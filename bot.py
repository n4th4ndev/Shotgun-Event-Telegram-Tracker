import asyncio
import html
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SHOTGUN_TOKEN = os.getenv("SHOTGUN_TOKEN")
ORGANIZER_ID = os.getenv("SHOTGUN_ORGANIZER_ID")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("botshotgun")

SHOTGUN_EVENTS_API = f"https://smartboard-api.shotgun.live/api/shotgun/organizers/{ORGANIZER_ID}/events"
SHOTGUN_TICKETS_API = "https://api.shotgun.live/tickets"
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
EVENTS_CACHE_TTL = 30
EVENT_STATS_CACHE_TTL = 15
MAX_HTTP_RETRIES = 3
MAX_DEAL_LINES = 12
SALES_POLL_INTERVAL = 60
RECENT_EVENTS_LIMIT = 8
STATE_FILE = os.path.join(os.path.dirname(__file__), "bot_state.json")
ALLOWED_CHAT_IDS = {
    int(chat_id.strip())
    for chat_id in os.getenv("BOTSHOTGUN_ALLOWED_CHAT_IDS", "").split(",")
    if chat_id.strip()
}


def format_eur(amount: float) -> str:
    return f"{amount:.2f} €"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_start_time(value: str | None) -> tuple[int, str]:
    if not value:
        return (1, "")

    dt = parse_dt(value)
    return (0, dt.isoformat() if dt else value)


def format_event_date(value: str | None) -> str:
    dt = parse_dt(value)
    if not dt:
        return "Date inconnue"
    return dt.astimezone().strftime("%d/%m/%Y %H:%M")


def is_recent_event(event: dict[str, Any]) -> bool:
    dt = parse_dt(event.get("start_time"))
    if dt is None:
        return False
    return dt < datetime.now(timezone.utc)


def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    ratio = max(0.0, min(1.0, current / total))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


class ShotgunAPIError(Exception):
    def __init__(self, user_message: str, *, log_message: str | None = None):
        super().__init__(log_message or user_message)
        self.user_message = user_message


class BotStateStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = asyncio.Lock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not os.path.exists(self.path):
            return {
                "subscribers": [],
                "event_snapshots": {},
                "event_catalog": {},
                "archived_events": {},
            }

        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
                payload.setdefault("subscribers", [])
                payload.setdefault("event_snapshots", {})
                payload.setdefault("event_catalog", {})
                payload.setdefault("archived_events", {})
                return payload
        except (OSError, json.JSONDecodeError):
            logger.warning("State file unreadable, recreating %s", self.path)
            return {
                "subscribers": [],
                "event_snapshots": {},
                "event_catalog": {},
                "archived_events": {},
            }

    async def save(self) -> None:
        tmp_path = f"{self.path}.tmp"
        async with self._lock:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, ensure_ascii=True, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)

    def subscribers(self) -> list[int]:
        return sorted({int(chat_id) for chat_id in self._state.get("subscribers", [])})

    async def subscribe(self, chat_id: int) -> bool:
        subscribers = set(self.subscribers())
        if chat_id in subscribers:
            return False
        subscribers.add(chat_id)
        self._state["subscribers"] = sorted(subscribers)
        await self.save()
        return True

    async def unsubscribe(self, chat_id: int) -> bool:
        subscribers = set(self.subscribers())
        if chat_id not in subscribers:
            return False
        subscribers.remove(chat_id)
        self._state["subscribers"] = sorted(subscribers)
        await self.save()
        return True

    def get_event_snapshot(self, event_id: str) -> dict[str, Any] | None:
        return self._state.get("event_snapshots", {}).get(str(event_id))

    async def set_event_snapshot(self, event_id: str, snapshot: dict[str, Any]) -> None:
        self._state.setdefault("event_snapshots", {})[str(event_id)] = snapshot
        await self.save()

    async def set_event_snapshots(self, snapshots: dict[str, dict[str, Any]]) -> None:
        self._state["event_snapshots"] = snapshots
        await self.save()

    def get_event_catalog_entry(self, event_id: str) -> dict[str, Any] | None:
        return self._state.get("event_catalog", {}).get(str(event_id))

    async def upsert_event_catalog_entry(
        self,
        event: dict[str, Any],
        snapshot: dict[str, Any] | None = None,
        stats: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "id": event["id"],
            "name": event["name"],
            "start_time": event.get("start_time"),
            "end_time": event.get("end_time"),
            "left_tickets": event.get("left_tickets", 0),
            "visibility": event.get("visibility"),
            "last_seen_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        if snapshot is not None:
            entry["snapshot"] = snapshot
        if stats is not None:
            entry["stats"] = stats
        self._state.setdefault("event_catalog", {})[str(event["id"])] = entry
        await self.save()

    def get_archived_event(self, event_id: str) -> dict[str, Any] | None:
        return self._state.get("archived_events", {}).get(str(event_id))

    def list_archived_events(self) -> list[dict[str, Any]]:
        events = list(self._state.get("archived_events", {}).values())
        events.sort(key=lambda item: parse_start_time(item.get("start_time")), reverse=True)
        return events

    async def archive_event(self, event_id: str, event_data: dict[str, Any]) -> None:
        self._state.setdefault("archived_events", {})[str(event_id)] = event_data
        await self.save()


class ShotgunClient:
    def __init__(self, token: str, organizer_id: str):
        self.token = token
        self.organizer_id = organizer_id
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=REQUEST_TIMEOUT,
        )
        self._events_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._stats_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._events_lock = asyncio.Lock()
        self._stats_locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        await self.client.aclose()

    def cache_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        events_valid = bool(self._events_cache and self._events_cache[0] > now)
        stats_valid = sum(1 for expires_at, _ in self._stats_cache.values() if expires_at > now)
        return {
            "events_cache_warm": events_valid,
            "stats_cache_entries": stats_valid,
            "stats_cache_total_keys": len(self._stats_cache),
        }

    async def get_events(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if not force_refresh and self._events_cache and self._events_cache[0] > now:
            return self._events_cache[1]

        async with self._events_lock:
            now = time.monotonic()
            if not force_refresh and self._events_cache and self._events_cache[0] > now:
                return self._events_cache[1]

            payload = await self._request_json(
                "GET",
                SHOTGUN_EVENTS_API,
                params={"key": self.token, "limit": 100},
                operation="fetch events",
            )

            events = []
            for event in payload.get("data", []):
                if event.get("cancelledAt"):
                    continue
                if not event.get("publishedAt") or not event.get("launchedAt"):
                    continue

                events.append(
                    {
                        "id": event["id"],
                        "name": event["name"],
                        "start_time": event.get("startTime"),
                        "end_time": event.get("endTime"),
                        "left_tickets": event.get("leftTicketsCount", 0),
                        "visibility": event.get("visibility"),
                    }
                )

            events.sort(key=lambda item: parse_start_time(item.get("start_time")))
            self._events_cache = (time.monotonic() + EVENTS_CACHE_TTL, events)
            logger.info("Fetched %s Shotgun event(s)", len(events))
            return events

    async def get_active_events(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        events = await self.get_events(force_refresh=force_refresh)
        return [event for event in events if not is_recent_event(event)]

    async def get_recent_events(self, force_refresh: bool = False, limit: int = RECENT_EVENTS_LIMIT) -> list[dict[str, Any]]:
        events = await self.get_events(force_refresh=force_refresh)
        recent_events = [event for event in events if is_recent_event(event)]
        recent_events.sort(key=lambda item: parse_start_time(item.get("start_time")), reverse=True)
        return recent_events[:limit]

    async def get_event_stats(self, event_id: str, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._stats_cache.get(event_id)
        if not force_refresh and cached and cached[0] > now:
            return cached[1]

        lock = self._stats_locks.setdefault(event_id, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            cached = self._stats_cache.get(event_id)
            if not force_refresh and cached and cached[0] > now:
                return cached[1]

            stats = {
                "total": 0,
                "valid": 0,
                "scanned": 0,
                "canceled": 0,
                "revenue": 0.0,
                "by_deal": {},
                "pages": 0,
            }

            next_url: str | None = SHOTGUN_TICKETS_API
            params: dict[str, Any] = {
                "organizer_id": self.organizer_id,
                "event_id": event_id,
                "limit": 100,
                # Sans ce flag l'API renvoie 0 ticket pour les événements
                # co-hébergés (où l'organisateur n'est pas l'hôte principal).
                "include_cohosted_events": "true",
            }

            while next_url:
                payload = await self._request_json(
                    "GET",
                    next_url,
                    params=params,
                    operation=f"fetch tickets for event {event_id}",
                )

                stats["pages"] += 1
                for ticket in payload.get("data", []):
                    stats["total"] += 1

                    status = ticket.get("ticket_status")
                    deal_title = ticket.get("deal_title") or "Sans nom"
                    deal_price = float(ticket.get("deal_price", 0) or 0) / 100

                    deal_stats = stats["by_deal"].setdefault(
                        deal_title,
                        {"sold": 0, "revenue": 0.0},
                    )

                    if status == "valid":
                        stats["valid"] += 1
                    elif status == "scanned":
                        stats["scanned"] += 1
                    elif status in {"canceled", "refunded"}:
                        stats["canceled"] += 1

                    if status in {"valid", "scanned"}:
                        stats["revenue"] += deal_price
                        deal_stats["sold"] += 1
                        deal_stats["revenue"] += deal_price

                next_url = payload.get("pagination", {}).get("next")
                params = None

            self._stats_cache[event_id] = (time.monotonic() + EVENT_STATS_CACHE_TTL, stats)
            logger.info(
                "Fetched stats for event %s: %s ticket(s), %s page(s)",
                event_id,
                stats["total"],
                stats["pages"],
            )
            return stats

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        operation: str,
    ) -> dict[str, Any]:
        delay = 1.0

        for attempt in range(1, MAX_HTTP_RETRIES + 1):
            started = time.perf_counter()
            try:
                response = await self.client.request(method, url, params=params)
                duration_ms = (time.perf_counter() - started) * 1000
                logger.info("%s attempt=%s status=%s duration_ms=%.0f", operation, attempt, response.status_code, duration_ms)

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else delay
                    if attempt == MAX_HTTP_RETRIES:
                        raise ShotgunAPIError(
                            "⏳ L'API Shotgun est temporairement saturée. Réessaie dans quelques secondes.",
                            log_message=f"Shotgun rate limited after {attempt} attempts",
                        )
                    await asyncio.sleep(wait_seconds)
                    delay *= 2
                    continue

                if response.status_code in {401, 403}:
                    raise ShotgunAPIError(
                        "🔐 Le bot n'arrive pas à accéder à l'API Shotgun. Vérifie les identifiants API.",
                        log_message=f"Shotgun auth failed with status {response.status_code}",
                    )

                if 500 <= response.status_code < 600:
                    if attempt == MAX_HTTP_RETRIES:
                        raise ShotgunAPIError(
                            "⚠️ L'API Shotgun rencontre un problème temporaire. Réessaie dans quelques instants.",
                            log_message=f"Shotgun server error {response.status_code}",
                        )
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue

                response.raise_for_status()
                return response.json()
            except httpx.RequestError as exc:
                if attempt == MAX_HTTP_RETRIES:
                    raise ShotgunAPIError(
                        "🌐 Impossible de joindre Shotgun pour le moment.",
                        log_message=f"Network error during {operation}: {exc}",
                    ) from exc
                logger.warning("%s attempt=%s failed: %s", operation, attempt, exc)
                await asyncio.sleep(delay)
                delay *= 2
            except ValueError as exc:
                raise ShotgunAPIError(
                    "⚠️ Réponse inattendue reçue depuis Shotgun.",
                    log_message=f"Invalid JSON during {operation}: {exc}",
                ) from exc

        raise ShotgunAPIError("⚠️ Impossible de récupérer les données Shotgun.")


def get_shotgun_client(context: ContextTypes.DEFAULT_TYPE) -> ShotgunClient:
    return context.application.bot_data["shotgun_client"]


def get_state_store(context: ContextTypes.DEFAULT_TYPE) -> BotStateStore:
    return context.application.bot_data["state_store"]


def get_chat_id(update: Update) -> int | None:
    if update.effective_chat is None:
        return None
    return update.effective_chat.id


async def ensure_authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True

    chat_id = get_chat_id(update)
    if chat_id in ALLOWED_CHAT_IDS:
        return True

    if update.callback_query:
        try:
            await update.callback_query.answer("Accès non autorisé", show_alert=True)
        except BadRequest:
            pass
    elif update.message:
        await update.message.reply_text("⛔ Accès non autorisé.")
    return False


def compute_event_snapshot(event: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    sold = stats["valid"] + stats["scanned"]
    return {
        "name": event["name"],
        "sold": sold,
        "scanned": stats["scanned"],
        "canceled": stats["canceled"],
        "revenue": round(stats["revenue"], 2),
        "left_tickets": event["left_tickets"],
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def build_archived_event_record(event: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": event["id"],
        "name": event["name"],
        "start_time": event.get("start_time"),
        "end_time": event.get("end_time"),
        "left_tickets": event.get("left_tickets", 0),
        "visibility": event.get("visibility"),
        "snapshot": snapshot or {},
        "archived_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


async def safe_edit_message(query, text: str, reply_markup=None, parse_mode=None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            logger.info("Ignoring duplicate Telegram edit for callback %s", query.data)
            return
        raise


async def answer_query_safely(query, text: str | None = None) -> None:
    try:
        await query.answer(text)
    except BadRequest as exc:
        logger.warning("Telegram callback answer failed for %s: %s", query.data, exc)


async def log_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


async def post_init(application: Application) -> None:
    application.bot_data["shotgun_client"] = ShotgunClient(SHOTGUN_TOKEN, ORGANIZER_ID)
    application.bot_data["state_store"] = BotStateStore(STATE_FILE)
    logger.info("Shotgun client initialized")


async def post_shutdown(application: Application) -> None:
    client: ShotgunClient | None = application.bot_data.get("shotgun_client")
    if client is not None:
        await client.close()
        logger.info("Shotgun client closed")


async def warm_events_cache(context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_shotgun_client(context)
    try:
        await client.get_active_events(force_refresh=True)
    except ShotgunAPIError as exc:
        logger.warning("Background events refresh failed: %s", exc)


async def notify_subscribers(application: Application, message: str) -> None:
    store: BotStateStore = application.bot_data["state_store"]
    for chat_id in store.subscribers():
        try:
            await application.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Failed to notify chat %s: %s", chat_id, exc)


async def monitor_sales(context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_shotgun_client(context)
    store = get_state_store(context)

    try:
        events = await client.get_active_events(force_refresh=True)
    except ShotgunAPIError as exc:
        logger.warning("Sales monitor events refresh failed: %s", exc)
        return

    next_snapshots: dict[str, dict[str, Any]] = {}
    notifications: list[str] = []
    live_event_ids: set[str] = set()

    for event in events:
        event_id = str(event["id"])
        live_event_ids.add(event_id)
        try:
            stats = await client.get_event_stats(event_id, force_refresh=True)
        except ShotgunAPIError as exc:
            logger.warning("Sales monitor stats refresh failed for %s: %s", event_id, exc)
            continue

        snapshot = compute_event_snapshot(event, stats)
        next_snapshots[event_id] = snapshot
        await store.upsert_event_catalog_entry(event, snapshot, stats)
        previous = store.get_event_snapshot(event_id)
        if previous is None:
            if is_recent_event(event):
                await store.archive_event(event_id, build_archived_event_record(event, stats))
            continue

        sold_delta = snapshot["sold"] - int(previous.get("sold", 0))
        revenue_delta = round(snapshot["revenue"] - float(previous.get("revenue", 0.0)), 2)
        scanned_delta = snapshot["scanned"] - int(previous.get("scanned", 0))

        if sold_delta <= 0 and revenue_delta <= 0 and scanned_delta <= 0:
            continue

        notifications.append(
            (
                f"🚀 <b>{html.escape(snapshot['name'])}</b>\n"
                f"Billets vendus : +{sold_delta}\n"
                f"Scannés : +{scanned_delta}\n"
                f"CA : +{format_eur(max(revenue_delta, 0.0))}\n"
                f"Restants : {snapshot['left_tickets']}"
            )
        )

        if is_recent_event(event):
            await store.archive_event(event_id, build_archived_event_record(event, stats))

    if notifications:
        for message in notifications:
            await notify_subscribers(context.application, message)

    if next_snapshots:
        await store.set_event_snapshots(next_snapshots)

    for event_id, catalog_entry in list(store._state.get("event_catalog", {}).items()):
        if event_id in live_event_ids:
            continue

        archived = store.get_archived_event(event_id)
        if archived is not None:
            continue

        snapshot = catalog_entry.get("stats") or store.get_event_snapshot(event_id) or catalog_entry.get("snapshot", {})
        await store.archive_event(
            event_id,
            {
                "id": int(event_id),
                "name": catalog_entry.get("name"),
                "start_time": catalog_entry.get("start_time"),
                "end_time": catalog_entry.get("end_time"),
                "left_tickets": catalog_entry.get("left_tickets", 0),
                "visibility": catalog_entry.get("visibility"),
                "snapshot": snapshot,
                "archived_at": datetime.utcnow().isoformat(timespec="seconds"),
            },
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    keyboard = [
        [InlineKeyboardButton("📅 Mes Événements", callback_data="list_events")],
        [InlineKeyboardButton("📈 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("🕘 Anciens", callback_data="recent_events")],
        [InlineKeyboardButton("🔔 Notifications", callback_data="notifications")],
        [InlineKeyboardButton("ℹ️ Aide", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        "👋 <b>Bonjour !</b>\n\n"
        "Je suis ton assistant Shotgun. Je peux t'aider à suivre tes ventes en temps réel.\n"
        "Clique sur un bouton pour commencer."
    )

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await safe_edit_message(update.callback_query, welcome_text, reply_markup=reply_markup, parse_mode="HTML")


async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    query = update.callback_query
    await answer_query_safely(query, "Chargement des événements...")

    client = get_shotgun_client(context)
    try:
        force_refresh = query.data == "refresh_events"
        events = await client.get_active_events(force_refresh=force_refresh)
    except ShotgunAPIError as exc:
        await safe_edit_message(query, exc.user_message)
        return

    if not events:
        await safe_edit_message(query, "📭 Aucun événement actif trouvé.")
        return

    keyboard = [
        [InlineKeyboardButton(f"🎉 {event['name']}", callback_data=f"evt_{event['id']}")]
        for event in events
    ]
    keyboard.append([InlineKeyboardButton("🔄 Actualiser", callback_data="refresh_events")])
    keyboard.append([InlineKeyboardButton("🕘 Voir les anciens", callback_data="recent_events")])
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data="start")])

    await safe_edit_message(
        query,
        f"📅 <b>{len(events)} événement(s) actif(s) :</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def recent_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    query = update.callback_query
    await answer_query_safely(query, "Chargement des anciens événements...")

    client = get_shotgun_client(context)
    store = get_state_store(context)
    try:
        force_refresh = query.data == "refresh_recent_events"
        api_recent_events = await client.get_recent_events(force_refresh=force_refresh)
    except ShotgunAPIError as exc:
        await safe_edit_message(query, exc.user_message)
        return

    archived_by_id = {str(event["id"]): event for event in store.list_archived_events()}
    for event in api_recent_events:
        archived_by_id[str(event["id"])] = event
    events = sorted(
        archived_by_id.values(),
        key=lambda item: parse_start_time(item.get("start_time")),
        reverse=True,
    )[:RECENT_EVENTS_LIMIT]

    if not events:
        await safe_edit_message(query, "📭 Aucun ancien événement trouvé.")
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"🕘 {event['name']} • {format_event_date(event['start_time'])}",
                callback_data=f"evt_{event['id']}",
            )
        ]
        for event in events
    ]
    keyboard.append([InlineKeyboardButton("🔄 Actualiser", callback_data="refresh_recent_events")])
    keyboard.append([InlineKeyboardButton("📅 Actifs", callback_data="list_events")])
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data="start")])

    await safe_edit_message(
        query,
        f"🕘 <b>{len(events)} ancien(s) événement(s) récent(s)</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


def build_event_detail_text(event: dict[str, Any], stats: dict[str, Any]) -> str:
    event_name = html.escape(event["name"])
    sold = stats["valid"] + stats["scanned"]
    capacity = sold + max(int(event["left_tickets"]), 0)
    status_label = "🕘 Terminé" if is_recent_event(event) else "🟢 Actif / à venir"
    detail_text = (
        f"🎉 <b>{event_name}</b>\n\n"
        f"{status_label}\n"
        f"🗓️ {format_event_date(event.get('start_time'))}\n"
        f"📊 <b>Résumé Global :</b>\n"
        f"🎟️ Total billets : {stats['total']}\n"
        f"✅ Valides : {stats['valid']}\n"
        f"🔍 Scannés : {stats['scanned']}\n"
        f"❌ Annulés : {stats['canceled']}\n"
        f"💰 <b>Revenus totaux : {format_eur(stats['revenue'])}</b>\n"
        f"📈 Remplissage : {progress_bar(sold, capacity)} {sold}/{capacity if capacity else sold}\n\n"
    )

    if stats["by_deal"]:
        detail_text += "🎫 <b>Détails par type de billet :</b>\n"
        sorted_deals = sorted(
            stats["by_deal"].items(),
            key=lambda item: (-item[1]["revenue"], -item[1]["sold"], item[0].lower()),
        )

        for deal_name, deal_stats in sorted_deals[:MAX_DEAL_LINES]:
            safe_deal_name = html.escape(deal_name)
            detail_text += f"\n• <b>{safe_deal_name}</b>\n"
            detail_text += f"Vendus : {deal_stats['sold']} | CA : {format_eur(deal_stats['revenue'])}\n"

        remaining = len(sorted_deals) - MAX_DEAL_LINES
        if remaining > 0:
            detail_text += f"\n… et {remaining} autre(s) type(s) de billet"

    detail_text += f"\n\n🎫 Billets restants : {event['left_tickets']}"
    detail_text += f"\n⚡ Cache stats : {EVENT_STATS_CACHE_TTL}s"
    detail_text += "\n⏱️ <i>Dernière mise à jour : à l'instant</i>"
    return detail_text


def build_dashboard_text(events_with_stats: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    total_events = len(events_with_stats)
    total_sold = 0
    total_scanned = 0
    total_canceled = 0
    total_revenue = 0.0

    lines = ["📈 <b>Dashboard Global</b>\n"]
    for index, (event, stats) in enumerate(sorted(
        events_with_stats,
        key=lambda item: (-item[1]["revenue"], -(item[1]["valid"] + item[1]["scanned"]), item[0]["name"].lower()),
    ), start=1):
        sold = stats["valid"] + stats["scanned"]
        capacity = sold + max(int(event["left_tickets"]), 0)
        rank = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, "•")
        total_sold += sold
        total_scanned += stats["scanned"]
        total_canceled += stats["canceled"]
        total_revenue += stats["revenue"]
        lines.append(
            (
                f"\n{rank} <b>{html.escape(event['name'])}</b>\n"
                f"{format_event_date(event.get('start_time'))}\n"
                f"Vendus : {sold} | Scannés : {stats['scanned']}\n"
                f"CA : {format_eur(stats['revenue'])} | Restants : {event['left_tickets']}\n"
                f"{progress_bar(sold, capacity)}"
            )
        )

    lines.insert(
        1,
        (
            f"{total_events} événement(s) actif(s)\n"
            f"Billets vendus : {total_sold}\n"
            f"Scannés : {total_scanned}\n"
            f"Annulés : {total_canceled}\n"
            f"CA total : <b>{format_eur(total_revenue)}</b>\n"
        ),
    )
    return "".join(lines)


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    client = get_shotgun_client(context)
    query = update.callback_query
    force_refresh = False

    if query:
        await answer_query_safely(query, "Chargement du dashboard...")
        force_refresh = query.data == "refresh_dashboard"

    try:
        events = await client.get_active_events(force_refresh=force_refresh)
        events_with_stats = []
        for event in events:
            stats = await client.get_event_stats(str(event["id"]), force_refresh=force_refresh)
            events_with_stats.append((event, stats))
    except ShotgunAPIError as exc:
        if query:
            await safe_edit_message(query, exc.user_message)
        else:
            await update.message.reply_text(exc.user_message)
        return

    if not events_with_stats:
        text = "📭 Aucun événement actif trouvé."
    else:
        text = build_dashboard_text(events_with_stats)

    keyboard = [
        [InlineKeyboardButton("🔄 Actualiser", callback_data="refresh_dashboard")],
        [InlineKeyboardButton("📅 Événements", callback_data="list_events")],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data="start")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await safe_edit_message(query, text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def notifications_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    store = get_state_store(context)
    query = update.callback_query
    chat_id = get_chat_id(update)
    is_subscribed = chat_id in store.subscribers() if chat_id is not None else False

    text = (
        "🔔 <b>Notifications</b>\n\n"
        f"Etat du chat : {'abonné' if is_subscribed else 'non abonné'}\n"
        f"Intervalle de surveillance : {SALES_POLL_INTERVAL}s\n"
        "Le bot envoie un message quand il détecte de nouvelles ventes, scans ou une hausse du CA."
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "🔕 Se désabonner" if is_subscribed else "🔔 S'abonner",
                callback_data="unsubscribe_me" if is_subscribed else "subscribe_me",
            )
        ],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data="start")],
    ]

    await safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def event_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    query = update.callback_query
    await answer_query_safely(query, "Chargement des stats...")

    force_refresh = query.data.startswith("refresh_evt_")
    event_id = query.data.removeprefix("refresh_evt_").removeprefix("evt_")

    client = get_shotgun_client(context)
    store = get_state_store(context)
    try:
        events = await client.get_events(force_refresh=force_refresh)
        event = next((item for item in events if str(item["id"]) == event_id), None)
        if event is not None:
            stats = await client.get_event_stats(event_id, force_refresh=force_refresh)
        else:
            archived_event = store.get_archived_event(event_id)
            if archived_event is None:
                await safe_edit_message(query, "❌ Événement introuvable.")
                return
            event = archived_event
            stats = archived_event.get(
                "snapshot",
                {
                    "total": 0,
                    "valid": 0,
                    "scanned": 0,
                    "canceled": 0,
                    "revenue": 0.0,
                    "by_deal": {},
                    "pages": 0,
                },
            )
    except ShotgunAPIError as exc:
        await safe_edit_message(query, exc.user_message)
        return

    keyboard = [
        [InlineKeyboardButton("🔄 Actualiser", callback_data=f"refresh_evt_{event_id}")],
        [InlineKeyboardButton("🔙 Liste des événements", callback_data="list_events")],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data="start")],
    ]

    await safe_edit_message(
        query,
        build_event_detail_text(event, stats),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    text = (
        "ℹ️ <b>Aide</b>\n\n"
        "Ce bot se connecte à ton compte Shotgun pour afficher tes statistiques.\n"
        "Utilise le bouton événements pour consulter les ventes, Dashboard pour la vue globale,\n"
        "Anciens pour revoir les événements passés,\n"
        "et Actualiser pour forcer un refresh API.\n\n"
        "Commandes utiles :\n"
        "/dashboard\n"
        "/recent\n"
        "/health\n"
        "/notifications\n"
        "/subscribe\n"
        "/unsubscribe"
    )
    keyboard = [[InlineKeyboardButton("🔙 Retour", callback_data="start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await answer_query_safely(update.callback_query)
        await safe_edit_message(update.callback_query, text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    client = get_shotgun_client(context)
    store = get_state_store(context)
    snapshot = client.cache_snapshot()
    text = (
        "🩺 <b>État du bot</b>\n\n"
        f"Events cache chaud : {'oui' if snapshot['events_cache_warm'] else 'non'}\n"
        f"Stats cache actives : {snapshot['stats_cache_entries']}\n"
        f"Clés stats suivies : {snapshot['stats_cache_total_keys']}\n"
        f"Abonnés notifications : {len(store.subscribers())}\n"
        f"Archives locales : {len(store.list_archived_events())}\n"
        f"TTL events : {EVENTS_CACHE_TTL}s\n"
        f"TTL stats : {EVENT_STATS_CACHE_TTL}s"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    client = get_shotgun_client(context)
    store = get_state_store(context)
    try:
        api_recent_events = await client.get_recent_events(force_refresh=True)
    except ShotgunAPIError as exc:
        await update.message.reply_text(exc.user_message)
        return

    archived_by_id = {str(event["id"]): event for event in store.list_archived_events()}
    for event in api_recent_events:
        archived_by_id[str(event["id"])] = event
    events = sorted(
        archived_by_id.values(),
        key=lambda item: parse_start_time(item.get("start_time")),
        reverse=True,
    )[:RECENT_EVENTS_LIMIT]

    if not events:
        await update.message.reply_text("📭 Aucun ancien événement trouvé.")
        return

    lines = ["🕘 <b>Anciens événements</b>\n"]
    for event in events:
        lines.append(f"\n• <b>{html.escape(event['name'])}</b>\n{format_event_date(event['start_time'])}")
    await update.message.reply_text("".join(lines), parse_mode="HTML")


async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    store = get_state_store(context)
    chat_id = get_chat_id(update)
    is_subscribed = chat_id in store.subscribers() if chat_id is not None else False
    text = (
        "🔔 <b>Notifications</b>\n\n"
        f"Etat du chat : {'abonné' if is_subscribed else 'non abonné'}\n"
        f"Intervalle : {SALES_POLL_INTERVAL}s"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    chat_id = get_chat_id(update)
    if chat_id is None:
        return

    store = get_state_store(context)
    created = await store.subscribe(chat_id)
    text = "🔔 Notifications activées pour ce chat." if created else "🔔 Ce chat reçoit déjà les notifications."
    await update.message.reply_text(text)


async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    chat_id = get_chat_id(update)
    if chat_id is None:
        return

    store = get_state_store(context)
    removed = await store.unsubscribe(chat_id)
    text = "🔕 Notifications désactivées pour ce chat." if removed else "🔕 Ce chat n'était pas abonné."
    await update.message.reply_text(text)


async def subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    query = update.callback_query
    chat_id = get_chat_id(update)
    if chat_id is None:
        return

    store = get_state_store(context)
    await store.subscribe(chat_id)
    await answer_query_safely(query, "Notifications activées")
    await notifications_panel(update, context)


async def unsubscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await ensure_authorized(update):
        return

    query = update.callback_query
    chat_id = get_chat_id(update)
    if chat_id is None:
        return

    store = get_state_store(context)
    await store.unsubscribe(chat_id)
    await answer_query_safely(query, "Notifications désactivées")
    await notifications_panel(update, context)


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("Erreur : TELEGRAM_BOT_TOKEN n'est pas défini dans le fichier .env")
        return
    if not SHOTGUN_TOKEN or not ORGANIZER_ID:
        print("Erreur : SHOTGUN_TOKEN ou SHOTGUN_ORGANIZER_ID manquant dans le fichier .env")
        return

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    if application.job_queue is not None:
        application.job_queue.run_repeating(warm_events_cache, interval=60, first=5)
        application.job_queue.run_repeating(monitor_sales, interval=SALES_POLL_INTERVAL, first=10)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("recent", recent_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("notifications", notifications_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    application.add_handler(CallbackQueryHandler(start, pattern="^start$"))
    application.add_handler(CallbackQueryHandler(list_events, pattern="^(list_events|refresh_events)$"))
    application.add_handler(CallbackQueryHandler(dashboard, pattern="^(dashboard|refresh_dashboard)$"))
    application.add_handler(CallbackQueryHandler(recent_events, pattern="^(recent_events|refresh_recent_events)$"))
    application.add_handler(CallbackQueryHandler(notifications_panel, pattern="^notifications$"))
    application.add_handler(CallbackQueryHandler(subscribe_callback, pattern="^subscribe_me$"))
    application.add_handler(CallbackQueryHandler(unsubscribe_callback, pattern="^unsubscribe_me$"))
    application.add_handler(CallbackQueryHandler(help_command, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(event_detail, pattern="^(evt_|refresh_evt_)"))
    application.add_error_handler(log_error)

    logger.info("BOTSHOTGUN starting in polling mode")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        poll_interval=2.0,
        timeout=30,
    )


if __name__ == "__main__":
    main()

<p align="center">
  <a href="https://shotgun.live">
    <img src="https://www.google.com/s2/favicons?domain=shotgun.live&sz=128" alt="Shotgun" width="72" height="72">
  </a>
</p>

<h1 align="center">🤖 Shotgun Bot — Telegram</h1>

<p align="center">
  <b>Unofficial</b> Telegram bot to track your
  <a href="https://shotgun.live">Shotgun</a> event sales in real time: per-event statistics,
  global dashboard, history of past events and automatic sales notifications.
</p>

<p align="center">
  <a href="https://shotgun.live">🌐 Shotgun website</a> ·
  <a href="https://organizer.shotgun.live">🎛️ Organizer dashboard</a> ·
  <a href="https://t.me/BotFather">🤖 BotFather</a>
</p>

<p align="center">
  <a href="README.md">🇫🇷 Français</a> ·
  <b>🇬🇧 English</b>
</p>

---

## 📋 Features

- 📅 **Active events**: list all your published, launched and non-cancelled events
- 📊 **Detailed statistics** per event:
  - Tickets sold, valid, scanned, cancelled
  - Total revenue
  - **Breakdown by ticket type** (name, quantity sold, revenue)
  - Remaining tickets available
- 📈 **Global dashboard**: aggregated view across all your active events (total sales, revenue, remaining)
- 🕘 **History**: browse past / archived events kept in local state
- 🔔 **Real-time notifications**: a background job polls sales and **pushes a message to subscribers** whenever tickets are sold or scanned (`+sold`, `+revenue`, `+scanned`, remaining)
- 🩺 **Health command**: inspect cache state, subscribers, archives and TTLs
- ⚡ **Caching layer**: short-TTL caches for events/stats plus a warm-up job to keep the API responsive
- 🔒 **Access control**: optional allow-list of Telegram chat IDs
- 💾 **Persistent state**: subscribers, sales snapshots and event archive stored in `bot_state.json`

## 🚀 Installation

### 1. Prerequisites

- Python 3.11+
- Shotgun account with organizer access
- Telegram bot (created via [@BotFather](https://t.me/BotFather))

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit the `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_telegram_token
SHOTGUN_TOKEN=your_shotgun_token
SHOTGUN_ORGANIZER_ID=your_organizer_id
# Optional: comma-separated Telegram chat IDs allowed to use the bot.
# Leave empty to allow everyone.
BOTSHOTGUN_ALLOWED_CHAT_IDS=
```

#### 🔑 Where to find your Shotgun credentials?

1. **Shotgun Token**: log in to your [organizer dashboard](https://organizer.shotgun.live) → integration > API
2. **Organizer ID**: visible in your Shotgun dashboard URL, or in the JSON response of API requests
3. **Telegram Token**: talk to [@BotFather](https://t.me/BotFather), type `/newbot` and follow the instructions
4. **Allowed chat IDs** (optional): message the bot, check the logs for your chat ID, then add it to `BOTSHOTGUN_ALLOWED_CHAT_IDS`

## 🎯 Usage

### Start the bot

```bash
python3 bot.py
```

The bot starts in polling mode, launches the background sales-monitor job, and waits for commands.

### Telegram commands

| Command | Description |
| --- | --- |
| `/start` | Main menu with buttons |
| `/dashboard` | Global aggregated stats across all active events |
| `/recent` | List past / archived events |
| `/notifications` | Notifications panel (subscribe status) |
| `/subscribe` | Receive real-time sales notifications |
| `/unsubscribe` | Stop receiving notifications |
| `/health` | Bot diagnostics (cache, subscribers, archives, TTLs) |
| `/help` | Help message |

The main menu exposes the same actions as buttons: **📅 My Events**, **📈 Dashboard**, **🕘 Past**, **🔔 Notifications**, **ℹ️ Help**, plus a **🔄 Refresh** button to force an API refresh.

### Example: per-event detail

```
🎉 [Event Name]

📊 Global Summary:
🎟️ Total tickets: 69
✅ Valid: 62
🔍 Scanned: 0
❌ Cancelled: 2
💰 Total revenue: 985.00 €

🎫 Breakdown by ticket type:

• [Ticket Type 1]
  └ Sold: 51 | Revenue: 765.00 €

• [Ticket Type 2]
  └ Sold: 11 | Revenue: 220.00 €

🎫 Remaining tickets: 238
```

### Example: sales notification (pushed automatically)

```
🚀 [Event Name]
Tickets sold: +3
Scanned: +0
Revenue: +45.00 €
Remaining: 235
```

## 🛠️ Utility scripts

### Restart the bot cleanly

If you encounter conflicts (error "Conflict: terminated by other getUpdates"):

```bash
./restart_bot.sh
```

This script kills only **this** bot instance (targeted by absolute path so it does not affect other `bot.py` processes), resets the Telegram webhook, then restarts.

### Reset webhook manually

```bash
python3 reset_webhook.py
```

## ⚙️ Configuration reference

These tunables live at the top of `bot.py`:

| Constant | Default | Meaning |
| --- | --- | --- |
| `EVENTS_CACHE_TTL` | `30s` | Events list cache lifetime |
| `EVENT_STATS_CACHE_TTL` | `15s` | Per-event stats cache lifetime |
| `SALES_POLL_INTERVAL` | `60s` | Background sales-monitor interval |
| `RECENT_EVENTS_LIMIT` | `8` | Max past events shown |
| `MAX_HTTP_RETRIES` | `3` | HTTP retry attempts |
| `MAX_DEAL_LINES` | `12` | Max ticket-type lines per event |

## 📁 Project structure

```
BOTSHOTGUN/
├── bot.py                 # Main bot code (menus, dashboard, notifications, caching)
├── requirements.txt       # Python dependencies
├── .env                   # Configuration (to create, not committed)
├── .env.example           # Configuration example
├── bot_state.json         # Runtime state: subscribers, snapshots, archives (not committed)
├── reset_webhook.py       # Reset the Telegram webhook
├── restart_bot.sh         # Clean restart script
└── README.md              # French readme (README.en.md = this file)
```

## 🔧 Troubleshooting

### Error "Conflict: terminated by other getUpdates"
Multiple bot instances are running. Run `./restart_bot.sh`.

### Error "Missing organizer_id"
Token or organizer ID is incorrect. Check your `.env`.

### "Accès non autorisé" (access denied)
Your chat ID is not in `BOTSHOTGUN_ALLOWED_CHAT_IDS`. Add it, or leave the variable empty to allow everyone.

### Incorrect prices
The Shotgun API returns prices in cents; the bot divides by 100 automatically.

## 📡 APIs used

- **Shotgun Events API**: `https://smartboard-api.shotgun.live/api/shotgun/organizers/{id}/events` — lists events
- **Shotgun Tickets API**: `https://api.shotgun.live/tickets` — retrieves sold ticket details

## 📝 Notes

- Runs in **polling mode** (no webhook)
- Stats are cached briefly (short TTLs) and refreshed on demand or by the background job
- Prices are automatically converted from cents to euros
- Only **published, launched, and non-cancelled** events are listed as active
- `bot_state.json` is runtime data — do not hand-edit unless fixing corrupted state

---

## ⚠️ Disclaimer / Legal notice

This project is a **personal and unofficial** tool. It is **in no way affiliated with, associated with, authorized, endorsed by, or officially connected to Shotgun** (Shotgun Live SAS) or any of its subsidiaries.

"Shotgun", the Shotgun logo and all related names, marks and signs are the **exclusive property of their respective owners** and are used here only for identification and reference purposes. All trademarks mentioned belong to their respective owners.

This bot uses Shotgun APIs with the organizer's credentials; you are responsible for complying with Shotgun's terms of service. Use at your own risk, without any warranty.

## 📄 License

For personal use.

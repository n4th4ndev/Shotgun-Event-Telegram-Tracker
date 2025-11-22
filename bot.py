import os
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
from flask import Flask, request as flask_request

# Load environment variables
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SHOTGUN_TOKEN = os.getenv("SHOTGUN_TOKEN")
ORGANIZER_ID = os.getenv("SHOTGUN_ORGANIZER_ID")
PORT = int(os.getenv("PORT", 5000))

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

SHOTGUN_EVENTS_API = f"https://smartboard-api.shotgun.live/api/shotgun/organizers/{ORGANIZER_ID}/events"
SHOTGUN_TICKETS_API = "https://api.shotgun.live/tickets"

# Flask app for webhook
app = Flask(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message with the main menu."""
    keyboard = [
        [InlineKeyboardButton("📅 Mes Événements", callback_data='list_events')],
        [InlineKeyboardButton("ℹ️ Aide", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 *Bonjour !* \n\n"
        "Je suis ton assistant Shotgun. Je peux t'aider à suivre tes ventes en temps réel.\n"
        "Clique sur un bouton pour commencer."
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def get_active_events():
    """Fetches active events from Shotgun Events API."""
    headers = {
        "Authorization": f"Bearer {SHOTGUN_TOKEN}"
    }
    params = {
        "key": SHOTGUN_TOKEN,
        "limit": 50
    }
    
    try:
        print(f"DEBUG: Fetching events from {SHOTGUN_EVENTS_API}")
        response = requests.get(SHOTGUN_EVENTS_API, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"DEBUG: Error Response: {response.text}")
            return None
            
        data = response.json().get('data', [])
        print(f"DEBUG: Found {len(data)} events")
        
        # Filter for active events (not cancelled, and in the future or ongoing)
        active_events = []
        now = datetime.now()
        
        for event in data:
            # Skip cancelled events
            if event.get('cancelledAt'):
                continue
            
            # Check if event is published and launched
            if not event.get('publishedAt') or not event.get('launchedAt'):
                continue
                
            active_events.append({
                'id': event['id'],
                'name': event['name'],
                'start_time': event.get('startTime'),
                'left_tickets': event.get('leftTicketsCount', 0),
                'visibility': event.get('visibility')
            })
        
        print(f"DEBUG: {len(active_events)} active events")
        return active_events

    except Exception as e:
        logging.error(f"Error fetching events: {e}")
        print(f"DEBUG: Exception: {e}")
        return None

async def get_event_stats(event_id):
    """Fetches ticket stats for a specific event with pagination."""
    headers = {
        "Authorization": f"Bearer {SHOTGUN_TOKEN}"
    }
    
    stats = {
        'total': 0,
        'valid': 0,
        'scanned': 0,
        'canceled': 0,
        'revenue': 0.0,
        'by_deal': {}  # Breakdown by ticket type
    }
    
    try:
        url = SHOTGUN_TICKETS_API
        params = {
            "organizer_id": ORGANIZER_ID,
            "event_id": event_id,
            "limit": 100  # Max per page
        }
        
        page = 0
        
        # Fetch all pages
        while url:
            page += 1
            print(f"DEBUG: Fetching tickets page {page} for event {event_id}")
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"DEBUG: Error Response: {response.text}")
                return None
            
            json_resp = response.json()
            data = json_resp.get('data', [])
            
            print(f"DEBUG: Page {page}: {len(data)} tickets")
            
            # Process tickets
            for ticket in data:
                stats['total'] += 1
                
                status = ticket.get('ticket_status')
                deal_title = ticket.get('deal_title', 'Sans nom')
                deal_price = float(ticket.get('deal_price', 0)) / 100  # Convert cents to euros
                
                # Initialize deal stats if not exists
                if deal_title not in stats['by_deal']:
                    stats['by_deal'][deal_title] = {
                        'sold': 0,
                        'revenue': 0.0
                    }
                
                # Count by status
                if status == 'valid':
                    stats['valid'] += 1
                elif status == 'scanned':
                    stats['scanned'] += 1
                elif status in ['canceled', 'refunded']:
                    stats['canceled'] += 1
                    
                # Add revenue and count for valid/scanned tickets
                if status in ['valid', 'scanned']:
                    stats['revenue'] += deal_price
                    stats['by_deal'][deal_title]['sold'] += 1
                    stats['by_deal'][deal_title]['revenue'] += deal_price
            
            # Check for next page
            pagination = json_resp.get('pagination', {})
            next_url = pagination.get('next')
            
            if next_url:
                # The next_url might be a full URL or a relative path, or just query params.
                # The documentation says "link to the next page", usually a full URL in modern APIs.
                # If it's just the path, we might need to prepend the base URL, but usually it's full.
                # Let's assume it's a full URL for now, or handle if it's not.
                url = next_url
                params = {}  # Params are usually included in the next_url
            else:
                url = None
        
        print(f"DEBUG: Event {event_id} total stats: {stats['total']} tickets across {page} page(s)")
        return stats

    except Exception as e:
        logging.error(f"Error fetching event stats: {e}")
        print(f"DEBUG: Exception: {e}")
        return None

async def list_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and lists active events as buttons."""
    query = update.callback_query
    try:
        await query.answer("Chargement des événements...")
    except Exception as e:
        print(f"DEBUG: query.answer failed: {e}")
    
    events = await get_active_events()
    
    if events is None:
        await query.edit_message_text("❌ Erreur lors de la récupération des événements.")
        return

    if not events:
        await query.edit_message_text("📭 Aucun événement actif trouvé.")
        return

    keyboard = []
    for event in events:
        btn_text = f"🎉 {event['name']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"evt_{event['id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data='start')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"📅 *{len(events)} événement(s) actif(s) :*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def event_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows details for a specific event."""
    query = update.callback_query
    try:
        await query.answer("Chargement des stats...")
    except Exception as e:
        print(f"DEBUG: query.answer failed: {e}")
    
    event_id = query.data.split('_')[1]
    
    # Get event info
    events = await get_active_events()
    if not events:
        await query.edit_message_text("❌ Impossible de trouver l'événement.")
        return
    
    event = next((e for e in events if str(e['id']) == event_id), None)
    if not event:
        await query.edit_message_text("❌ Événement introuvable.")
        return
    
    # Get ticket stats
    stats = await get_event_stats(event_id)
    if stats is None:
        await query.edit_message_text("❌ Erreur lors de la récupération des stats.")
        return
    
    # Build detail text with breakdown by ticket type
    detail_text = (
        f"🎉 *{event['name']}*\n\n"
        f"📊 *Résumé Global :*\n"
        f"🎟️ Total billets : {stats['total']}\n"
        f"✅ Valides : {stats['valid']}\n"
        f"🔍 Scannés : {stats['scanned']}\n"
        f"❌ Annulés : {stats['canceled']}\n"
        f"💰 *Revenus totaux : {stats['revenue']:.2f} €*\n\n"
    )
    
    # Add breakdown by ticket type
    if stats['by_deal']:
        detail_text += "🎫 *Détails par type de billet :*\n"
        for deal_name, deal_stats in stats['by_deal'].items():
            detail_text += f"\n• *{deal_name}*\n"
            detail_text += f"  └ Vendus : {deal_stats['sold']} | Solde : {deal_stats['revenue']:.2f} €\n"
    
    detail_text += f"\n🎫 Billets restants : {event['left_tickets']}\n"
    detail_text += f"_Dernière mise à jour : à l'instant_"
    
    keyboard = [
        [InlineKeyboardButton("🔄 Actualiser", callback_data=f"evt_{event_id}")],
        [InlineKeyboardButton("🔙 Liste des événements", callback_data='list_events')],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data='start')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(detail_text, reply_markup=reply_markup, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    text = (
        "ℹ️ *Aide*\n\n"
        "Ce bot se connecte à ton compte Shotgun pour afficher tes statistiques.\n"
        "Assure-toi que tes clés API sont correctement configurées dans le fichier `.env`."
    )
    keyboard = [[InlineKeyboardButton("🔙 Retour", callback_data='start')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

def main():
    if not TELEGRAM_TOKEN:
        print("Erreur : TELEGRAM_BOT_TOKEN n'est pas défini dans le fichier .env")
        return

    # Build application
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern='^start$'))
    application.add_handler(CallbackQueryHandler(list_events, pattern='^list_events$'))
    application.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    application.add_handler(CallbackQueryHandler(event_detail, pattern='^evt_'))

    print("🤖 Le bot est en cours d'exécution en mode POLLING...")
    print("⚠️  Si tu as des conflits, ferme TOUS les terminaux et attends 30 secondes avant de relancer.")
    
    # Use drop_pending_updates and a higher timeout
    application.run_polling(
        drop_pending_updates=True, 
        allowed_updates=Update.ALL_TYPES,
        poll_interval=2.0,
        timeout=30
    )

if __name__ == '__main__':
    main()

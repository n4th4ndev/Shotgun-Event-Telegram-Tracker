# 🤖 Shotgun Bot - Telegram

Telegram bot to track your Shotgun event sales in real-time.

## 📋 Features

- 📅 **List active events**: Displays all your published and non-cancelled events
- 📊 **Detailed statistics** per event:
  - Total tickets sold
  - Valid, scanned, and cancelled tickets
  - Total revenue
  - **Breakdown by ticket type** (name, quantity sold, revenue)
  - Remaining tickets available
- 🔄 **Real-time updates**: Stats are fetched on each request

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

Edit the `.env` file with your keys:

```env
TELEGRAM_BOT_TOKEN=your_telegram_token
SHOTGUN_TOKEN=your_shotgun_token
SHOTGUN_ORGANIZER_ID=your_organizer_id
```

#### 🔑 Where to find your Shotgun credentials?

1. **Shotgun Token**:
   - Log in to your Shotgun dashboard
   - Go to integration > API

2. **Organizer ID**:
   - Visible in your Shotgun dashboard URL
   - Or in the JSON response of API requests

3. **Telegram Token**:
   - Talk to [@BotFather](https://t.me/BotFather)
   - Type `/newbot` and follow instructions
   - Copy the provided token

## 🎯 Usage

### Start the bot

```bash
python3 bot.py
```

The bot starts in polling mode and waits for commands.

### Telegram commands

1. Open Telegram and search for your bot
2. Click **Start** or type `/start`
3. Use the buttons to navigate:
   - **📅 My Events**: List all your active events
   - **🎉 [Event name]**: Show detailed stats
   - **🔙 Back**: Return to previous menu

### Example output

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

## 🛠️ Utility scripts

### Restart the bot cleanly

If you encounter conflicts (error "Conflict: terminated by other getUpdates"), use:

```bash
./restart_bot.sh
```

This script:
1. Kills all bot instances
2. Resets the Telegram webhook
3. Restarts the bot

### Reset webhook manually

```bash
python3 reset_webhook.py
```

## 📁 Project structure

```
shotgunbot/
├── bot.py                 # Main bot code
├── requirements.txt       # Python dependencies
├── .env                   # Configuration (to create)
├── .env.example          # Configuration example
├── reset_webhook.py      # Script to reset Telegram webhook
├── restart_bot.sh        # Clean restart script
└── README.md             # This file
```

## 🔧 Troubleshooting

### Error "Conflict: terminated by other getUpdates"

**Cause**: Multiple bot instances running simultaneously.

**Solution**:
1. Close all terminals
2. Run `./restart_bot.sh`
3. Or restart your computer

### Error "Missing organizer_id"

**Cause**: Token or organizer ID is incorrect.

**Solution**: Check your `.env` file and ensure the values are correct.

### Incorrect prices

**Cause**: Shotgun API returns prices in cents.

**Solution**: The bot automatically divides by 100. If you still see issues, check the latest code version.

## 📡 APIs used

- **Shotgun Events API**: `https://smartboard-api.shotgun.live/api/shotgun/organizers/{id}/events`
  - Lists active events
  
- **Shotgun Tickets API**: `https://api.shotgun.live/tickets`
  - Retrieves sold ticket details

## 📝 Notes

- The bot works in **polling mode** (no webhook)
- Stats are fetched **on demand** (no caching)
- Prices are automatically converted from cents to euros
- Only **published, launched, and non-cancelled** events are displayed

## 🤝 Support

For any questions or issues, verify:
1. Your API keys are valid
2. The Telegram bot is running
3. You only have one bot instance running

## 📄 License

This project is for personal use.

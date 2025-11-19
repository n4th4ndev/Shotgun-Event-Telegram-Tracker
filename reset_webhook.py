import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Delete webhook and drop pending updates
url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
response = requests.get(url)
print(f"Delete webhook response: {response.json()}")

# Get updates with offset=-1 to clear the queue
url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1"
response = requests.get(url)
print(f"Clear updates response: {response.json()}")

print("✅ Webhook cleared and updates queue reset!")

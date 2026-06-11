#!/bin/bash
# Redémarre proprement UNIQUEMENT le bot Shotgun.
# Avant : `pkill -9 -f "python3.*bot.py"` tuait aussi BOTFONT et l'airtable bot
# (tous nommés bot.py). On cible désormais ce bot par son chemin absolu.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT="$DIR/bot.py"

# Tuer uniquement les instances de CE bot
pkill -9 -f "$BOT"

# Laisser le temps au process de se terminer
sleep 2

# Réinitialiser le webhook Telegram
python3 "$DIR/reset_webhook.py"

# Laisser Telegram libérer la connexion de long-poll
sleep 3

# Démarrer le bot avec son chemin absolu (identifiable au prochain restart)
cd "$DIR"
python3 "$BOT"

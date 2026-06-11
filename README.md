<p align="center">
  <a href="https://shotgun.live">
    <img src="https://www.google.com/s2/favicons?domain=shotgun.live&sz=128" alt="Shotgun" width="72" height="72">
  </a>
</p>

<h1 align="center">🤖 Shotgun Bot — Telegram</h1>

<p align="center">
  Bot Telegram <b>non officiel</b> pour suivre en temps réel les ventes de tes événements
  <a href="https://shotgun.live">Shotgun</a> : statistiques par événement, dashboard global,
  historique des anciens événements et notifications automatiques de ventes.
</p>

<p align="center">
  <a href="https://shotgun.live">🌐 Site Shotgun</a> ·
  <a href="https://organizer.shotgun.live">🎛️ Dashboard organisateur</a> ·
  <a href="https://t.me/BotFather">🤖 BotFather</a>
</p>

<p align="center">
  <b>🇫🇷 Français</b> ·
  <a href="README.en.md">🇬🇧 English</a>
</p>

---

## 📋 Fonctionnalités

- 📅 **Événements actifs** : liste tous tes événements publiés, lancés et non annulés
- 📊 **Statistiques détaillées** par événement :
  - Billets vendus, valides, scannés, annulés
  - Chiffre d'affaires total
  - **Détail par type de billet** (nom, quantité vendue, CA)
  - Billets restants
- 📈 **Dashboard global** : vue agrégée sur tous tes événements actifs (ventes, CA, restants)
- 🕘 **Historique** : consulte les anciens événements archivés dans l'état local
- 🔔 **Notifications temps réel** : une tâche de fond surveille les ventes et **envoie un message aux abonnés** dès qu'il y a des ventes ou des scans (`+vendus`, `+CA`, `+scannés`, restants)
- 🩺 **Commande santé** : inspecte l'état du cache, les abonnés, les archives et les TTL
- ⚡ **Couche de cache** : caches à TTL court pour les événements/stats + tâche de préchauffage pour garder l'API réactive
- 🔒 **Contrôle d'accès** : liste blanche optionnelle d'ID de chat Telegram
- 💾 **État persistant** : abonnés, snapshots de ventes et archives stockés dans `bot_state.json`

## 🚀 Installation

### 1. Prérequis

- Python 3.11+
- Un compte Shotgun avec accès organisateur
- Un bot Telegram (créé via [@BotFather](https://t.me/BotFather))

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configuration

Copie `.env.example` vers `.env` et renseigne tes identifiants :

```bash
cp .env.example .env
```

Édite le fichier `.env` :

```env
TELEGRAM_BOT_TOKEN=ton_token_telegram
SHOTGUN_TOKEN=ton_token_shotgun
SHOTGUN_ORGANIZER_ID=ton_id_organisateur
# Optionnel : ID de chat Telegram autorisés, séparés par des virgules.
# Laisser vide pour autoriser tout le monde.
BOTSHOTGUN_ALLOWED_CHAT_IDS=
```

#### 🔑 Où trouver tes identifiants Shotgun ?

1. **Token Shotgun** : connecte-toi à ton [dashboard organisateur](https://organizer.shotgun.live) → intégration > API
2. **ID organisateur** : visible dans l'URL de ton dashboard Shotgun, ou dans la réponse JSON des requêtes API
3. **Token Telegram** : parle à [@BotFather](https://t.me/BotFather), tape `/newbot` et suis les instructions
4. **ID de chat autorisés** (optionnel) : écris au bot, récupère ton chat ID dans les logs, puis ajoute-le à `BOTSHOTGUN_ALLOWED_CHAT_IDS`

## 🎯 Utilisation

### Démarrer le bot

```bash
python3 bot.py
```

Le bot démarre en mode polling, lance la tâche de surveillance des ventes et attend les commandes.

### Commandes Telegram

| Commande | Description |
| --- | --- |
| `/start` | Menu principal avec boutons |
| `/dashboard` | Stats globales agrégées sur tous les événements actifs |
| `/recent` | Liste des anciens événements archivés |
| `/notifications` | Panneau de notifications (statut d'abonnement) |
| `/subscribe` | Recevoir les notifications de ventes en temps réel |
| `/unsubscribe` | Arrêter les notifications |
| `/health` | Diagnostic du bot (cache, abonnés, archives, TTL) |
| `/help` | Message d'aide |

Le menu principal propose les mêmes actions en boutons : **📅 Mes Événements**, **📈 Dashboard**, **🕘 Anciens**, **🔔 Notifications**, **ℹ️ Aide**, plus un bouton **🔄 Actualiser** pour forcer un refresh API.

### Exemple : détail d'un événement

```
🎉 [Nom de l'événement]

📊 Résumé global :
🎟️ Billets totaux : 69
✅ Valides : 62
🔍 Scannés : 0
❌ Annulés : 2
💰 CA total : 985.00 €

🎫 Détail par type de billet :

• [Type de billet 1]
  └ Vendus : 51 | CA : 765.00 €

• [Type de billet 2]
  └ Vendus : 11 | CA : 220.00 €

🎫 Billets restants : 238
```

### Exemple : notification de vente (envoyée automatiquement)

```
🚀 [Nom de l'événement]
Billets vendus : +3
Scannés : +0
CA : +45.00 €
Restants : 235
```

## 🛠️ Scripts utilitaires

### Redémarrer proprement le bot

En cas de conflit (erreur « Conflict: terminated by other getUpdates ») :

```bash
./restart_bot.sh
```

Ce script tue uniquement l'instance de **ce** bot (ciblée par chemin absolu pour ne pas affecter les autres processus `bot.py`), réinitialise le webhook Telegram, puis redémarre.

### Réinitialiser le webhook manuellement

```bash
python3 reset_webhook.py
```

## ⚙️ Référence de configuration

Ces réglages se trouvent en haut de `bot.py` :

| Constante | Défaut | Signification |
| --- | --- | --- |
| `EVENTS_CACHE_TTL` | `30s` | Durée de vie du cache de la liste d'événements |
| `EVENT_STATS_CACHE_TTL` | `15s` | Durée de vie du cache des stats par événement |
| `SALES_POLL_INTERVAL` | `60s` | Intervalle de la surveillance des ventes |
| `RECENT_EVENTS_LIMIT` | `8` | Nombre max d'anciens événements affichés |
| `MAX_HTTP_RETRIES` | `3` | Tentatives de réessai HTTP |
| `MAX_DEAL_LINES` | `12` | Nombre max de lignes de types de billets par événement |

## 📁 Structure du projet

```
BOTSHOTGUN/
├── bot.py                 # Code principal (menus, dashboard, notifications, cache)
├── requirements.txt       # Dépendances Python
├── .env                   # Configuration (à créer, non versionnée)
├── .env.example           # Exemple de configuration
├── bot_state.json         # État runtime : abonnés, snapshots, archives (non versionné)
├── reset_webhook.py       # Réinitialise le webhook Telegram
├── restart_bot.sh         # Script de redémarrage propre
└── README.md              # Ce fichier
```

## 🔧 Dépannage

### Erreur « Conflict: terminated by other getUpdates »
Plusieurs instances du bot tournent. Lance `./restart_bot.sh`.

### Erreur « Missing organizer_id »
Le token ou l'ID organisateur est incorrect. Vérifie ton `.env`.

### « Accès non autorisé »
Ton chat ID n'est pas dans `BOTSHOTGUN_ALLOWED_CHAT_IDS`. Ajoute-le, ou laisse la variable vide pour autoriser tout le monde.

### Prix incorrects
L'API Shotgun renvoie les prix en centimes ; le bot divise automatiquement par 100.

## 📡 APIs utilisées

- **Shotgun Events API** : `https://smartboard-api.shotgun.live/api/shotgun/organizers/{id}/events` — liste les événements
- **Shotgun Tickets API** : `https://api.shotgun.live/tickets` — récupère le détail des billets vendus

## 📝 Notes

- Fonctionne en **mode polling** (pas de webhook)
- Les stats sont mises en cache brièvement (TTL courts) et rafraîchies à la demande ou par la tâche de fond
- Les prix sont automatiquement convertis de centimes en euros
- Seuls les événements **publiés, lancés et non annulés** sont listés comme actifs
- `bot_state.json` est une donnée runtime — ne pas éditer à la main sauf pour réparer un état corrompu

---

## ⚠️ Avertissement / Mentions légales

Ce projet est un outil **personnel et non officiel**. Il **n'est en aucun cas affilié, associé, autorisé, soutenu ni officiellement lié à Shotgun** (Shotgun Live SAS) ou à l'une de ses filiales.

« Shotgun », le logo Shotgun et tous les noms, marques et signes associés sont la **propriété exclusive de leurs détenteurs respectifs** et ne sont utilisés ici qu'à des fins d'identification et de référence. Toutes les marques citées appartiennent à leurs propriétaires respectifs.

Ce bot utilise des API Shotgun avec les identifiants de l'organisateur ; tu es responsable du respect des conditions d'utilisation de Shotgun. Utilisation à tes propres risques, sans aucune garantie.

## 📄 Licence

Projet à usage personnel.

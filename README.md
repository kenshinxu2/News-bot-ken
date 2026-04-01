# 🎌 Kenshin Anime News Bot

Auto-posts anime news, trailers & announcements to your Telegram channel every **2 minutes**.

---

## 📦 Sources

| Source | Type | Interval |
|---|---|---|
| Anime News Network | RSS News + Images | 2 min |
| Crunchyroll News | RSS News + Images | 2 min |
| Anime Corner | RSS News + Images | 2 min |
| MyAnimeList (Jikan API) | News Articles | 2 min |
| YouTube × 5 channels | Trailers + Thumbnails | 2 min |
| AniList | Upcoming Anime Announcements | 6 hrs |

---

## ⚙️ Setup

### 1. Get Credentials

- **API_ID & API_HASH** → https://my.telegram.org
- **BOT_TOKEN** → @BotFather on Telegram
- **ADMIN_IDS** → Your numeric user ID (get from @userinfobot)

### 2. Add Bot as Admin

Add your bot to **@kenshin_anime** channel as **Administrator** with permission to post messages.

### 3. Deploy on Railway

1. Push this folder to a GitHub repo
2. Go to https://railway.app → **New Project** → **Deploy from GitHub**
3. Select your repo
4. Go to **Variables** tab and add:
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   BOT_TOKEN=your_bot_token
   ADMIN_IDS=your_user_id
   ```
5. Deploy starts automatically ✅

### 4. Set Channel

Send to your bot:
```
/setchannel @kenshin_anime
```

Done! Bot will start posting every 2 minutes 🚀

---

## 🤖 Commands (Admin only)

| Command | Description |
|---|---|
| `/setchannel @channel` | Set target channel |
| `/status` | View bot status |
| `/fetchnow` | Force fetch immediately |
| `/clearposted` | Reset duplicate tracker |
| `/help` | Show help menu |

---

## 📁 File Structure

```
kenshin-anime-news-bot/
├── main.py          ← Main bot (all-in-one)
├── requirements.txt
├── Procfile
├── railway.toml
└── .env.example
```

import asyncio
import os
import pickle
import logging
import re

import feedparser
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  ENV VARIABLES
# ─────────────────────────────────────────────────────────────────
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = list(map(int, os.environ.get("ADMIN_IDS", "0").split(",")))

# ─────────────────────────────────────────────────────────────────
#  PERSISTENCE  (pickle files)
# ─────────────────────────────────────────────────────────────────
CHANNEL_FILE = "channel.pkl"
POSTED_FILE  = "posted.pkl"

def _load(path, default):
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return default

def _save(path, data):
    with open(path, "wb") as f:
        pickle.dump(data, f)

target_channel: int | None = _load(CHANNEL_FILE, None)
posted_ids: set             = _load(POSTED_FILE,  set())

# ─────────────────────────────────────────────────────────────────
#  PYROGRAM CLIENT
# ─────────────────────────────────────────────────────────────────
bot = Client(
    "kenshin_news_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# ─────────────────────────────────────────────────────────────────
#  SOURCES CONFIG
# ─────────────────────────────────────────────────────────────────
RSS_SOURCES = [
    {
        "name"  : "Anime News Network",
        "url"   : "https://www.animenewsnetwork.com/all/rss.xml?ann-edition=us",
        "emoji" : "📰",
        "tag"   : "ANN",
    },
    {
        "name"  : "Crunchyroll News",
        "url"   : "https://www.crunchyroll.com/newsrss?lang=enUS",
        "emoji" : "🍥",
        "tag"   : "Crunchyroll",
    },
    {
        "name"  : "Anime Corner",
        "url"   : "https://animecorner.me/feed/",
        "emoji" : "🎌",
        "tag"   : "AnimeCorner",
    },
]

YOUTUBE_CHANNELS = [
    {"name": "Crunchyroll",    "id": "UCVTQuK2CaWaTgSsoNkn5AiQ"},
    {"name": "AniplexUSA",     "id": "UCkDiDoALEm01MlpkBmTcz9Q"},
    {"name": "Funimation",     "id": "UCWiy83SIvWRQmtEFYY1OkBw"},
    {"name": "Muse Asia",      "id": "UCsF5LOVDzSJ8Ew7KPNK3HOw"},
    {"name": "TOHO Animation", "id": "UCX9hV7JCVLqFiZ2BqmO0j7Q"},
]

# Keywords to filter YouTube videos (only anime-related)
YT_KEYWORDS = [
    "trailer", "pv", "preview", "official", "season", "episode",
    "anime", "mv", "opening", "ending", "announcement", "teaser",
]

# ─────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────
def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def yt_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

def yt_thumbnail(video_id: str) -> str:
    return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

def extract_video_id(link: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", link)
    return m.group(1) if m else None

def mark_posted(uid: str):
    posted_ids.add(uid)
    _save(POSTED_FILE, posted_ids)

# ─────────────────────────────────────────────────────────────────
#  SEND HELPERS
# ─────────────────────────────────────────────────────────────────
async def send_with_photo(chat_id: int, photo: str, caption: str, buttons) -> bool:
    """Try sending with photo; fall back to text-only on failure."""
    try:
        await bot.send_photo(
            chat_id,
            photo=photo,
            caption=caption,
            reply_markup=buttons,
            parse_mode="html",
        )
        return True
    except Exception as e:
        log.warning(f"Photo send failed ({e}), trying text-only…")

    try:
        await bot.send_message(
            chat_id,
            caption,
            reply_markup=buttons,
            disable_web_page_preview=False,
            parse_mode="html",
        )
        return True
    except Exception as e:
        log.error(f"Text send also failed: {e}")
        return False

async def send_text_only(chat_id: int, text: str, buttons) -> bool:
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_markup=buttons,
            disable_web_page_preview=False,
            parse_mode="html",
        )
        return True
    except Exception as e:
        log.error(f"send_text_only failed: {e}")
        return False

# ─────────────────────────────────────────────────────────────────
#  FETCHERS
# ─────────────────────────────────────────────────────────────────

# ── 1. RSS News ─────────────────────────────────────────────────
async def fetch_rss_news() -> int:
    if not target_channel:
        return 0
    total = 0

    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            # Process oldest-first so channel is in chronological order
            entries = list(reversed(feed.entries[:10]))

            for entry in entries:
                uid = entry.get("id") or entry.get("link", "")
                if not uid or uid in posted_ids:
                    continue

                title   = entry.get("title", "Anime News").strip()
                link    = entry.get("link", "").strip()
                summary = strip_html(entry.get("summary", entry.get("description", "")))
                if len(summary) > 400:
                    summary = summary[:400].rstrip() + "…"

                # Try to find image
                img_url = None
                for attr in ("media_thumbnail", "media_content"):
                    val = getattr(entry, attr, None)
                    if val and isinstance(val, list):
                        img_url = val[0].get("url")
                        break
                if not img_url:
                    for enc in entry.get("enclosures", []):
                        if "image" in enc.get("type", ""):
                            img_url = enc.get("href")
                            break

                caption = (
                    f"{src['emoji']} <b>{src['name']}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🎌 <b>{title}</b>\n\n"
                    f"{summary}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>🔔 Stay updated with KenshinAnime!</i>\n"
                    f"#AnimeNews #{src['tag']} #KenshinAnime"
                )
                btn = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🌐 Read Full Article", url=link)
                ]])

                sent = False
                if img_url:
                    sent = await send_with_photo(target_channel, img_url, caption, btn)
                else:
                    sent = await send_text_only(target_channel, caption, btn)

                if sent:
                    mark_posted(uid)
                    total += 1
                    log.info(f"[RSS] Posted: {title[:60]}")
                    await asyncio.sleep(4)

        except Exception as e:
            log.error(f"[RSS] Error in {src['name']}: {e}")

    return total


# ── 2. YouTube Trailers ──────────────────────────────────────────
async def fetch_yt_trailers() -> int:
    if not target_channel:
        return 0
    total = 0

    for ch in YOUTUBE_CHANNELS:
        try:
            feed = feedparser.parse(yt_feed_url(ch["id"]))
            entries = list(reversed(feed.entries[:8]))

            for entry in entries:
                vid_id = getattr(entry, "yt_videoid", None) or extract_video_id(
                    entry.get("link", "")
                )
                if not vid_id:
                    continue

                uid = f"yt_{vid_id}"
                if uid in posted_ids:
                    continue

                title = entry.get("title", "").strip()
                link  = entry.get("link", "").strip()

                # Filter: only anime-related videos
                if not any(kw in title.lower() for kw in YT_KEYWORDS):
                    continue

                thumb   = yt_thumbnail(vid_id)
                caption = (
                    f"🎬 <b>New Video Drop!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📺 <b>Channel:</b> {ch['name']}\n"
                    f"🎌 <b>{title}</b>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>🔔 Latest from KenshinAnime!</i>\n"
                    f"#AnimeTrailer #Anime #KenshinAnime"
                )
                btn = InlineKeyboardMarkup([[
                    InlineKeyboardButton("▶️ Watch on YouTube", url=link)
                ]])

                sent = await send_with_photo(target_channel, thumb, caption, btn)
                if sent:
                    mark_posted(uid)
                    total += 1
                    log.info(f"[YT] Posted: {title[:60]}")
                    await asyncio.sleep(4)

        except Exception as e:
            log.error(f"[YT] Error in {ch['name']}: {e}")

    return total


# ── 3. MAL / Jikan News ─────────────────────────────────────────
async def fetch_jikan_news() -> int:
    if not target_channel:
        return 0
    total = 0
    url   = "https://api.jikan.moe/v4/news/anime"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    log.warning(f"[Jikan] HTTP {r.status}")
                    return 0
                data = await r.json()

        items = (data.get("data") or [])[:8]
        items = list(reversed(items))  # oldest first

        for item in items:
            mal_id = item.get("mal_id", "")
            link   = item.get("url", "")
            uid    = f"jikan_{mal_id or link}"

            if uid in posted_ids:
                continue

            title   = item.get("title", "Anime News").strip()
            excerpt = strip_html(item.get("excerpt", ""))
            if len(excerpt) > 400:
                excerpt = excerpt[:400].rstrip() + "…"
            author  = item.get("author_username", "MAL Staff")
            img     = item.get("images", {}).get("jpg", {}).get("image_url")

            caption = (
                f"📰 <b>MyAnimeList News</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎌 <b>{title}</b>\n\n"
                f"{excerpt}\n\n"
                f"✍️ <i>By {author}</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"#AnimeNews #MAL #KenshinAnime"
            )
            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔗 Read on MAL", url=link)
            ]])

            sent = False
            if img:
                sent = await send_with_photo(target_channel, img, caption, btn)
            else:
                sent = await send_text_only(target_channel, caption, btn)

            if sent:
                mark_posted(uid)
                total += 1
                log.info(f"[Jikan] Posted: {title[:60]}")
                await asyncio.sleep(4)

    except Exception as e:
        log.error(f"[Jikan] Error: {e}")

    return total


# ── 4. AniList Announcements ─────────────────────────────────────
async def fetch_anilist_announcements() -> int:
    if not target_channel:
        return 0
    total = 0
    query = """
    query {
      Page(page: 1, perPage: 8) {
        media(type: ANIME, status: NOT_YET_RELEASED, sort: POPULARITY_DESC) {
          id
          title { romaji english }
          description(asHtml: false)
          coverImage { large }
          startDate { year month day }
          episodes
          genres
          siteUrl
          studios(isMain: true) { nodes { name } }
        }
      }
    }
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://graphql.anilist.co",
                json={"query": query},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as r:
                if r.status != 200:
                    log.warning(f"[AniList] HTTP {r.status}")
                    return 0
                data = await r.json()

        media_list = data.get("data", {}).get("Page", {}).get("media", [])

        for anime in media_list:
            uid = f"anilist_{anime['id']}"
            if uid in posted_ids:
                continue

            title   = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
            desc    = strip_html(anime.get("description") or "")
            if len(desc) > 350:
                desc = desc[:350].rstrip() + "…"
            cover   = anime.get("coverImage", {}).get("large")
            site    = anime.get("siteUrl", "")
            genres  = " • ".join((anime.get("genres") or [])[:4])
            eps     = anime.get("episodes") or "TBA"
            sd      = anime.get("startDate") or {}
            yr      = sd.get("year", "?")
            mo      = str(sd.get("month", "?")).zfill(2)
            dy      = str(sd.get("day",   "?")).zfill(2)
            airing  = f"{dy}/{mo}/{yr}"
            studios = ", ".join(
                n["name"] for n in (anime.get("studios", {}).get("nodes") or [])[:2]
            ) or "Unknown Studio"

            caption = (
                f"📢 <b>Upcoming Anime Announcement!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎌 <b>{title}</b>\n\n"
                f"{desc if desc else '❓ No description available yet.'}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>Airing Date:</b> {airing}\n"
                f"📺 <b>Episodes:</b> {eps}\n"
                f"🎭 <b>Genres:</b> {genres}\n"
                f"🏢 <b>Studio:</b> {studios}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"#UpcomingAnime #AnimeAnnouncement #KenshinAnime"
            )
            btn = InlineKeyboardMarkup([[
                InlineKeyboardButton("📖 View on AniList", url=site)
            ]])

            sent = False
            if cover:
                sent = await send_with_photo(target_channel, cover, caption, btn)
            else:
                sent = await send_text_only(target_channel, caption, btn)

            if sent:
                mark_posted(uid)
                total += 1
                log.info(f"[AniList] Posted: {title[:60]}")
                await asyncio.sleep(4)

    except Exception as e:
        log.error(f"[AniList] Error: {e}")

    return total

# ─────────────────────────────────────────────────────────────────
#  MASTER FETCH JOB  (runs every 2 min)
# ─────────────────────────────────────────────────────────────────
async def job_all_news():
    log.info("━━ 2-min news cycle started ━━")
    r = await fetch_rss_news()
    j = await fetch_jikan_news()
    y = await fetch_yt_trailers()
    log.info(f"━━ Cycle done | RSS={r}  Jikan={j}  YT={y} ━━")

async def job_announcements():
    log.info("━━ AniList announcements job started ━━")
    a = await fetch_anilist_announcements()
    log.info(f"━━ AniList done | Posted={a} ━━")

# ─────────────────────────────────────────────────────────────────
#  BOT COMMANDS
# ─────────────────────────────────────────────────────────────────
@bot.on_message(filters.command(["start", "help"]))
async def cmd_start(_, m: Message):
    text = (
        "🤖 <b>Kenshin Anime News Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Auto-posts anime news, trailers & announcements every <b>2 minutes</b>!\n\n"
        "<b>📋 Commands (Admin only):</b>\n\n"
        "🔹 /setchannel <code>@channel</code> — Set target channel\n"
        "🔹 /status — View bot status\n"
        "🔹 /fetchnow — Force fetch right now\n"
        "🔹 /clearposted — Reset duplicate tracker\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Made with ❤️ for @kenshin_anime</i>"
    )
    await m.reply_text(text, parse_mode="html")


@bot.on_message(filters.command("setchannel") & filters.user(ADMIN_IDS))
async def cmd_set_channel(_, m: Message):
    global target_channel
    if len(m.command) < 2:
        return await m.reply_text("❌ <b>Usage:</b> <code>/setchannel @channelname</code>", parse_mode="html")
    try:
        chat = await bot.get_chat(m.command[1])
        target_channel = chat.id
        _save(CHANNEL_FILE, target_channel)
        await m.reply_text(
            f"✅ <b>Channel set successfully!</b>\n\n"
            f"📺 <b>Name:</b> {chat.title}\n"
            f"🆔 <b>ID:</b> <code>{chat.id}</code>\n\n"
            f"<i>Bot will now post news every 2 minutes.</i>",
            parse_mode="html",
        )
        log.info(f"Channel set to: {chat.title} ({chat.id})")
    except Exception as e:
        await m.reply_text(f"❌ <b>Error:</b> <code>{e}</code>", parse_mode="html")


@bot.on_message(filters.command("status") & filters.user(ADMIN_IDS))
async def cmd_status(_, m: Message):
    ch_info = "❌ Not set"
    if target_channel:
        try:
            chat    = await bot.get_chat(target_channel)
            ch_info = f"<b>{chat.title}</b> (<code>{chat.id}</code>)"
        except Exception:
            ch_info = f"<code>{target_channel}</code>"

    await m.reply_text(
        f"📊 <b>Bot Status</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📺 <b>Channel:</b> {ch_info}\n"
        f"📦 <b>Tracked posts:</b> <code>{len(posted_ids)}</code>\n"
        f"⏰ <b>News check:</b> Every 2 minutes\n"
        f"📢 <b>Announcements:</b> Every 6 hours\n"
        f"✅ <b>Scheduler:</b> Running\n\n"
        f"<b>Sources:</b>\n"
        f"• Anime News Network (RSS)\n"
        f"• Crunchyroll News (RSS)\n"
        f"• Anime Corner (RSS)\n"
        f"• MAL / Jikan API\n"
        f"• YouTube (5 channels)\n"
        f"• AniList (announcements)\n"
        f"━━━━━━━━━━━━━━━━━━━━",
        parse_mode="html",
    )


@bot.on_message(filters.command("fetchnow") & filters.user(ADMIN_IDS))
async def cmd_fetch_now(_, m: Message):
    if not target_channel:
        return await m.reply_text("❌ Set channel first with <code>/setchannel @channel</code>", parse_mode="html")
    msg = await m.reply_text("⏳ <b>Fetching from all sources…</b>", parse_mode="html")
    r = await fetch_rss_news()
    j = await fetch_jikan_news()
    y = await fetch_yt_trailers()
    a = await fetch_anilist_announcements()
    await msg.edit_text(
        f"✅ <b>Fetch Complete!</b>\n\n"
        f"📰 RSS News: <code>{r}</code>\n"
        f"📰 MAL News: <code>{j}</code>\n"
        f"🎬 Trailers: <code>{y}</code>\n"
        f"📢 Announcements: <code>{a}</code>",
        parse_mode="html",
    )


@bot.on_message(filters.command("clearposted") & filters.user(ADMIN_IDS))
async def cmd_clear(_, m: Message):
    global posted_ids
    old = len(posted_ids)
    posted_ids = set()
    _save(POSTED_FILE, posted_ids)
    await m.reply_text(
        f"✅ <b>Cleared!</b> Removed <code>{old}</code> tracked post IDs.\n"
        f"<i>Bot will re-fetch all news on next cycle.</i>",
        parse_mode="html",
    )

# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────
async def main():
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    # Every 2 minutes — news + trailers
    scheduler.add_job(job_all_news,       "interval", minutes=2,  id="all_news")
    # Every 6 hours — AniList upcoming announcements
    scheduler.add_job(job_announcements,  "interval", hours=6,    id="announcements")

    scheduler.start()
    log.info("✅ Scheduler started — news every 2 min, announcements every 6 hrs")

    await bot.start()
    log.info("🤖 Kenshin Anime News Bot is LIVE!")

    # Initial fetch on startup (after 10s to let bot settle)
    await asyncio.sleep(10)
    log.info("🚀 Running initial fetch on startup…")
    await job_all_news()
    await job_announcements()

    # Keep bot running
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

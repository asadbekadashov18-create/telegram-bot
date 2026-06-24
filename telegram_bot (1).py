import logging
import tempfile
import os
import sqlite3
import yt_dlp
import speech_recognition as sr
from pydub import AudioSegment
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8983669857:AAHNCAHQ2tWAX62whe4SdQs8w2MZD0zcioQ"
ADMIN_ID = 8037874843  # Sizning Telegram ID ingiz — /myid buyrug'i bilan bilib olasiz

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

user_requests = {}
search_results_cache = {}

# =====================
# DATABASE
# =====================

def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_date TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id, username, full_name):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name, joined_date)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, full_name, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    today = c.execute(
        "SELECT COUNT(*) FROM users WHERE joined_date = ?",
        (datetime.now().strftime("%Y-%m-%d"),)
    ).fetchone()[0]
    conn.close()
    return total, today

# =====================
# HELPER FUNCTIONS
# =====================

def is_valid_url(text):
    return text.startswith("http://") or text.startswith("https://")

def detect_platform(url):
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    elif "tiktok.com" in url:
        return "TikTok"
    elif "instagram.com" in url:
        return "Instagram"
    elif "pinterest.com" in url or "pin.it" in url:
        return "Pinterest"
    elif "spotify.com" in url:
        return "Spotify"
    elif "soundcloud.com" in url:
        return "SoundCloud"
    elif "facebook.com" in url or "fb.watch" in url:
        return "Facebook"
    elif "twitter.com" in url or "x.com" in url:
        return "Twitter/X"
    else:
        return "Boshqa"

def search_songs(query, count=15):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
            results = []
            for entry in info.get("entries", []):
                title = entry.get("title", "Noma'lum")
                url = f"https://www.youtube.com/watch?v={entry.get('id', '')}"
                duration = entry.get("duration", 0) or 0
                try:
                    duration = int(float(duration))
                except:
                    duration = 0
                mins = duration // 60
                secs = duration % 60
                results.append({
                    "title": title,
                    "url": url,
                    "duration": f"{mins}:{secs:02d}" if duration else "?"
                })
            return results
    except Exception as e:
        logger.error(f"Qidiruv xatosi: {e}")
        return []

def download_audio(url):
    tmp_dir = tempfile.mkdtemp()
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Musiqa")
            files = []
            for root, dirs, filenames in os.walk(tmp_dir):
                for filename in filenames:
                    files.append(os.path.join(root, filename))
            return files[0] if files else None, title
    except Exception as e:
        logger.error(f"Audio yuklab olish xatosi: {e}")
        return None, None

def download_pinterest(url):
    import requests
    import re
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        session = requests.Session()
        if "pin.it" in url:
            resp = session.get(url, headers=headers, allow_redirects=True, timeout=10)
            url = resp.url
        resp = session.get(url, headers=headers, timeout=10)
        html = resp.text
        patterns = [
            r'"orig":\{"url":"([^"]+)"',
            r'"736x":\{"url":"([^"]+)"',
            r'"564x":\{"url":"([^"]+)"',
            r'<meta property="og:image" content="([^"]+)"',
        ]
        img_url = None
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                img_url = match.group(1).replace("\\u002F", "/").replace("\\/", "/")
                break
        if not img_url:
            return None, None
        img_resp = session.get(img_url, headers=headers, timeout=15)
        tmp_dir = tempfile.mkdtemp()
        ext = "png" if "png" in img_url else "jpg"
        filepath = os.path.join(tmp_dir, f"pinterest.{ext}")
        with open(filepath, "wb") as f:
            f.write(img_resp.content)
        return filepath, "Pinterest rasmi"
    except Exception as e:
        logger.error(f"Pinterest xato: {e}")
        return None, None

def download_media(url, audio_only=False):
    tmp_dir = tempfile.mkdtemp()
    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
        }
    else:
        ydl_opts = {
            "format": "best[filesize<50M]/best",
            "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "media")
            files = []
            for root, dirs, filenames in os.walk(tmp_dir):
                for filename in filenames:
                    files.append(os.path.join(root, filename))
            return files[0] if files else None, title
    except Exception as e:
        logger.error(f"Yuklab olish xatosi: {e}")
        return None, None

def voice_to_text(ogg_path):
    try:
        tmp_dir = tempfile.mkdtemp()
        wav_path = os.path.join(tmp_dir, "voice.wav")
        audio = AudioSegment.from_ogg(ogg_path)
        audio.export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
            try:
                return recognizer.recognize_google(audio_data, language="uz-UZ")
            except:
                return recognizer.recognize_google(audio_data, language="ru-RU")
    except Exception as e:
        logger.error(f"Ovoz xatosi: {e}")
        return None

# =====================
# HANDLERS
# =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username or "", user.full_name or "")
    await update.message.reply_text(
        "Salom! 👋 Men Universal Yuklovchi Botman!\n\n"
        "Quyidagilarni yuboring:\n\n"
        "🔗 YouTube, TikTok, Instagram, Pinterest linki\n"
        "🎵 Musiqa nomi — 'Ummon' yoki 'Harry Styles'\n"
        "🎙 Ovozli xabar — qo'shiq nomini ayting\n\n"
        "Shunchaki yuboring — men yuklab beraman! 🚀"
    )

async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi o'z ID sini bilishi uchun"""
    await update.message.reply_text(f"🆔 Sizning ID ingiz: `{update.effective_user.id}`", parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistika — faqat admin uchun"""
    user_id = update.effective_user.id
    
    # Admin ID ni tekshirish
    if ADMIN_ID and user_id != ADMIN_ID:
        await update.message.reply_text("❌ Bu buyruq faqat admin uchun!")
        return
    
    total, today = get_stats()
    await update.message.reply_text(
        f"📊 *Bot statistikasi:*\n\n"
        f"👥 Jami foydalanuvchilar: *{total}*\n"
        f"📅 Bugun qo'shilganlar: *{today}*",
        parse_mode="Markdown"
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username or "", user.full_name or "")
    user_id = user.id
    loading_msg = await update.message.reply_text("🎙 Ovoz tanilmoqda...")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        tmp_dir = tempfile.mkdtemp()
        ogg_path = os.path.join(tmp_dir, "voice.ogg")
        await file.download_to_drive(ogg_path)
        text = voice_to_text(ogg_path)
        if text:
            results = search_songs(text, 15)
            if results:
                search_results_cache[user_id] = results
                keyboard = []
                for i, song in enumerate(results):
                    keyboard.append([InlineKeyboardButton(
                        f"🎵 {song['title'][:45]} ({song['duration']})",
                        callback_data=f"song_{i}"
                    )])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await loading_msg.edit_text(
                    f"🎙 '{text}' uchun natijalar:",
                    reply_markup=reply_markup
                )
            else:
                await loading_msg.edit_text("❌ Hech narsa topilmadi.")
        else:
            await loading_msg.edit_text("❌ Ovozni tushunmadim.")
    except Exception as e:
        logger.error(f"Ovoz xatosi: {e}")
        await loading_msg.edit_text("❌ Xato yuz berdi.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username or "", user.full_name or "")
    text = update.message.text.strip()
    user_id = user.id

    if is_valid_url(text):
        platform = detect_platform(text)
        user_requests[user_id] = {"type": "url", "data": text, "platform": platform}

        if platform == "Pinterest":
            keyboard = [[InlineKeyboardButton("🖼 Rasm yukla", callback_data="photo")]]
        elif platform in ["SoundCloud", "Spotify"]:
            keyboard = [[InlineKeyboardButton("🎵 Musiqa yukla", callback_data="audio")]]
        else:
            keyboard = [[
                InlineKeyboardButton("🎬 Video yukla", callback_data="video"),
                InlineKeyboardButton("🎵 Musiqa yukla", callback_data="audio"),
            ]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ {platform} linki aniqlandi!\n\nNimani yuklab beray?",
            reply_markup=reply_markup
        )
    else:
        loading_msg = await update.message.reply_text(f"🔍 '{text}' qidirilmoqda...")
        results = search_songs(text, 15)
        if results:
            search_results_cache[user_id] = results
            keyboard = []
            for i, song in enumerate(results):
                keyboard.append([InlineKeyboardButton(
                    f"🎵 {song['title'][:45]} ({song['duration']})",
                    callback_data=f"song_{i}"
                )])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await loading_msg.edit_text(
                f"🎵 '{text}' uchun {len(results)} ta natija:",
                reply_markup=reply_markup
            )
        else:
            await loading_msg.edit_text("❌ Hech narsa topilmadi.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data.startswith("song_"):
        idx = int(query.data.split("_")[1])
        results = search_results_cache.get(user_id, [])
        if not results or idx >= len(results):
            await query.edit_message_text("❌ Qaytadan qidiring.")
            return
        song = results[idx]
        await query.edit_message_text(f"⏳ '{song['title']}' yuklanmoqda...")
        filepath, title = download_audio(song["url"])
        if filepath and os.path.exists(filepath):
            await query.edit_message_text("📤 Musiqa yuborilmoqda...")
            with open(filepath, "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title=title,
                    caption=f"✅ {title} 🎵"
                )
            await query.delete_message()
            os.remove(filepath)
        else:
            await query.edit_message_text("❌ Yuklab bo'lmadi.")
        return

    request = user_requests.get(user_id)
    if not request:
        await query.edit_message_text("❌ Qaytadan yuboring.")
        return

    url = request["data"]
    action = query.data
    await query.edit_message_text("⏳ Yuklanmoqda...")

    if action == "photo":
        filepath, title = download_pinterest(url)
        if filepath and os.path.exists(filepath):
            await query.edit_message_text("📤 Rasm yuborilmoqda...")
            with open(filepath, "rb") as f:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=f,
                    caption="✅ Mana rasmingiz! 🖼"
                )
            await query.delete_message()
            os.remove(filepath)
        else:
            await query.edit_message_text("❌ Pinterest rasmini yuklab bo'lmadi.")
        return

    audio_only = action == "audio"
    filepath, title = download_media(url, audio_only=audio_only)

    if not filepath or not os.path.exists(filepath):
        await query.edit_message_text("❌ Yuklab bo'lmadi.")
        return

    try:
        if audio_only:
            await query.edit_message_text("📤 Musiqa yuborilmoqda...")
            with open(filepath, "rb") as f:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f,
                    title=title or "Musiqa",
                    caption="✅ Mana musiqangiz! 🎵"
                )
        else:
            await query.edit_message_text("📤 Video yuborilmoqda...")
            with open(filepath, "rb") as f:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=f,
                    caption=f"✅ {title or 'Video'} 🎬",
                    supports_streaming=True
                )
        await query.delete_message()
    except Exception as e:
        logger.error(f"Yuborish xatosi: {e}")
        await query.edit_message_text("❌ Fayl juda katta.")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Xato: {context.error}", exc_info=context.error)

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)
    print("✅ Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()

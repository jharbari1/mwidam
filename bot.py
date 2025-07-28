import logging
import requests
import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

# === CONFIG ===
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Set this in Render Environment
API_URL = "https://api.v02.savethevideo.com/tasks"

# Validate token
if not BOT_TOKEN:
    logging.error("BOT_TOKEN environment variable not set!")
    exit(1)

# === LOGGER ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Start command ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Send me any video link (YouTube, Facebook, etc.) and I'll show you available resolutions to download."
    )

# === Handle incoming video URLs ===
def handle_message(update: Update, context: CallbackContext):
    url = update.message.text.strip()
    chat_id = update.message.chat_id
    message = update.message.reply_text("🔍 Processing video...")

    try:
        task = requests.post(API_URL, json={"type": "info", "url": url})
        if task.status_code != 200:
            message.edit_text("❌ Failed to process video. Invalid URL or service error.")
            return

        data = task.json()
        task_href = data.get("href")
        if not task_href:
            message.edit_text("❌ Couldn't get video information. Unsupported platform?")
            return

        # Poll until completed or timeout
        for _ in range(30):  # 30 attempts (60s)
            result = requests.get("https://api.v02.savethevideo.com" + task_href)
            if result.status_code != 200:
                message.edit_text("❌ Error checking video status.")
                return

            status = result.json()
            if status.get("state") == "completed":
                break
            elif status.get("state") == "failed":
                message.edit_text(f"❌ Failed: {status.get('error', {}).get('message', 'Unknown error')}")
                return
            time.sleep(2)
        else:
            message.edit_text("❌ Video processing timed out.")
            return

        result_data = status.get("result", [])
        if not result_data:
            message.edit_text("❌ No downloadable formats found.")
            return

        formats = result_data[0].get("formats", [])
        buttons = []
        context.user_data["video_formats"] = []

        for i, fmt in enumerate(formats):
            if fmt.get("ext") != "mp4" or fmt.get("vcodec") == "none":
                continue
            resolution = fmt.get("resolution") or f"{fmt.get('height', '?')}p"
            has_audio = fmt.get("acodec") != "none"
            label = f"{resolution} {'🔊' if has_audio else '🔇'}"
            context.user_data["video_formats"].append(fmt)
            buttons.append([InlineKeyboardButton(label, callback_data=str(i))])

        if not buttons:
            message.edit_text("❌ No supported video formats.")
            return

        message.edit_text("✅ Choose a resolution:", reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        logger.error(f"Error: {e}")
        message.edit_text("❌ Internal error. Try again later.")

# === Handle resolution button press ===
def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    try:
        index = int(query.data)
        formats = context.user_data.get("video_formats", [])
        if index >= len(formats):
            query.edit_message_text("❌ Invalid format selection.")
            return

        fmt = formats[index]
        video_url = fmt.get("url")
        resolution = fmt.get("resolution", "video")
        filename = f"video_{resolution}_{int(time.time())}.mp4"

        query.edit_message_text(f"⬇️ Downloading {resolution}...")

        with requests.get(video_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        query.edit_message_text(f"📤 Uploading {resolution}...")
        with open(filename, "rb") as video:
            context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video,
                caption=f"🎬 {resolution} video",
                timeout=120
            )

        query.edit_message_text(f"✅ Done! Your {resolution} video is ready.")

    except Exception as e:
        logger.error(f"Button handler error: {e}")
        query.edit_message_text("❌ Download or upload failed.")
    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass

# === Main bot startup ===
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(handle_button))

    logger.info("Bot started polling...")
    updater.start_polling()
    updater.idle()

# === Entry point ===
if __name__ == '__main__':
    main()

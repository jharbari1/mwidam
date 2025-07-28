import logging
import requests
import os
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters, CallbackQueryHandler

# === CONFIG ===
BOT_TOKEN = os.environ.get("8134907822:AAE-Z28AdGc16Kb74DH1KDx92tpd3aWWz74")  # From Render environment variables
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
    update.message.reply_text("👋 Send me any video link (YouTube, Facebook, etc.) and I'll show you available resolutions to download.")

# === Handle incoming video URLs ===
def handle_message(update: Update, context: CallbackContext):
    url = update.message.text.strip()
    chat_id = update.message.chat_id
    message = update.message.reply_text("🔍 Processing video...")
    
    try:
        # Get video info
        task = requests.post(API_URL, json={"type": "info", "url": url})
        if task.status_code != 200:
            message.edit_text("❌ Failed to process video. Invalid URL or service error.")
            return

        data = task.json()
        task_href = data.get("href")
        if not task_href:
            message.edit_text("❌ Couldn't get video information. Unsupported platform?")
            return

        # Poll for completion
        attempts = 0
        while attempts < 30:  # Max 60 seconds (30 attempts * 2s)
            result = requests.get("https://api.v02.savethevideo.com" + task_href)
            if result.status_code != 200:
                message.edit_text("❌ Error while checking video status.")
                return
            
            status = result.json()
            state = status.get("state")
            
            if state == "completed":
                break
            elif state == "failed":
                error_msg = status.get("error", {}).get("message", "Unknown error")
                message.edit_text(f"❌ Video processing failed: {error_msg}")
                return
            elif state == "pending":
                time.sleep(2)
                attempts += 1
        else:
            message.edit_text("❌ Video processing timed out. Try again later.")
            return

        # Get available formats
        result_data = status.get("result", [])
        if not result_data:
            message.edit_text("❌ No downloadable formats found.")
            return

        formats = result_data[0].get("formats", [])
        buttons = []
        context.user_data["video_formats"] = []

        for i, fmt in enumerate(formats):
            # Skip non-video formats and audio-only
            if fmt.get("ext") != "mp4" or fmt.get("vcodec") == "none":
                continue
                
            # Create format label
            resolution = fmt.get("resolution") or f"{fmt.get('height', '?')}p"
            has_audio = fmt.get("acodec") != "none"
            label = f"{resolution} {'🔊' if has_audio else '🔇'}"
            
            # Store format and create button
            context.user_data["video_formats"].append(fmt)
            buttons.append([InlineKeyboardButton(label, callback_data=str(i))])

        if not buttons:
            message.edit_text("❌ No supported video formats found.")
            return

        message.edit_text("✅ Choose a resolution to download:", reply_markup=InlineKeyboardMarkup(buttons))
        
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        message.edit_text("❌ Internal error occurred. Please try again later.")

# === Handle resolution button press ===
def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    try:
        index = int(query.data)
        formats = context.user_data.get("video_formats", [])
        
        if index >= len(formats):
            query.edit_message_text("❌ Invalid selection. Please start over.")
            return

        fmt = formats[index]
        video_url = fmt.get("url")
        resolution = fmt.get("resolution", "video")
        filename = f"video_{resolution}_{int(time.time())}.mp4"

        # Download video
        query.edit_message_text(f"⬇️ Downloading {resolution}...")
        
        with requests.get(video_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Upload to Telegram
        query.edit_message_text(f"📤 Uploading {resolution}...")
        with open(filename, "rb") as video:
            context.bot.send_video(
                chat_id=query.message.chat_id,
                video=video,
                caption=f"🎬 {resolution} video",
                timeout=120
            )
        
        # Cleanup
        os.remove(filename)
        query.edit_message_text(f"✅ Download complete! Enjoy your {resolution} video.")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Download failed: {str(e)}")
        query.edit_message_text("❌ Download failed. Network error occurred.")
    except Exception as e:
        logger.error(f"Error handling button: {str(e)}")
        query.edit_message_text("❌ Internal error occurred. Please try again.")
    finally:
        # Cleanup if file exists
        if os.path.exists(filename):
            os.remove(filename)

# === Main setup ===
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(handle_button))

    logger.info("Bot started polling...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
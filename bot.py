import os
import json
import re
import logging
from time import sleep
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

# --- Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Constants ---
SESSION_FILE = "session.json"
PROCESSED_FILE = "processed_messages.json"
REEL_REGEX = re.compile(r"https?://www\.instagram\.com/reel/[A-Za-z0-9_\-]+/?")

# --- Utils ---
def save_json(data, filename):
    with open(filename, "w") as f:
        json.dump(data, f)

def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return []

def human_delay():
    sleep(3)

# --- Bot Class ---
class InstagramRepostBot:
    def __init__(self):
        self.cl = Client()
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")
        self.processed = set(load_json(PROCESSED_FILE))

    def login(self):
        if os.path.exists(SESSION_FILE):
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(self.username, self.password)
                logger.info("✅ Session restored.")
                return
            except Exception as e:
                logger.warning(f"⚠️ Failed to load session: {e}")

        logger.info("🔐 Logging in fresh.")
        self.cl.login(self.username, self.password)
        self.cl.dump_settings(SESSION_FILE)

    def process_dms(self):
        threads = self.cl.direct_threads()
        reposts = 0

        for thread in threads:
            for msg in thread.messages:
                msg_id = str(msg.id)
                if msg_id in self.processed:
                    continue

                text = msg.text or ""

                # Case 1: Reel URL in text
                m = REEL_REGEX.search(text)
                if m:
                    url = m.group(0)
                    logger.info(f"🎯 Reposting reel URL: {url}")
                    try:
                        self.cl.clip_upload_by_url(url, caption="")
                        self.processed.add(msg_id)
                        reposts += 1
                        human_delay()
                    except Exception as e:
                        logger.warning(f"❌ Failed to repost reel from URL: {e}")
                    continue

                # Case 2: Forwarded reel (media_share)
                if hasattr(msg, "media_share") and msg.media_share:
                    media = msg.media_share
                    if getattr(media, "video_url", None):
                        logger.info(f"↪️ Reposting forwarded reel: {media.video_url}")
                        try:
                            self.cl.clip_upload_by_url(media.video_url, caption="")
                            self.processed.add(msg_id)
                            reposts += 1
                            human_delay()
                        except Exception as e:
                            logger.warning(f"❌ Failed to repost forwarded reel: {e}")
                        continue

                    # Case 3: Image with optional caption
                    if getattr(media, "thumbnail_url", None):
                        logger.info(f"🖼️ Reposting image post")
                        try:
                            self.cl.photo_upload_by_url(media.thumbnail_url, caption=text)
                            self.processed.add(msg_id)
                            reposts += 1
                            human_delay()
                        except Exception as e:
                            logger.warning(f"❌ Failed to repost image: {e}")
                        continue

        logger.info(f"✅ Run complete. Total reposts: {reposts}")
        save_json(list(self.processed), PROCESSED_FILE)

# --- Main ---
if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.login()
    bot.process_dms()
#!/usr/bin/env python3
import os
import json
import logging
import random
import re
from time import sleep
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired
from pydantic import ValidationError

# ─── Configuration ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger(__name__)

USERNAME       = os.getenv("INSTAGRAM_USERNAME")
PASSWORD       = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE   = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
MAX_REPOSTS    = 5
REEL_REGEX     = re.compile(r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_\-]+/?")

# ─── State Helpers ─────────────────────────────────────────────────────────────
def load_processed_ids() -> set:
    if PROCESSED_FILE.exists():
        try:
            return set(json.loads(PROCESSED_FILE.read_text()))
        except Exception:
            logger.warning("⚠️ Could not parse processed_messages.json, starting fresh")
    return set()

def save_processed_ids(processed: set):
    PROCESSED_FILE.write_text(json.dumps(list(processed)))

# ─── Bot Class ─────────────────────────────────────────────────────────────────
class RepostBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.critical("❌ INSTAGRAM_USERNAME/PASSWORD not set")
            exit(1)
        self.cl = Client()
        self.processed = load_processed_ids()

    def login(self):
        # Try restoring session
        if SESSION_FILE.exists():
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(USERNAME, PASSWORD)
                logger.info("✅ Session restored")
                return
            except Exception:
                logger.warning("⚠️ Session expired, performing fresh login")
        # Fresh login
        self.cl.login(USERNAME, PASSWORD)
        self.cl.dump_settings(SESSION_FILE)
        logger.info("✅ Fresh login complete and session saved")

    def process_dms(self):
        reposts = 0
        threads = self.cl.direct_threads(amount=20)

        for thread in threads:
            try:
                # Wrap entire thread processing
                for msg in thread.messages:
                    mid = str(msg.id)
                    if mid in self.processed:
                        continue

                    try:
                        text = msg.text or ""

                        # 1) Reel link in text
                        m = REEL_REGEX.search(text)
                        if m and reposts < MAX_REPOSTS:
                            url = m.group(0)
                            logger.info(f"↪️ Reposting reel URL: {url}")
                            self.cl.clip_upload_by_url(url, caption="")
                            reposts += 1
                            self.processed.add(mid)
                            sleep(random.uniform(1, 3))
                            continue

                        # 2) Forwarded reel (media_share with video_url)
                        if hasattr(msg, "media_share") and msg.media_share and reposts < MAX_REPOSTS:
                            media = msg.media_share
                            video_url = getattr(media, "video_url", None)
                            if video_url:
                                logger.info(f"↪️ Reposting forwarded reel: {video_url}")
                                self.cl.clip_upload_by_url(video_url, caption="")
                                reposts += 1
                                self.processed.add(mid)
                                sleep(random.uniform(1, 3))
                                continue

                            # 3) Photo with caption
                            photo_url = getattr(media, "thumbnail_url", None)
                            if photo_url:
                                caption = text.strip()
                                logger.info(f"🖼️ Reposting photo: {photo_url} | caption: {caption}")
                                self.cl.photo_upload_by_url(photo_url, caption=caption)
                                reposts += 1
                                self.processed.add(mid)
                                sleep(random.uniform(1, 3))
                                continue

                    except ValidationError as e:
                        logger.warning(f"⚠️ Skipped message {mid} due to data validation error: {e}")
                        self.processed.add(mid)
                        continue
                    except Exception as e:
                        logger.error(f"❌ Error processing message {mid}: {e}")
                        self.processed.add(mid)
                        continue

                    # mark as processed even if no repost
                    self.processed.add(mid)

                    if reposts >= MAX_REPOSTS:
                        logger.info("🛑 Reached daily repost limit")
                        break

                if reposts >= MAX_REPOSTS:
                    break

            except ValidationError as e:
                logger.error(f"❌ Skipped entire thread {thread.id} due to validation error: {e}")
                continue
            except Exception as e:
                logger.error(f"❌ Unexpected error in thread {thread.id}: {e}")
                continue

        logger.info(f"✅ Run complete. Total reposts: {reposts}")
        save_processed_ids(self.processed)

    def run(self):
        logger.info("🚀 Starting Instagram DM Repost Bot")
        self.login()
        self.process_dms()

# ─── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        bot = RepostBot()
        bot.run()
    except Exception as e:
        logger.critical(f"💥 Fatal error: {e}")
        exit(1)
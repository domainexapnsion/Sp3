#!/usr/bin/env python3
"""
Instagram DM Repost Bot
Handles session persistence, manual 2FA fallback, and reposts reels/photos from DMs.
"""

import os
import json
import time
import random
import logging
import re
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import ChallengeRequired

# ─── Config ────────────────────────────────────────────────────────────────────
USERNAME       = os.getenv("INSTAGRAM_USERNAME")
PASSWORD       = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE   = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
REEL_REGEX     = re.compile(r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_\-]+/?")
MAX_REPOSTS    = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def human_delay():
    time.sleep(random.uniform(1, 3))

def load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            pass
    return []

def save_json(path: Path, data):
    path.write_text(json.dumps(data))

# ─── Bot Class ────────────────────────────────────────────────────────────────
class InstagramBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.critical("❌ INSTAGRAM_USERNAME/PASSWORD not set")
            exit(1)
        self.cl = Client()
        self.processed = set(load_json(PROCESSED_FILE))

    def load_session_from_secret(self):
        secret = os.environ.get("INSTAGRAM_SESSION_JSON")
        if not secret:
            return False
        try:
            data = json.loads(secret)
            self.cl.set_settings(data)
            self.cl.get_timeline_feed()
            logger.info("✅ Loaded session from secret")
            return True
        except:
            return False

    def load_session(self):
        if not SESSION_FILE.exists():
            return False
        try:
            self.cl.load_settings(str(SESSION_FILE))
            self.cl.get_timeline_feed()
            logger.info("✅ Loaded session.json")
            return True
        except:
            SESSION_FILE.unlink(missing_ok=True)
            return False

    def save_session(self):
        try:
            self.cl.dump_settings(str(SESSION_FILE))
            logger.info("💾 session.json saved")
        except Exception as e:
            logger.error(f"❌ Could not save session: {e}")

    def login_with_session(self):
        # 1) GitHub secret session
        if self.load_session_from_secret():
            return True
        # 2) Local session.json
        if self.load_session():
            return True
        # 3) Fresh login with manual 2FA fallback
        logger.info("🔐 Attempting credential login…")
        try:
            self.cl.login(USERNAME, PASSWORD)
            self.save_session()
            logger.info("✅ Credential login successful; session saved")
            return True

        except ChallengeRequired:
            logger.warning("📧 Verification required—check your email/SMS for the code.")
            code = input("Enter the 6-digit Instagram verification code: ").strip()
            self.cl.login(USERNAME, PASSWORD, verification_code=code)
            self.save_session()
            logger.info("✅ Logged in after manual verification; session saved")
            return True

        except Exception as e:
            logger.error(f"❌ Credential login failed: {e}")
            return False

    def process_dms(self):
        reposts = 0
        threads = self.cl.direct_threads(amount=20)

        for thread in threads:
            for msg in thread.messages:
                mid = str(msg.id)
                if mid in self.processed:
                    continue

                text = msg.text or ""
                # 1) Reel link in text
                m = REEL_REGEX.search(text)
                if m and reposts < MAX_REPOSTS:
                    url = m.group(0)
                    logger.info(f"↪️ Reposting reel URL: {url}")
                    try:
                        self.cl.clip_upload_by_url(url, caption="")
                        reposts += 1
                    except Exception as e:
                        logger.error(f"❌ Reel repost failed: {e}")
                    human_delay()
                    self.processed.add(mid)
                    continue

                # 2) Forwarded reel
                if hasattr(msg, "media_share") and msg.media_share and reposts < MAX_REPOSTS:
                    media = msg.media_share
                    video_url = getattr(media, "video_url", None)
                    if video_url:
                        logger.info(f"↪️ Reposting forwarded reel: {video_url}")
                        try:
                            self.cl.clip_upload_by_url(video_url, caption="")
                            reposts += 1
                        except Exception as e:
                            logger.error(f"❌ Forwarded reel failed: {e}")
                        human_delay()
                        self.processed.add(mid)
                        continue

                    # 3) Photo + caption
                    photo_url = getattr(media, "thumbnail_url", None)
                    if photo_url:
                        caption = text.strip()
                        logger.info(f"🖼️ Reposting photo: {photo_url} | caption: {caption}")
                        try:
                            self.cl.photo_upload_by_url(photo_url, caption=caption)
                            reposts += 1
                        except Exception as e:
                            logger.error(f"❌ Photo repost failed: {e}")
                        human_delay()
                        self.processed.add(mid)
                        continue

                # mark processed
                self.processed.add(mid)
                if reposts >= MAX_REPOSTS:
                    logger.info("🛑 Reached daily repost limit")
                    break
            if reposts >= MAX_REPOSTS:
                break

        save_json(PROCESSED_FILE, list(self.processed))
        logger.info(f"✅ Run complete. Total reposts: {reposts}")

    def run(self):
        logger.info("🚀 Starting Instagram DM Repost Bot")
        if self.login_with_session():
            self.process_dms()
        else:
            logger.error("❌ Login failed; aborting.")

if __name__ == "__main__":
    InstagramBot().run()
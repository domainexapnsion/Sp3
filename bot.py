#!/usr/bin/env python3
"""
Debug Version – Instagram DM Repost Bot
• Safely skips reels with unsupported metadata (original_sound_info bug)
• Reposts:
    – Reel links shared in DM text
    – Photo attachments + accompanying text as caption
"""

import os
import re
import json
import time
import random
import logging

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, PleaseWaitFewMinutes
from pydantic import ValidationError
import instagrapi.extractors as extractors

# ─── Patch the internal extractor to swallow ValidationError ─────────────────
_orig_extract_media_v1 = extractors.extract_media_v1

def _safe_extract_media_v1(clip):
    try:
        return _orig_extract_media_v1(clip)
    except ValidationError as e:
        logging.warning(f"⚠️ Skipping unsupported reel metadata: {e}")
        return None

extractors.extract_media_v1 = _safe_extract_media_v1
# ──────────────────────────────────────────────────────────────────────────────

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────
USERNAME        = os.getenv("INSTAGRAM_USERNAME")
PASSWORD        = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE    = "session.json"
PROCESSED_FILE  = "processed_messages.json"
MAX_REPOSTS     = 5
REEL_REGEX      = re.compile(r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?")

# ─── Helpers ──────────────────────────────────────────────────────────────────
def human_delay():
    time.sleep(random.uniform(1, 3))

def load_json(path):
    if os.path.exists(path):
        return json.load(open(path))
    return []

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

# ─── Bot Class ────────────────────────────────────────────────────────────────
class InstagramBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.error("Missing INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD")
            exit(1)
        self.cl = Client()
        self.processed = set(load_json(PROCESSED_FILE))

    def login(self):
        # Try session file
        if os.path.exists(SESSION_FILE):
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(USERNAME, PASSWORD)  # validation call
                logger.info("✅ Loaded and validated session.json")
                return
            except Exception:
                logger.warning("⚠️ session.json expired, performing fresh login")

        # Fresh login + save
        self.cl.login(USERNAME, PASSWORD)
        self.cl.dump_settings(SESSION_FILE)
        logger.info("✅ Logged in fresh and saved session.json")

    def process_dms(self):
        threads = self.cl.direct_threads(amount=20)
        reposts = 0

        for thread in threads:
            for msg in thread.messages:
                msg_id = str(msg.id)
                if msg_id in self.processed:
                    continue

                text = msg.text or ""

                # 1) Reel link in text
                m = REEL_REGEX.search(text)
                if m and reposts < MAX_REPOSTS:
                    url = m.group(0)
                    logger.info(f"↪️ Reposting reel link: {url}")
                    try:
                        self.cl.clip_upload_by_url(url, caption="")
                        reposts += 1
                    except Exception as e:
                        logger.error(f"❌ Reel repost failed: {e}")
                    human_delay()
                    self.processed.add(msg_id)
                    if reposts >= MAX_REPOSTS:
                        break
                    continue

                # 2) Photo attachment + text caption
                if hasattr(msg, "media_share") and msg.media_share and reposts < MAX_REPOSTS:
                    media = msg.media_share
                    photo_url = getattr(media, "thumbnail_url", None)
                    if photo_url:
                        caption = text.strip()
                        logger.info(f"↪️ Reposting photo: {photo_url} with caption: {caption}")
                        try:
                            self.cl.photo_upload_by_url(photo_url, caption=caption)
                            reposts += 1
                        except Exception as e:
                            logger.error(f"❌ Photo repost failed: {e}")
                        human_delay()
                        self.processed.add(msg_id)
                        if reposts >= MAX_REPOSTS:
                            break
                        continue

                # Mark processed anyway to avoid re-checking
                self.processed.add(msg_id)

            if reposts >= MAX_REPOSTS:
                break

        save_json(PROCESSED_FILE, list(self.processed))
        logger.info(f"✅ Run complete. Total reposts: {reposts}")

    def run(self):
        logger.info("🚀 Starting Instagram DM Repost Bot")
        self.login()
        self.process_dms()

if __name__ == "__main__":
    InstagramBot().run()
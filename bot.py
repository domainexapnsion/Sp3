#!/usr/bin/env python3
"""
Daily Instagram DM → Repost Bot using instagrapi
"""

import os
import re
import json
import time
import random
import logging
import requests

from instagrapi import Client
from dotenv import load_dotenv

# ─── Setup Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Load Environment ─────────────────────────────────────────────────────────
load_dotenv()
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

if not USERNAME or not PASSWORD:
    logger.error("Missing INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD in env")
    exit(1)

# ─── Paths & Constants ────────────────────────────────────────────────────────
SESSION_DIR = os.path.expanduser(f"~/.config/instagrapi/session_{USERNAME}")
PROCESSED_FILE = "processed_dms.json"
MAX_PHOTOS_PER_RUN = 5
MAX_REELS_PER_RUN = 1
DELAY_RANGE = (1.0, 3.0)  # seconds

# ─── Helpers ─────────────────────────────────────────────────────────────────
def human_delay():
    t = random.uniform(*DELAY_RANGE)
    logger.debug(f"Sleeping {t:.1f}s")
    time.sleep(t)

def download_media(url: str, dest: str) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 16):
                f.write(chunk)
        return True
    except Exception as e:
        logger.warning(f"Failed download {url}: {e}")
        return False

# ─── Load or Init Processed DM IDs ────────────────────────────────────────────
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE) as f:
        processed = set(json.load(f))
else:
    processed = set()

# ─── Initialize Client ────────────────────────────────────────────────────────
client = Client(
    settings=SESSION_DIR,
    device=None  # let instagrapi pick & then save
)

try:
    client.load_settings(SESSION_DIR)
    logger.info("Loaded existing session")
except Exception:
    logger.info("No session found, logging in")
    client.login(USERNAME, PASSWORD)
    client.dump_settings(SESSION_DIR)
    logger.info("Logged in & saved session")

# ─── Fetch Direct Messages ────────────────────────────────────────────────────
logger.info("Fetching DMs...")
dms = client.direct_messages()
logger.info(f"Total threads: {len(dms)}")

reels_posted = 0
photos_posted = 0

for thread in dms:
    for msg in thread.messages:
        if msg.id in processed:
            continue

        # look for Instagram URL
        text = msg.text or ""
        urls = re.findall(r"https?://(?:www\.)?instagram\.com/(?:p|reel)/[A-Za-z0-9_-]+/?", text)
        media_urls = [m.thumbnail_url or m.url for m in msg.media or []]

        # ─── Process Reel URL ─────────────────────────────────────────
        if urls and reels_posted < MAX_REELS_PER_RUN:
            reel_url = urls[0]
            logger.info(f"Reposting reel: {reel_url}")
            # download temp
            tmp = "/tmp/reel.mp4"
            if download_media(reel_url + "media/?size=l", tmp):
                client.video_upload(tmp, caption="")
                reels_posted += 1
            else:
                logger.warning("Failed to download reel")
            human_delay()

        # ─── Process Photo + Caption ───────────────────────────────────
        elif media_urls and photos_posted < MAX_PHOTOS_PER_RUN:
            photo_url = media_urls[0]
            caption = text.strip()
            logger.info(f"Reposting photo: {photo_url} caption: {caption[:30]}…")
            tmp = "/tmp/photo.jpg"
            if download_media(photo_url, tmp):
                client.photo_upload(tmp, caption=caption)
                photos_posted += 1
            else:
                logger.warning("Failed to download photo")
            human_delay()

        processed.add(msg.id)

# ─── Save State ───────────────────────────────────────────────────────────────
with open(PROCESSED_FILE, "w") as f:
    json.dump(list(processed), f)

client.dump_settings(SESSION_DIR)
logger.info(f"Done! Reels: {reels_posted}, Photos: {photos_posted}")
#!/usr/bin/env python3
"""
Instagram Repost Bot - The Definitive Fix
Author: Gemini
Date: August 8, 2025
Description: This script is built to be brutally effective at reposting media from DMs.
It avoids the common PydanticValidationError by fetching DM and media data using
low-level API calls, bypassing instagrapi's Pydantic models where they are known to fail.
"""

 

import instagrapi
import os
import json
import time
import random
import logging
import re
import requests
import sys
from pathlib import Path

# Attempt to import instagrapi
try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired,
        PydanticValidationError,
        ClientError
    )
    from instagrapi.types import Media
except ImportError:
    print("Error: instagrapi is not installed. Please run 'pip install instagrapi requests'")
    sys.exit(1)

# --- Configuration ---
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
MAX_REPOSTS_PER_RUN = 5  # Safety limit

# --- Setup Logging ---
DOWNLOADS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger(__name__)


class InstagramRepostBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.critical("❌ FATAL: INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables must be set.")
            sys.exit(1)

        self.cl = Client()
        self.cl.delay_range = [2, 5]
        self.processed_ids = self._load_processed_ids()
        logger.info(f"✅ Loaded {len(self.processed_ids)} previously processed message IDs.")

    def _load_processed_ids(self):
        if PROCESSED_FILE.exists():
            try:
                return set(json.loads(PROCESSED_FILE.read_text()))
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Could not read {PROCESSED_FILE}, starting fresh.")
                return set()
        return set()

    def _save_processed_ids(self):
        PROCESSED_FILE.write_text(json.dumps(list(self.processed_ids), indent=2))

    def login(self):
        """Handles login using session file or fresh credentials."""
        logger.info("🔐 Attempting to log in...")
        if SESSION_FILE.exists():
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(USERNAME, PASSWORD)
                # Test the session
                self.cl.get_timeline_feed()
                logger.info("✅ Logged in successfully using session file.")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Session login failed: {e}. Attempting fresh login.")
                # If session is broken, remove it
                SESSION_FILE.unlink(missing_ok=True)

        try:
            self.cl.login(USERNAME, PASSWORD)
            self.cl.dump_settings(SESSION_FILE)
            logger.info("✅ Fresh login successful. Session saved.")
            return True
        except Exception as e:
            logger.error(f"❌ FATAL: Could not log in. Error: {e}")
            return False

    def get_media_info_robustly(self, media_pk: str) -> dict:
        """
        Gets media info, bypassing Pydantic validation on failure by using a raw API call.
        """
        logger.info(f"🔍 Getting info for media PK: {media_pk}")
        try:
            # First, try the normal way
            media_info = self.cl.media_info(media_pk)
            return media_info.dict()
        except PydanticValidationError as e:
            logger.warning(f"⚠️ Pydantic validation failed for media_info. This is EXPECTED for some reels.")
            logger.warning(f"   Falling back to raw private API request. Error was: {e}")
            try:
                # Fallback: Use a direct, raw API call that returns a dictionary
                data = self.cl.private_request(f"media/{media_pk}/info/")
                if data.get('items'):
                    logger.info("✅ Successfully fetched media info via raw API fallback.")
                    return data['items'][0]
                else:
                    logger.error("❌ Raw API fallback failed: 'items' key not found.")
                    return {}
            except Exception as e2:
                logger.error(f"❌ Raw API fallback also failed: {e2}")
                return {}
        except Exception as e:
            logger.error(f"❌ An unexpected error occurred in get_media_info_robustly: {e}")
            return {}

    def download_media(self, media_info: dict) -> Path | None:
        """Downloads a video or photo from media info dictionary."""
        media_type = media_info.get("media_type")
        filename = f"{media_info.get('pk')}_{int(time.time())}"
        download_url = None

        if media_type == 2 and media_info.get("video_url"):  # Video
            download_url = media_info["video_url"]
            filepath = DOWNLOADS_DIR / f"{filename}.mp4"
        elif media_type == 1 and media_info.get("thumbnail_url"):  # Photo
            # For photos, get the highest quality candidate
            candidates = media_info.get("image_versions2", {}).get("candidates", [])
            if candidates:
                download_url = candidates[0].get("url")
            else: # Fallback to thumbnail if no other candidates
                 download_url = media_info.get("thumbnail_url")
            filepath = DOWNLOADS_DIR / f"{filename}.jpg"
        else:
            logger.warning(f"Unsupported media type ({media_type}) or missing URL.")
            return None

        if not download_url:
            logger.error("Could not find a valid download URL.")
            return None

        try:
            logger.info(f"Downloading from {download_url} to {filepath}...")
            response = requests.get(download_url, stream=True, timeout=60)
            response.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("✅ Download complete.")
            return filepath
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            return None

    def upload_bruteforce(self, file_path: Path, caption: str) -> bool:
        """
        Tries every possible upload method until one works. This is the brute-force part.
        """
        logger.info(f"🚀 Starting brute-force upload for {file_path.name}...")

        # Determine potential methods based on file extension
        is_video = file_path.suffix.lower() == ".mp4"
        is_photo = file_path.suffix.lower() in [".jpg", ".jpeg"]

        upload_methods = []
        if is_video:
            upload_methods.extend([
                ("Reel (clip_upload)", self.cl.clip_upload),
                ("Video (video_upload)", self.cl.video_upload)
            ])
        if is_photo:
            upload_methods.append(("Photo (photo_upload)", self.cl.photo_upload))

        if not upload_methods:
            logger.error(f"No upload method available for file type: {file_path.suffix}")
            return False

        for name, method in upload_methods:
            try:
                logger.info(f"🔄 Trying to upload as: {name}")
                result = method(file_path, caption)
                if result:
                    logger.info(f"✅ SUCCESS! Uploaded as {name}. Media PK: {result.pk}")
                    return True
                else:
                    logger.warning(f"⚠️ {name} completed but returned no result. Trying next method.")
            except Exception as e:
                logger.warning(f"Failed to upload as {name}. Error: {e}. Trying next method.")
                time.sleep(1)

        logger.error(f"❌ All upload methods failed for {file_path}.")
        return False

    def process_dms(self):
        """
        The core logic. Fetches DMs using raw API calls to avoid Pydantic errors.
        """
        logger.info("📨 Fetching DM threads using raw API call to prevent validation errors...")
        reposts_count = 0
        try:
            # THIS IS THE FIX: Use private_request to get raw dictionary data
            inbox_data = self.cl.private_request("direct_v2/inbox/?persistentBadging=true&limit=20")
            threads = inbox_data.get("inbox", {}).get("threads", [])

            if not threads:
                logger.info("No DM threads found in inbox.")
                return

            logger.info(f"Found {len(threads)} threads. Checking for new media...")

            for thread in threads:
                if reposts_count >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"Reached max reposts limit of {MAX_REPOSTS_PER_RUN}. Stopping for this run.")
                    break

                # The messages are ordered newest-first in the API response
                for item in thread.get("items", []):
                    item_id = item.get("item_id")
                    if not item_id or item_id in self.processed_ids:
                        continue

                    # Mark as processed immediately to avoid retries
                    self.processed_ids.add(item_id)

                    media_share = item.get("media_share")
                    if not media_share:
                        continue

                    logger.info(f"Found shared media in thread {thread.get('thread_id')}, message {item_id}")

                    media_pk = media_share.get("pk")
                    caption = media_share.get("caption", {}).get("text", "") if media_share.get("caption") else ""

                    # Get media info robustly
                    media_info = self.get_media_info_robustly(media_pk)
                    if not media_info:
                        logger.error(f"Could not retrieve info for media PK {media_pk}. Skipping.")
                        continue

                    # Download the media
                    file_path = self.download_media(media_info)
                    if not file_path:
                        logger.error(f"Could not download media for PK {media_pk}. Skipping.")
                        continue

                    # Brute-force the upload
                    success = self.upload_bruteforce(file_path, caption)

                    # Cleanup
                    file_path.unlink() # Delete the downloaded file

                    if success:
                        reposts_count += 1
                        logger.info(f"Repost count: {reposts_count}/{MAX_REPOSTS_PER_RUN}")
                    else:
                        logger.error(f"Failed to repost media from message {item_id}.")

                    # Human-like delay
                    time.sleep(random.uniform(15, 30))

        except Exception as e:
            logger.error(f"❌ An error occurred during DM processing: {e}", exc_info=True)
        finally:
            logger.info("Saving processed message IDs...")
            self._save_processed_ids()
            logger.info(f"Run complete. Total reposts this session: {reposts_count}")

def main():
    logger.info("🔥 DAMNIT REPOST BOT - INITIALIZING 🔥")
    bot = InstagramRepostBot()
    if bot.login():
        bot.process_dms()
    logger.info("✅ Bot run finished.")

if __name__ == "__main__":
    main()
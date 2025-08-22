#!/usr/bin/env python3
"""
Instagram Repost Bot - Fixed Version for Reel Handling
Description: This bot checks for unread DMs, downloads shared media (photos/videos/reels),
and reposts them to your account. Now properly handles sent reels from DMs.
"""

import os
import json
import time
import random
import logging
import sys
from pathlib import Path

# --- Dependency Installation ---
# Ensures instagrapi is available.
try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired
except ImportError:
    print("Installing required package: instagrapi")
    os.system(f"{sys.executable} -m pip install -q instagrapi")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired

# --- Configuration ---
# Credentials will be read from GitHub Secrets.
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# File paths for session and tracking data.
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
CONFIG_FILE = Path("bot_config.json")

# Operational Parameters
MAX_REPOSTS_PER_RUN = 5
NETWORK_RETRY_COUNT = 5

# --- Logging Setup ---
# Creates a log file to record the bot's activity.
DOWNLOADS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('RepostBot')

class InstagramRepostBot:
    def __init__(self):
        """Initializes the bot client and loads tracking data."""
        self.cl = Client()
        self.cl.delay_range = [2, 5]  # Set human-like delays
        self.processed_ids = self._load_json(PROCESSED_FILE, set())
        self.config = self._load_json(CONFIG_FILE, {})
        logger.info(f"Bot initialized. Previously processed {len(self.processed_ids)} messages.")

    def _load_json(self, file_path: Path, default_value):
        """Safely loads data from a JSON file."""
        if file_path.exists():
            try:
                with file_path.open('r') as f:
                    content = f.read()
                    if not content: return default_value
                    # Convert list to set for processed_ids for faster lookups
                    data = json.loads(content)
                    return set(data) if isinstance(data, list) else data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"⚠️ Could not read {file_path}: {e}. Starting fresh.")
        return default_value

    def _save_json(self, data, file_path: Path):
        """Saves data to a JSON file."""
        try:
            with file_path.open('w') as f:
                # Convert set back to list for JSON serialization
                if isinstance(data, set):
                    data = list(data)
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error(f"❌ Could not write to {file_path}: {e}")

    def tactical_login(self):
        """
        Handles authentication. Prioritizes using the session file, which is essential
        for running in an automated environment like GitHub Actions.
        """
        logger.info("🔑 Initiating authentication protocols...")

        # Phase 1: Prioritize Session-based authentication
        if SESSION_FILE.exists():
            try:
                logger.info("Found existing session file. Loading settings...")
                self.cl.load_settings(SESSION_FILE)
                logger.info("Verifying session by fetching account info...")
                self.cl.account_info()  # A lightweight check to see if the session is valid
                logger.info("✅ Session is valid and active.")
                return True
            except Exception as e:
                logger.warning(f"⚠️ Session file is invalid or expired: {e}. Proceeding with fresh login.")

        # Phase 2: Fallback to Credential login (should not happen in GitHub Actions if session is valid)
        logger.info("🚀 No valid session found. Deploying fresh credentials.")
        if not USERNAME or not PASSWORD:
            logger.critical("⛔ CREDENTIALS NOT FOUND. Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD secrets.")
            return False

        try:
            self.cl.login(USERNAME, PASSWORD)
            logger.info("🔥 Authentication successful.")
            # This should not be needed in the GitHub Action but is good practice.
            self.cl.dump_settings(SESSION_FILE)
            logger.info("New session file saved for future runs.")
            return True
        except Exception as e:
            # This will cause the GitHub Action to fail, as it cannot handle interactive prompts.
            logger.critical(f"☠️ FATAL LOGIN FAILURE: {e}")
            return False

    def download_media(self, media_pk: str, media_type: int) -> Path | None:
        """
        Downloads media from Instagram using instagrapi's built-in functions,
        which properly handle authentication for private accounts.
        """
        logger.info(f"📥 Downloading media item {media_pk} (type: {media_type})...")
        try:
            if media_type == 2:  # Video/Clip/Reel
                return self.cl.video_download(media_pk, folder=DOWNLOADS_DIR)
            elif media_type == 1:  # Photo
                return self.cl.photo_download(media_pk, folder=DOWNLOADS_DIR)
            elif media_type == 8:  # Album/Carousel
                # Download the first item of the album
                return self.cl.album_download(media_pk, folder=DOWNLOADS_DIR)[0]
            else:
                logger.warning(f"Unsupported media type: {media_type}")
                return None
        except Exception as e:
            logger.error(f"☢️ Download failed for media {media_pk}: {e}")
            return None

    def repost_media(self, file_path: Path, caption: str) -> bool:
        """Uploads the downloaded media to the bot's account."""
        logger.info(f"🚀 Reposting media from {file_path.name}...")
        try:
            if file_path.suffix.lower() in ['.mp4', '.mov', '.avi']:
                # Use clip_upload for reels/videos
                result = self.cl.clip_upload(file_path, caption)
                logger.info(f"✅ Clip upload result: {result}")
            else:
                result = self.cl.photo_upload(file_path, caption)
                logger.info(f"✅ Photo upload result: {result}")
            return True
        except Exception as e:
            logger.error(f"💥 Repost failed: {e}", exc_info=True)
            return False

    def run(self):
        """The main execution loop for the bot."""
        if not self.tactical_login():
            sys.exit("Terminating due to login failure.")

        logger.info("📡 Checking for unread messages...")
        repost_counter = 0
        try:
            # Fetch the 20 most recent threads, looking for unread ones.
            threads = self.cl.direct_threads(thread_count=20, selected_filter='unread')
            if not threads:
                logger.info("No unread message threads found.")
                return

            logger.info(f"Found {len(threads)} unread thread(s).")
            for thread in threads:
                if repost_counter >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"Repost limit of {MAX_REPOSTS_PER_RUN} reached for this run.")
                    break

                for message in thread.messages:
                    if message.id in self.processed_ids:
                        continue

                    # Mark message as processed immediately to avoid retries on failure.
                    self.processed_ids.add(message.id)

                    # 🔍 DEBUG: Check what type of message this is
                    logger.info(f"=== MESSAGE DEBUG ===")
                    logger.info(f"Message ID: {message.id}")
                    logger.info(f"Has media_share: {hasattr(message, 'media_share') and message.media_share is not None}")
                    logger.info(f"Has story_share: {hasattr(message, 'story_share') and message.story_share is not None}")
                    logger.info(f"Has clip: {hasattr(message, 'clip') and message.clip is not None}")
                    logger.info(f"Has reel_share: {hasattr(message, 'reel_share') and message.reel_share is not None}")
                    logger.info(f"Message text: {getattr(message, 'text', 'No text')}")

                    media_to_download = None
                    
                    # Handle regular media shares (posts, photos)
                    if message.media_share:
                        media_to_download = message.media_share
                        logger.info(f"Found regular media share from user @{media_to_download.user.username}")
                    
                    # 🎯 NEW: Handle story shares (this might be where reels come through)
                    elif hasattr(message, 'story_share') and message.story_share:
                        story = message.story_share
                        if hasattr(story, 'media') and story.media:
                            media_to_download = story.media
                            logger.info(f"Found story share with media from user @{media_to_download.user.username}")
                    
                    # 🎯 NEW: Handle direct clip shares
                    elif hasattr(message, 'clip') and message.clip:
                        media_to_download = message.clip
                        logger.info(f"Found clip share from user @{media_to_download.user.username}")
                    
                    # 🎯 NEW: Sometimes reels come as 'reel_share'
                    elif hasattr(message, 'reel_share') and message.reel_share:
                        if hasattr(message.reel_share, 'media') and message.reel_share.media:
                            media_to_download = message.reel_share.media
                            logger.info(f"Found reel share with media")

                    # If we found media to download
                    if media_to_download:
                        logger.info(f"Media PK: {media_to_download.pk}, Media Type: {media_to_download.media_type}")
                        
                        # Download the media
                        local_path = self.download_media(media_to_download.pk, media_to_download.media_type)
                        if not local_path:
                            continue

                        # Repost the media
                        caption = getattr(media_to_download, 'caption_text', '') or ""
                        if self.repost_media(local_path, caption):
                            repost_counter += 1
                        
                        # Clean up the downloaded file
                        local_path.unlink()

                        # Add a delay to appear more human
                        sleep_time = random.randint(30, 90)
                        logger.info(f"😴 Sleeping for {sleep_time} seconds...")
                        time.sleep(sleep_time)

                        if repost_counter >= MAX_REPOSTS_PER_RUN:
                            break
                    else:
                        logger.info(f"Message {message.id} contains no supported media type, skipping.")
        
        except Exception as e:
            logger.critical(f"An unexpected error occurred during the run: {e}", exc_info=True)
        finally:
            logger.info("Saving processed message IDs...")
            self._save_json(self.processed_ids, PROCESSED_FILE)
            logger.info(f"🏁 Mission complete. Reposted {repost_counter} items in this run.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

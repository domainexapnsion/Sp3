#!/usr/bin/env python3
"""
Instagram Repost Bot
- Uses an external service for reliable downloading to bypass 401 errors.
- Falls back to the internal library method if the external service fails.
- Improved error handling and media ID extraction.
"""
import os
import json
import time
import random
import logging
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any, Union

# Attempt to import required libraries, installing them if they are missing.
try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests
except ImportError:
    print("Required libraries not found. Installing...")
    os.system(f"{sys.executable} -m pip install -q instagrapi requests")
    print("Installation complete. Please run the script again.")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests

# --- Configuration ---
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# --- Enhanced Operational Parameters ---
MAX_REPOSTS_PER_RUN = 3
NETWORK_RETRY_COUNT = 3 # Reduced retries for faster failure on persistent issues
MIN_DELAY = 3
MAX_DELAY = 10

# --- User Agent Rotation ---
USER_AGENTS = [
    "Instagram 219.0.0.12.117 Android",
    "Instagram 210.0.0.13.120 Android",
    "Instagram 217.0.0.13.123 Android",
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
]

# --- Logging Setup ---
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
        self.cl = Client()
        self.cl.delay_range = [MIN_DELAY, MAX_DELAY]
        self.processed_ids = self.load_processed_ids()
        logger.info(f"Bot initialized. Previously processed {len(self.processed_ids)} messages.")

    def load_processed_ids(self):
        if PROCESSED_FILE.exists():
            try:
                with PROCESSED_FILE.open('r') as f:
                    return set(json.load(f))
            except (json.JSONDecodeError, IOError):
                return set()
        return set()

    def save_processed_ids(self):
        try:
            with PROCESSED_FILE.open('w') as f:
                json.dump(list(self.processed_ids), f)
        except Exception as e:
            logger.error(f"Failed to save processed IDs: {e}")

    def random_delay(self, min_seconds=2, max_seconds=8):
        delay = random.uniform(min_seconds, max_seconds)
        logger.info(f"😴 Random delay of {delay:.2f} seconds")
        time.sleep(delay)

    def rotate_user_agent(self):
        new_agent = random.choice(USER_AGENTS)
        self.cl.set_user_agent(new_agent)
        logger.info(f"🔄 Rotated user agent to: {new_agent}")

    def login(self):
        logger.info("🔑 Attempting login...")
        if SESSION_FILE.exists():
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.account_info() # Verify session is still valid
                logger.info("✅ Session loaded and is valid.")
                return True
            except Exception as e:
                logger.warning(f"Session expired or invalid ({e}), attempting fresh login...")
                if SESSION_FILE.exists():
                    SESSION_FILE.unlink() # Delete expired session
        
        if USERNAME and PASSWORD:
            self.rotate_user_agent()
            try:
                self.cl.login(USERNAME, PASSWORD)
                self.cl.dump_settings(SESSION_FILE)
                logger.info("✅ Login successful.")
                return True
            except Exception as e:
                logger.error(f"❌ Login failed: {e}")
                return False
        else:
            logger.error("❌ Credentials (INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD) not found.")
            return False

    def extract_shortcode_from_url(self, url: str) -> Optional[str]:
        if not url:
            return None
        patterns = [r'instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)']
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def shortcode_to_media_id(self, shortcode: str) -> Optional[str]:
        try:
            media_pk = self.cl.media_pk_from_code(shortcode)
            return str(media_pk)
        except Exception as e:
            logger.warning(f"Failed to convert shortcode {shortcode} to media_id: {e}")
            return None
            
    def get_media_info_by_any_id(self, media_id: Union[str, int]) -> Optional[Any]:
        logger.info(f"🔍 Trying to get media info for ID: {media_id}")
        try:
            # instagrapi's media_info is robust and can handle various ID formats
            return self.cl.media_info(str(media_id))
        except Exception as e:
            logger.warning(f"❌ Could not get media info for ID {media_id}: {e}")
            return None

    def find_reels_in_messages(self, threads):
        reels = []
        if not threads:
            return reels
            
        for thread in threads:
            for item in thread.get('items', []):
                item_id = item.get('item_id')
                if not item_id or item_id in self.processed_ids:
                    continue

                media_id = None
                shortcode = None
                media_type = 2 # Default to video/reel

                # Standard reel/media shares often contain the full media object
                if item.get('reel_share', {}).get('media'):
                    media = item['reel_share']['media']
                    media_id = media.get('id')
                    shortcode = media.get('code')
                elif item.get('media_share'):
                    media = item['media_share']
                    media_id = media.get('id')
                    shortcode = media.get('code')
                # 'clip' is a common format for reels shared in DMs
                elif item.get('clip', {}).get('clip'):
                    media = item['clip']['clip']
                    media_id = media.get('pk')
                    shortcode = media.get('code')
                
                if media_id and shortcode:
                    logger.info(f"🎯 Found reel: {shortcode} (ID: {media_id})")
                    reels.append({
                        'item_id': item_id,
                        'media_id': str(media_id),
                        'shortcode': shortcode,
                        'media_type': media_type,
                        'timestamp': item.get('timestamp', 0)
                    })
        
        reels.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return reels

    def download_media_externally(self, shortcode: str) -> Optional[Path]:
        """
        NEW: Primary download method using an external service to avoid 401 errors.
        """
        logger.info(f"🌍 Attempting external download for shortcode: {shortcode}")
        insta_url = f"https://www.instagram.com/reel/{shortcode}/"
        # Using a reliable public API endpoint for downloading social media content
        api_url = "https://api.cobalt.tools/api/json"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        payload = {
            "url": insta_url
        }

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "stream":
                video_url = data.get("url")
                if not video_url:
                    logger.error("❌ External API returned a stream status but no URL.")
                    return None
                
                logger.info(f"✅ External service provided video URL. Downloading...")
                video_response = requests.get(video_url, stream=True, timeout=60)
                video_response.raise_for_status()
                
                file_path = DOWNLOADS_DIR / f"{shortcode}.mp4"
                with open(file_path, "wb") as f:
                    for chunk in video_response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"✅ External download successful. Saved to: {file_path}")
                return file_path
            else:
                logger.error(f"❌ External service failed. Status: {data.get('status')}, Text: {data.get('text')}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ External download request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ An unexpected error occurred during external download: {e}")
            return None

    def download_media(self, reel_data: Dict) -> Optional[Path]:
        media_id = reel_data['media_id']
        shortcode = reel_data['shortcode']
        media_type = reel_data['media_type']
        
        logger.info(f"📥 Starting download process for reel {shortcode} (ID: {media_id})")
        self.random_delay(2, 5)

        # --- METHOD 1: EXTERNAL DOWNLOADER (PRIMARY) ---
        external_path = self.download_media_externally(shortcode)
        if external_path:
            return external_path

        # --- METHOD 2: INSTAGRAPI (FALLBACK) ---
        logger.warning(f"⚠️ External download failed. Falling back to internal library method for {media_id}.")
        try:
            if media_type == 2: # Video/Reel
                return self.cl.clip_download(media_id, folder=DOWNLOADS_DIR)
            elif media_type == 1: # Photo
                return self.cl.photo_download(media_id, folder=DOWNLOADS_DIR)
            else:
                logger.warning(f"Unknown media type {media_type}, attempting clip download.")
                return self.cl.clip_download(media_id, folder=DOWNLOADS_DIR)
        except Exception as e:
            logger.error(f"❌ All download methods failed for {media_id}. Error: {e}")
            return None

    def upload_reel(self, video_path: Path, caption="Reposted 🔄"):
        try:
            logger.info(f"🚀 Uploading reel from {video_path}")
            if not video_path.exists() or video_path.stat().st_size == 0:
                logger.error(f"❌ Video file is missing or empty: {video_path}")
                return False
            
            self.random_delay(5, 15)
            
            result = self.cl.clip_upload(
                video_path,
                caption=caption,
                extra_data={"share_to_feed": True}
            )
            if result:
                logger.info(f"✅ Reel uploaded successfully! Media ID: {result.id}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Critical upload error: {e}")
            return False

    def run(self):
        logger.info("🚀 Starting Instagram Repost Bot...")
        if not self.login():
            logger.error("❌ Cannot proceed without login. Exiting.")
            return

        try:
            threads = self.cl.direct_threads(amount=20)
            if not threads:
                logger.info("🤷 No threads found in DMs.")
                return
            
            reels = self.find_reels_in_messages(threads)
            if not reels:
                logger.info("🤷 No new, unprocessed reels found in DMs.")
                return
                
            logger.info(f"🎯 Found {len(reels)} new reels to process.")
            
            processed_count = 0
            for i, reel in enumerate(reels):
                if processed_count >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"⏹️ Reached max repost limit of {MAX_REPOSTS_PER_RUN}.")
                    break
                
                logger.info(f"--- Processing reel {i+1}/{len(reels)} (Shortcode: {reel['shortcode']}) ---")
                
                reel_path = self.download_media(reel)
                if not reel_path:
                    logger.error(f"❌ Failed to download reel {reel['shortcode']}. Skipping.")
                    self.processed_ids.add(reel['item_id'])
                    continue
                
                caption = f"Amazing reel! 🔥\n\n#repost #viral #reel"
                if self.upload_reel(reel_path, caption):
                    logger.info(f"✅ Successfully processed reel {reel['shortcode']}")
                    processed_count += 1
                else:
                    logger.error(f"❌ Failed to upload reel {reel['shortcode']}")
                
                # Mark as processed regardless of upload success to avoid retrying failed uploads
                self.processed_ids.add(reel['item_id'])
                
                # Clean up downloaded file
                try:
                    os.remove(reel_path)
                    logger.info(f"🧹 Cleaned up downloaded file: {reel_path.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to clean up file: {e}")
                
                if i < len(reels) - 1 and processed_count < MAX_REPOSTS_PER_RUN:
                    self.random_delay(15, 45)
            
            logger.info(f"🏁 Mission complete! Processed {processed_count} reels in this run.")
            
        except Exception as e:
            logger.error(f"❌ Critical error in main execution: {e}", exc_info=True)
            
        finally:
            self.save_processed_ids()
            logger.info("💾 Saved processed IDs.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

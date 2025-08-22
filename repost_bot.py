#!/usr/bin/env python3
"""
Instagram Repost Bot - Fixed Version for Reel Handling
"""

import os
import json
import time
import random
import logging
import sys
from pathlib import Path

try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired
except ImportError:
    os.system(f"{sys.executable} -m pip install -q instagrapi")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired

# Configuration
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Logging setup
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
        self.cl.delay_range = [2, 5]
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
        with PROCESSED_FILE.open('w') as f:
            json.dump(list(self.processed_ids), f)

    def login(self):
        logger.info("🔑 Attempting login...")
        try:
            if SESSION_FILE.exists():
                self.cl.load_settings(SESSION_FILE)
                self.cl.account_info()
                logger.info("✅ Session is valid.")
                return True
            else:
                if USERNAME and PASSWORD:
                    self.cl.login(USERNAME, PASSWORD)
                    self.cl.dump_settings(SESSION_FILE)
                    logger.info("✅ Login successful.")
                    return True
                else:
                    logger.error("❌ Credentials not found.")
                    return False
        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            return False

    def get_reel_from_dms(self):
        """Extract reel ID from direct messages using raw API response"""
        try:
            response = self.cl.private_request("direct_v2/inbox/", params={
                "visual_message_return_type": "unseen",
                "thread_message_limit": 10,
                "persistentBadging": "true",
                "limit": 20
            })
            
            threads = response.get('inbox', {}).get('threads', [])
            for thread in threads:
                for item in thread.get('items', []):
                    item_id = item.get('item_id')
                    if item_id in self.processed_ids:
                        continue
                    
                    # Check for reel share
                    if 'reel_share' in item and item['reel_share']:
                        reel_data = item['reel_share']
                        media_id = reel_data.get('media', {}).get('id')
                        if media_id:
                            self.processed_ids.add(item_id)
                            return media_id
                    
                    # Check for media share (might be a reel)
                    elif 'media_share' in item and item['media_share']:
                        media_data = item['media_share']
                        if media_data.get('media_type') == 2:  # Video type
                            media_id = media_data.get('id')
                            self.processed_ids.add(item_id)
                            return media_id
            return None
        except Exception as e:
            logger.error(f"Error checking DMs: {e}")
            return None

    def download_reel(self, media_id):
        """Download reel using media ID"""
        try:
            logger.info(f"📥 Downloading reel {media_id}")
            reel_path = self.cl.video_download(media_id, folder=DOWNLOADS_DIR)
            return reel_path
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            return None

    def upload_reel(self, video_path, caption=""):
        """Upload reel to your account"""
        try:
            logger.info("🚀 Uploading reel...")
            self.cl.clip_upload(video_path, caption=caption)
            logger.info("✅ Reel uploaded successfully!")
            return True
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            return False

    def run(self):
        if not self.login():
            return

        logger.info("🔍 Checking for reels in DMs...")
        media_id = self.get_reel_from_dms()
        
        if media_id:
            reel_path = self.download_reel(media_id)
            if reel_path:
                if self.upload_reel(reel_path, "Check out this reel!"):
                    logger.info("✅ Successfully processed reel!")
                # Clean up downloaded file
                try:
                    os.remove(reel_path)
                except:
                    pass
            else:
                logger.error("❌ Failed to download reel")
        else:
            logger.info("🤷 No new reels found in DMs")
        
        self.save_processed_ids()
        logger.info("🏁 Mission complete.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

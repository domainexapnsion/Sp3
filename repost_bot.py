#!/usr/bin/env python3
"""
Instagram Repost Bot - Enhanced Version with Error Handling
"""

import os
import json
import time
import random
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes
except ImportError:
    os.system(f"{sys.executable} -m pip install -q instagrapi")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes

# Configuration
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Enhanced operational parameters
MAX_REPOSTS_PER_RUN = 3
NETWORK_RETRY_COUNT = 5
MIN_DELAY = 3
MAX_DELAY = 10

# User agent rotation
USER_AGENTS = [
    "Instagram 219.0.0.12.117 Android",
    "Instagram 210.0.0.13.120 Android", 
    "Instagram 217.0.0.13.123 Android",
    "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
]

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
        """Add a random delay between requests"""
        delay = random.uniform(min_seconds, max_seconds)
        logger.info(f"😴 Random delay of {delay:.2f} seconds")
        time.sleep(delay)
        return delay

    def rotate_user_agent(self):
        """Rotate user agent to appear more human"""
        new_agent = random.choice(USER_AGENTS)
        self.cl.set_user_agent(new_agent)
        logger.info(f"🔄 Rotated user agent to: {new_agent}")

    def login(self):
        """Handle authentication with retries and error handling"""
        logger.info("🔑 Attempting login...")
        
        for attempt in range(3):
            try:
                if SESSION_FILE.exists():
                    self.cl.load_settings(SESSION_FILE)
                    # Verify session is still valid
                    self.cl.account_info()
                    logger.info("✅ Session is valid.")
                    return True
                else:
                    if USERNAME and PASSWORD:
                        self.rotate_user_agent()
                        self.cl.login(USERNAME, PASSWORD)
                        self.cl.dump_settings(SESSION_FILE)
                        logger.info("✅ Login successful.")
                        return True
                    else:
                        logger.error("❌ Credentials not found.")
                        return False
            except PleaseWaitFewMinutes as e:
                wait_time = (attempt + 1) * 60  # Wait 1, 2, then 3 minutes
                logger.warning(f"⏳ Instagram asked us to wait. Waiting {wait_time} seconds...")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"❌ Login attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    self.random_delay(10, 30)
        
        logger.error("❌ All login attempts failed.")
        return False

    def make_api_request(self, endpoint, params=None):
        """Make API request with retry logic and error handling"""
        for attempt in range(NETWORK_RETRY_COUNT):
            try:
                self.rotate_user_agent()
                response = self.cl.private_request(endpoint, params=params or {})
                return response
            except Exception as e:
                logger.warning(f"API request failed (attempt {attempt+1}): {e}")
                if attempt < NETWORK_RETRY_COUNT - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.info(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"All API request attempts failed for {endpoint}")
                    return None

    def get_reel_from_dms(self):
        """Extract reel ID from direct messages using raw API response"""
        logger.info("🔍 Checking for reels in DMs...")
        
        params = {
            "visual_message_return_type": "unseen",
            "thread_message_limit": 10,
            "persistentBadging": "true",
            "limit": 20
        }
        
        response = self.make_api_request("direct_v2/inbox/", params)
        if not response:
            return None
            
        try:
            threads = response.get('inbox', {}).get('threads', [])
            logger.info(f"Found {len(threads)} threads")
            
            for thread in threads:
                thread_id = thread.get('thread_id', 'unknown')
                logger.info(f"Checking thread {thread_id}")
                
                items = thread.get('items', [])
                logger.info(f"Thread has {len(items)} items")
                
                for item in items:
                    item_id = item.get('item_id')
                    if not item_id or item_id in self.processed_ids:
                        continue
                        
                    logger.info(f"Checking item {item_id}")
                    
                    # Check for reel share
                    if 'reel_share' in item and item['reel_share']:
                        reel_data = item['reel_share']
                        media = reel_data.get('media', {})
                        media_id = media.get('id')
                        
                        if media_id:
                            logger.info(f"🎯 Found reel share: {media_id}")
                            self.processed_ids.add(item_id)
                            return media_id
                    
                    # Check for media share (might be a reel)
                    elif 'media_share' in item and item['media_share']:
                        media_data = item['media_share']
                        media_type = media_data.get('media_type')
                        media_id = media_data.get('id')
                        
                        if media_type == 2 and media_id:  # Video type
                            logger.info(f"🎯 Found media share (video): {media_id}")
                            self.processed_ids.add(item_id)
                            return media_id
                    
                    # Check for clip shares
                    elif 'clip' in item and item['clip']:
                        clip_data = item['clip']
                        media_id = clip_data.get('pk') or clip_data.get('id')
                        
                        if media_id:
                            logger.info(f"🎯 Found clip: {media_id}")
                            self.processed_ids.add(item_id)
                            return media_id
                    
                    # Log what we found for debugging
                    else:
                        available_keys = [k for k, v in item.items() if v is not None]
                        logger.info(f"Item {item_id} has keys: {available_keys}")
            
            logger.info("🤷 No new reels found in DMs")
            return None
                
        except Exception as e:
            logger.error(f"Error parsing API response: {e}")
            return None

    def download_reel(self, media_id):
        """Download reel using media ID with error handling"""
        try:
            logger.info(f"📥 Downloading reel {media_id}")
            
            # Get media info first
            media_info = self.cl.media_info(media_id)
            if not media_info:
                logger.error("❌ Could not get media info")
                return None
                
            # Check if it's a video
            if not media_info.is_video:
                logger.error("❌ Media is not a video")
                return None
                
            # Download the video
            reel_path = self.cl.video_download(media_id, folder=DOWNLOADS_DIR)
            if reel_path and Path(reel_path).exists():
                logger.info(f"✅ Downloaded to {reel_path}")
                return reel_path
            else:
                logger.error("❌ Download failed - file doesn't exist")
                return None
                
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            return None

    def upload_reel(self, video_path, caption=""):
        """Upload reel to your account with error handling"""
        try:
            logger.info("🚀 Uploading reel...")
            
            # Add a random delay before uploading
            self.random_delay(5, 15)
            
            # Upload the reel
            result = self.cl.clip_upload(
                video_path, 
                caption=caption,
                # Additional parameters to mimic human behavior
                extra_data={
                    "share_to_feed": True,
                    "like_and_view_counts_disabled": False,
                    "disable_comments": False,
                }
            )
            
            if result:
                logger.info("✅ Reel uploaded successfully!")
                return True
            else:
                logger.error("❌ Upload failed - no result returned")
                return False
                
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            return False

    def run(self):
        """Main execution method"""
        if not self.login():
            logger.error("❌ Cannot proceed without login")
            return

        # Add initial delay
        self.random_delay(2, 5)
        
        # Try to find a reel in DMs
        media_id = self.get_reel_from_dms()
        
        if media_id:
            # Download the reel
            reel_path = self.download_reel(media_id)
            if reel_path:
                # Upload the reel
                if self.upload_reel(reel_path, "Check out this reel! 🔥"):
                    logger.info("✅ Successfully processed reel!")
                else:
                    logger.error("❌ Failed to upload reel")
                
                # Clean up downloaded file
                try:
                    os.remove(reel_path)
                    logger.info("🧹 Cleaned up downloaded file")
                except Exception as e:
                    logger.error(f"❌ Failed to clean up file: {e}")
            else:
                logger.error("❌ Failed to download reel")
        else:
            logger.info("🤷 No new reels found in DMs")
        
        # Save processed IDs
        self.save_processed_ids()
        logger.info("🏁 Mission complete.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

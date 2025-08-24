#!/usr/bin/env python3
"""
Instagram Repost Bot - Enhanced Clip Handling
"""

import os
import json
import time
import random
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

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

    def get_direct_messages(self):
        """Get direct messages with detailed logging"""
        logger.info("📨 Fetching direct messages...")
        
        params = {
            "visual_message_return_type": "unseen",
            "thread_message_limit": 20,
            "persistentBadging": "true",
            "limit": 40,
            "is_prefetching": "false"
        }
        
        response = self.make_api_request("direct_v2/inbox/", params)
        if not response:
            logger.error("❌ Failed to fetch direct messages")
            return None
            
        try:
            # Log the full response structure for debugging
            logger.info(f"API Response keys: {list(response.keys())}")
            
            if 'inbox' in response:
                inbox = response['inbox']
                logger.info(f"Inbox keys: {list(inbox.keys())}")
                
                threads = inbox.get('threads', [])
                logger.info(f"Found {len(threads)} threads")
                
                # Log each thread for debugging
                for i, thread in enumerate(threads):
                    thread_id = thread.get('thread_id', 'unknown')
                    items = thread.get('items', [])
                    logger.info(f"Thread {i+1}: ID={thread_id}, Items={len(items)}")
                    
                    # Log each item in the thread
                    for j, item in enumerate(items):
                        item_id = item.get('item_id', 'unknown')
                        item_type = item.get('item_type', 'unknown')
                        user_id = item.get('user_id', 'unknown')
                        logger.info(f"  Item {j+1}: ID={item_id}, Type={item_type}, User={user_id}")
                        
                        # Log all keys in the item for debugging
                        item_keys = [k for k, v in item.items() if v is not None]
                        logger.info(f"    Item keys: {item_keys}")
                        
                        # For clip items, log the clip structure
                        if 'clip' in item and item['clip']:
                            clip_data = item['clip']
                            logger.info(f"    📹 Clip keys: {list(clip_data.keys())}")
                            if 'media' in clip_data and clip_data['media']:
                                media_data = clip_data['media']
                                logger.info(f"    📹 Media keys: {list(media_data.keys())}")
                                media_id = media_data.get('id')
                                logger.info(f"    📹 Media ID: {media_id}")
                
                return threads
            else:
                logger.error("❌ No inbox found in response")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error parsing API response: {e}")
            return None

    def find_reels_in_messages(self, threads):
        """Find reels in message threads"""
        reels = []
        
        if not threads:
            return reels
            
        for thread in threads:
            thread_id = thread.get('thread_id', 'unknown')
            items = thread.get('items', [])
            
            for item in items:
                item_id = item.get('item_id')
                if not item_id or item_id in self.processed_ids:
                    continue
                    
                # Check for reel share
                if 'reel_share' in item and item['reel_share']:
                    reel_data = item['reel_share']
                    media = reel_data.get('media', {})
                    media_id = media.get('id')
                    
                    if media_id:
                        logger.info(f"🎯 Found reel share: {media_id}")
                        reels.append({
                            'item_id': item_id,
                            'media_id': media_id,
                            'media_type': 2,  # Video
                            'type': 'reel_share'
                        })
                
                # Check for media share (might be a reel)
                elif 'media_share' in item and item['media_share']:
                    media_data = item['media_share']
                    media_id = media_data.get('id')
                    media_type = media_data.get('media_type')
                    
                    if media_id and media_type == 2:  # Video type
                        logger.info(f"🎯 Found media share (video): {media_id}")
                        reels.append({
                            'item_id': item_id,
                            'media_id': media_id,
                            'media_type': 2,
                            'type': 'media_share'
                        })
                
                # Check for clip shares - this is the key fix
                elif 'clip' in item and item['clip']:
                    clip_data = item['clip']
                    
                    # Extract media ID from clip - different possible locations
                    media_id = None
                    
                    # Try direct ID in clip
                    if 'id' in clip_data:
                        media_id = clip_data['id']
                    
                    # Try media object within clip
                    elif 'media' in clip_data and clip_data['media']:
                        media_obj = clip_data['media']
                        if 'id' in media_obj:
                            media_id = media_obj['id']
                    
                    # Try PK field
                    elif 'pk' in clip_data:
                        media_id = clip_data['pk']
                    
                    if media_id:
                        logger.info(f"🎯 Found clip: {media_id}")
                        reels.append({
                            'item_id': item_id,
                            'media_id': media_id,
                            'media_type': 2,
                            'type': 'clip'
                        })
                    else:
                        logger.info(f"❌ Clip found but no media ID: {clip_data}")
        
        return reels

    def download_media(self, media_id, media_type):
        """Download media using media ID"""
        try:
            logger.info(f"📥 Downloading media {media_id} (type: {media_type})")
            
            if media_type == 2:  # Video/Reel
                return self.cl.video_download(media_id, folder=DOWNLOADS_DIR)
            elif media_type == 1:  # Photo
                return self.cl.photo_download(media_id, folder=DOWNLOADS_DIR)
            else:
                logger.error(f"❌ Unsupported media type: {media_type}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            return None

    def upload_reel(self, video_path, caption=""):
        """Upload reel to your account"""
        try:
            logger.info("🚀 Uploading reel...")
            
            # Add a random delay before uploading
            self.random_delay(5, 15)
            
            # Upload the reel
            result = self.cl.clip_upload(
                video_path, 
                caption=caption,
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
        
        # Get direct messages
        threads = self.get_direct_messages()
        
        if not threads:
            logger.info("🤷 No threads found in DMs")
            self.save_processed_ids()
            return
            
        # Find reels in messages
        reels = self.find_reels_in_messages(threads)
        
        if not reels:
            logger.info("🤷 No reels found in DMs")
            self.save_processed_ids()
            return
            
        logger.info(f"🎯 Found {len(reels)} reels to process")
        
        # Process each reel
        processed_count = 0
        for reel in reels:
            if processed_count >= MAX_REPOSTS_PER_RUN:
                logger.info(f"⏹️ Reached max repost limit of {MAX_REPOSTS_PER_RUN}")
                break
                
            # Download the reel
            reel_path = self.download_media(reel['media_id'], reel['media_type'])
            if not reel_path:
                logger.error(f"❌ Failed to download reel {reel['media_id']}")
                continue
                
            # Upload the reel
            if self.upload_reel(reel_path, "Check out this reel! 🔥"):
                logger.info(f"✅ Successfully processed reel {reel['media_id']}")
                self.processed_ids.add(reel['item_id'])
                processed_count += 1
            else:
                logger.error(f"❌ Failed to upload reel {reel['media_id']}")
            
            # Clean up downloaded file
            try:
                os.remove(reel_path)
                logger.info("🧹 Cleaned up downloaded file")
            except Exception as e:
                logger.error(f"❌ Failed to clean up file: {e}")
                
            # Add delay between processing reels
            if processed_count < len(reels) and processed_count < MAX_REPOSTS_PER_RUN:
                self.random_delay(10, 30)
        
        # Save processed IDs
        self.save_processed_ids()
        logger.info(f"🏁 Mission complete. Processed {processed_count} reels.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

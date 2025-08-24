#!/usr/bin/env python3
"""
Instagram Repost Bot - Enhanced Version with Better DM Detection
- Improved DM fetching to get all conversations including older ones
- Better reel detection across different message types
- Enhanced logging for debugging
- Multiple fallback methods for media detection
"""
import os
import json
import time
import random
import logging
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any, Union, List

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
NETWORK_RETRY_COUNT = 3
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
        logger.info("🔐 Attempting login...")
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

    def get_direct_messages_enhanced(self):
        """Enhanced DM fetching with multiple approaches"""
        logger.info("📨 Fetching direct messages with enhanced detection...")
        
        # Method 1: Standard inbox fetch with broader parameters
        try:
            params = {
                "visual_message_return_type": "unseen",
                "thread_message_limit": 50,  # Increased from 20
                "persistentBadging": "true",
                "limit": 100,  # Increased from 40
            }
            response = self.cl.private_request("direct_v2/inbox/", params=params)
            if response and 'inbox' in response:
                threads = response['inbox'].get('threads', [])
                logger.info(f"Method 1: Found {len(threads)} threads")
                if threads:
                    return threads
        except Exception as e:
            logger.warning(f"Method 1 failed: {e}")

        # Method 2: Fetch without visual_message_return_type filter
        try:
            params = {
                "thread_message_limit": 50,
                "limit": 100,
            }
            response = self.cl.private_request("direct_v2/inbox/", params=params)
            if response and 'inbox' in response:
                threads = response['inbox'].get('threads', [])
                logger.info(f"Method 2: Found {len(threads)} threads")
                if threads:
                    return threads
        except Exception as e:
            logger.warning(f"Method 2 failed: {e}")

        # Method 3: Use instagrapi's built-in direct_threads method
        try:
            threads = self.cl.direct_threads(amount=100)
            logger.info(f"Method 3: Found {len(threads)} threads using built-in method")
            if threads:
                # Convert to dict format for consistency
                converted_threads = []
                for thread in threads:
                    thread_data = {
                        'thread_id': thread.id,
                        'items': []
                    }
                    # Get messages for each thread
                    try:
                        messages = self.cl.direct_messages(thread.id, amount=50)
                        for msg in messages:
                            msg_data = {
                                'item_id': msg.id,
                                'timestamp': int(msg.timestamp.timestamp()),
                                'item_type': msg.item_type if hasattr(msg, 'item_type') else None,
                            }
                            
                            # Check for media shares
                            if hasattr(msg, 'media_share') and msg.media_share:
                                msg_data['media_share'] = {
                                    'id': str(msg.media_share.id),
                                    'code': msg.media_share.code,
                                    'media_type': msg.media_share.media_type
                                }
                            
                            # Check for reel shares  
                            if hasattr(msg, 'reel_share') and msg.reel_share:
                                msg_data['reel_share'] = {
                                    'media': {
                                        'id': str(msg.reel_share.id),
                                        'code': msg.reel_share.code if hasattr(msg.reel_share, 'code') else None
                                    }
                                }
                            
                            # Check for clips
                            if hasattr(msg, 'clip') and msg.clip:
                                msg_data['clip'] = {
                                    'clip': {
                                        'pk': str(msg.clip.id),
                                        'code': msg.clip.code if hasattr(msg.clip, 'code') else None
                                    }
                                }
                            
                            # Check for text with Instagram URLs
                            if hasattr(msg, 'text') and msg.text:
                                msg_data['text'] = msg.text
                                if 'instagram.com' in msg.text or 'instagr.am' in msg.text:
                                    msg_data['contains_instagram_url'] = True
                            
                            thread_data['items'].append(msg_data)
                    except Exception as e:
                        logger.warning(f"Failed to get messages for thread {thread.id}: {e}")
                    
                    converted_threads.append(thread_data)
                return converted_threads
        except Exception as e:
            logger.warning(f"Method 3 failed: {e}")

        logger.error("❌ All DM fetching methods failed")
        return None

    def extract_shortcode_from_url(self, url: str) -> Optional[str]:
        """Extract Instagram shortcode from URL"""
        if not url:
            return None
        
        patterns = [
            r'instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)',
            r'instagr\.am/p/([A-Za-z0-9_-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None

    def find_reels_in_messages(self, threads):
        """Enhanced reel detection across all message types"""
        reels = []
        if not threads:
            return reels
        
        logger.info(f"🔍 Scanning {len(threads)} threads for reels...")
        
        total_items_checked = 0
        for thread_idx, thread in enumerate(threads):
            thread_id = thread.get('thread_id', f'thread_{thread_idx}')
            items = thread.get('items', [])
            logger.info(f"📱 Thread {thread_idx + 1}: Checking {len(items)} messages")
            
            for item in items:
                total_items_checked += 1
                item_id = item.get('item_id')
                if not item_id:
                    continue
                
                # Skip if already processed
                if item_id in self.processed_ids:
                    logger.debug(f"⭐ Skipping already processed item: {item_id}")
                    continue

                media_id = None
                shortcode = None
                media_type = 2  # Default to video/reel
                reel_type = None

                # Method 1: Direct media share
                if item.get('media_share'):
                    media = item['media_share']
                    media_id = media.get('id')
                    shortcode = media.get('code')
                    media_type = media.get('media_type', 2)
                    reel_type = 'media_share'
                    logger.info(f"🎯 Found media_share: {shortcode} (ID: {media_id})")

                # Method 2: Reel share
                elif item.get('reel_share', {}).get('media'):
                    media = item['reel_share']['media']
                    media_id = media.get('id')
                    shortcode = media.get('code')
                    reel_type = 'reel_share'
                    logger.info(f"🎯 Found reel_share: {shortcode} (ID: {media_id})")

                # Method 3: Clip share
                elif item.get('clip', {}).get('clip'):
                    media = item['clip']['clip']
                    media_id = media.get('pk')
                    shortcode = media.get('code')
                    reel_type = 'clip'
                    logger.info(f"🎯 Found clip: {shortcode} (ID: {media_id})")

                # Method 4: Text messages with Instagram URLs
                elif item.get('text') or item.get('contains_instagram_url'):
                    text = item.get('text', '')
                    if 'instagram.com' in text or 'instagr.am' in text:
                        shortcode = self.extract_shortcode_from_url(text)
                        if shortcode:
                            reel_type = 'text_url'
                            logger.info(f"🎯 Found Instagram URL in text: {shortcode}")
                            # We'll get the media_id later via shortcode

                # Method 5: Check all string values in item for Instagram URLs
                else:
                    for key, value in item.items():
                        if isinstance(value, str) and ('instagram.com' in value or 'instagr.am' in value):
                            shortcode = self.extract_shortcode_from_url(value)
                            if shortcode:
                                reel_type = f'url_in_{key}'
                                logger.info(f"🎯 Found Instagram URL in {key}: {shortcode}")
                                break

                # If we have either media_id or shortcode, add to reels
                if media_id or shortcode:
                    reel_data = {
                        'item_id': item_id,
                        'media_id': str(media_id) if media_id else None,
                        'shortcode': shortcode,
                        'media_type': media_type,
                        'type': reel_type,
                        'timestamp': item.get('timestamp', 0),
                        'thread_id': thread_id
                    }
                    
                    # If we only have shortcode, try to get media_id
                    if not media_id and shortcode:
                        try:
                            media_info = self.cl.media_info_by_shortcode(shortcode)
                            if media_info:
                                reel_data['media_id'] = str(media_info.id)
                                reel_data['media_type'] = media_info.media_type
                                logger.info(f"✅ Got media_id from shortcode: {media_info.id}")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not get media_id for shortcode {shortcode}: {e}")
                    
                    reels.append(reel_data)
        
        logger.info(f"📊 Checked {total_items_checked} total messages across {len(threads)} threads")
        
        # Sort reels by timestamp (newest first)
        reels.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        # Log summary
        if reels:
            logger.info(f"🎉 Found {len(reels)} reels:")
            for i, reel in enumerate(reels[:5]):  # Show first 5
                logger.info(f"  {i+1}. {reel['shortcode']} ({reel['type']}) - ID: {reel.get('media_id', 'Unknown')}")
            if len(reels) > 5:
                logger.info(f"  ... and {len(reels) - 5} more")
        
        return reels

    def download_media_externally(self, shortcode: str) -> Optional[Path]:
        """Primary download method using an external service."""
        logger.info(f"🌐 Attempting external download for shortcode: {shortcode}")
        insta_url = f"https://www.instagram.com/reel/{shortcode}/"
        api_url = "https://api.cobalt.tools/api/json"
        
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        payload = {"url": insta_url}

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
        media_id = reel_data.get('media_id')
        shortcode = reel_data.get('shortcode')
        
        logger.info(f"🔥 Starting download process for reel {shortcode} (ID: {media_id})")
        self.random_delay(2, 5)

        # Ensure we have a shortcode for external download
        if not shortcode and media_id:
            try:
                media_info = self.cl.media_info(media_id)
                shortcode = media_info.code
                logger.info(f"📝 Got shortcode from media_id: {shortcode}")
            except Exception as e:
                logger.warning(f"⚠️ Could not get shortcode for media_id {media_id}: {e}")

        # --- METHOD 1: EXTERNAL DOWNLOADER (PRIMARY) ---
        if shortcode:
            external_path = self.download_media_externally(shortcode)
            if external_path:
                return external_path

        # --- METHOD 2: INSTAGRAPI (FALLBACK) ---
        if media_id:
            logger.warning(f"⚠️ External download failed. Falling back to internal library method for {media_id}.")
            try:
                return self.cl.clip_download(media_id, folder=DOWNLOADS_DIR)
            except Exception as e:
                logger.error(f"❌ Internal download method failed for {media_id}. Error: {e}")
                # Try video download as final fallback
                try:
                    return self.cl.video_download(media_id, folder=DOWNLOADS_DIR)
                except Exception as e2:
                    logger.error(f"❌ Video download also failed: {e2}")
        
        logger.error(f"❌ All download methods failed for reel")
        return None

    def upload_reel(self, video_path: Path, caption="Reposted 🔥"):
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
            # Enhanced DM fetching
            threads = self.get_direct_messages_enhanced()
            if not threads:
                logger.info("🤷 No threads found in DMs with any method.")
                return
            
            reels = self.find_reels_in_messages(threads)
            if not reels:
                logger.info("🤷 No new, unprocessed reels found in DMs.")
                return
                
            logger.info(f"🎯 Found {len(reels)} new reels to process.")
            
            processed_count = 0
            for i, reel in enumerate(reels):
                if processed_count >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"ℹ️ Reached max repost limit of {MAX_REPOSTS_PER_RUN}.")
                    break
                
                logger.info(f"--- Processing reel {i+1}/{len(reels)} (Shortcode: {reel.get('shortcode', 'Unknown')}) ---")
                
                reel_path = self.download_media(reel)
                if not reel_path:
                    logger.error(f"❌ Failed to download reel {reel.get('shortcode', reel.get('media_id'))}. Skipping.")
                    self.processed_ids.add(reel['item_id'])
                    continue
                
                caption = f"Amazing reel! 🔥\n\n#repost #viral #reel"
                if self.upload_reel(reel_path, caption):
                    logger.info(f"✅ Successfully processed reel {reel.get('shortcode', reel.get('media_id'))}")
                    processed_count += 1
                else:
                    logger.error(f"❌ Failed to upload reel {reel.get('shortcode', reel.get('media_id'))}")
                
                self.processed_ids.add(reel['item_id'])
                
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

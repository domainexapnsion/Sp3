#!/usr/bin/env python3
"""
Instagram Repost Bot - Back to v1 Detection + Reliable Download
Uses v1's proven reel detection method with multiple download fallbacks
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

try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests
    import yt_dlp
except ImportError:
    os.system(f"{sys.executable} -m pip install -q instagrapi requests yt-dlp")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests
    import yt_dlp

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
        delay = random.uniform(min_seconds, max_seconds)
        logger.info(f"😴 Random delay of {delay:.2f} seconds")
        time.sleep(delay)
        return delay

    def rotate_user_agent(self):
        new_agent = random.choice(USER_AGENTS)
        self.cl.set_user_agent(new_agent)
        logger.info(f"🔄 Rotated user agent to: {new_agent}")

    def login(self):
        logger.info("🔐 Attempting login...")
        
        for attempt in range(3):
            try:
                if SESSION_FILE.exists():
                    self.cl.load_settings(SESSION_FILE)
                    # Verify session is still valid
                    try:
                        self.cl.account_info()
                        logger.info("✅ Session is valid.")
                        return True
                    except Exception:
                        logger.info("Session expired, attempting fresh login...")
                        SESSION_FILE.unlink()  # Delete expired session
                
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
        """Get direct messages with detailed logging - V1 METHOD"""
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
            if 'inbox' in response:
                inbox = response['inbox']
                threads = inbox.get('threads', [])
                logger.info(f"Found {len(threads)} threads")
                
                # DEBUG: Log raw thread structure
                if threads:
                    logger.info(f"🔍 Sample thread structure:")
                    sample_thread = threads[0]
                    logger.info(f"Thread keys: {list(sample_thread.keys())}")
                    if 'items' in sample_thread and sample_thread['items']:
                        sample_item = sample_thread['items'][0]
                        logger.info(f"Sample item keys: {list(sample_item.keys())}")
                
                return threads
            else:
                logger.error("❌ No inbox found in response")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error parsing API response: {e}")
            return None

    def extract_shortcode_from_url(self, url: str) -> Optional[str]:
        """Extract Instagram shortcode from URL"""
        if not url:
            return None
        
        # Match Instagram URL patterns
        patterns = [
            r'instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)',
            r'instagr\.am/p/([A-Za-z0-9_-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None

    def shortcode_to_media_id(self, shortcode: str) -> Optional[str]:
        """Convert Instagram shortcode to media ID"""
        try:
            media_info = self.cl.media_info_by_shortcode(shortcode)
            if media_info:
                return str(media_info.id)
        except Exception as e:
            logger.warning(f"Failed to convert shortcode {shortcode}: {e}")
        return None

    def extract_media_id_from_clip(self, clip_data: Dict) -> Optional[str]:
        """Extract media ID from clip data - V1 METHOD"""
        logger.info(f"🔍 Extracting media ID from clip data...")
        
        # Method 1: Look for 'id' field in clip data
        if 'id' in clip_data:
            media_id = str(clip_data['id']).split('_')[0]  # Remove user ID part
            logger.info(f"✅ Found media ID (clip.id): {media_id}")
            return media_id
        
        # Method 2: Look for 'pk' field
        if 'pk' in clip_data:
            media_id = str(clip_data['pk'])
            logger.info(f"✅ Found media ID (clip.pk): {media_id}")
            return media_id
        
        # Method 3: Look for 'code' field (shortcode)
        if 'code' in clip_data:
            shortcode = clip_data['code']
            media_id = self.shortcode_to_media_id(shortcode)
            if media_id:
                logger.info(f"✅ Found media ID from shortcode {shortcode}: {media_id}")
                return media_id
        
        # Method 4: Look for nested media object
        if 'clip' in clip_data and isinstance(clip_data['clip'], dict):
            nested_clip = clip_data['clip']
            
            # Check nested clip for ID fields
            for id_field in ['id', 'pk', 'media_id', 'fbid']:
                if id_field in nested_clip:
                    media_id = str(nested_clip[id_field]).split('_')[0]
                    logger.info(f"✅ Found media ID (nested clip.{id_field}): {media_id}")
                    return media_id
        
        logger.warning("❌ Could not extract media ID from clip data")
        return None

    def find_reels_in_messages(self, threads):
        """Find reels in message threads - V1 METHOD"""
        reels = []
        
        if not threads:
            return reels
            
        for thread in threads:
            thread_id = thread.get('thread_id', 'unknown')
            items = thread.get('items', [])
            
            for item in items:
                item_id = item.get('item_id')
                if not item_id:
                    continue
                    
                # Skip if already processed
                if item_id in self.processed_ids:
                    logger.info(f"⭐️ Skipping already processed item: {item_id}")
                    continue
                
                # Check for different types of reel shares
                media_id = None
                reel_type = None
                
                # Method 1: Check for reel share
                if 'reel_share' in item and item['reel_share']:
                    reel_data = item['reel_share']
                    media = reel_data.get('media', {})
                    media_id = media.get('id')
                    reel_type = 'reel_share'
                    
                    if media_id:
                        logger.info(f"🎯 Found reel share: {media_id}")
                
                # Method 2: Check for media share (might be a reel)
                elif 'media_share' in item and item['media_share']:
                    media_data = item['media_share']
                    media_id = media_data.get('id')
                    media_type = media_data.get('media_type')
                    reel_type = 'media_share'
                    
                    if media_id and media_type == 2:  # Video type
                        logger.info(f"🎯 Found media share (video): {media_id}")
                
                # Method 3: Check for clip shares - V1 DETECTION
                elif 'clip' in item and item['clip']:
                    clip_data = item['clip']
                    reel_type = 'clip'
                    
                    # Use V1 media ID extraction
                    media_id = self.extract_media_id_from_clip(clip_data)
                    
                    if media_id:
                        logger.info(f"🎯 Found clip with media ID: {media_id}")
                
                # If we found a media ID, add to reels list
                if media_id and reel_type:
                    reels.append({
                        'item_id': item_id,
                        'media_id': str(media_id),
                        'media_type': 2,  # Assume video for clips
                        'type': reel_type,
                        'timestamp': item.get('timestamp', 0)
                    })
                    logger.info(f"✅ Added reel: {media_id} (type: {reel_type})")
        
        # Sort reels by timestamp (newest first)
        reels.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        return reels

    def download_with_yt_dlp(self, media_id: str) -> Optional[Path]:
        """Download using yt-dlp as primary method"""
        try:
            logger.info(f"📥 Trying yt-dlp download for media ID: {media_id}")
            
            # Try to get shortcode first
            shortcode = None
            try:
                media_info = self.cl.media_info(media_id)
                shortcode = media_info.code
                logger.info(f"📝 Got shortcode: {shortcode}")
            except:
                logger.warning("Could not get shortcode, will try with media_id")
            
            # Build Instagram URL
            if shortcode:
                url = f"https://www.instagram.com/reel/{shortcode}/"
            else:
                url = f"https://www.instagram.com/p/{media_id}/"
            
            # yt-dlp options
            ydl_opts = {
                'outtmpl': str(DOWNLOADS_DIR / f'{media_id}.%(ext)s'),
                'format': 'best[ext=mp4]/best',
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file
            for file in DOWNLOADS_DIR.glob(f'{media_id}.*'):
                logger.info(f"✅ yt-dlp download successful: {file}")
                return file
                
        except Exception as e:
            logger.warning(f"⚠️ yt-dlp download failed: {e}")
        
        return None

    def download_with_cobalt(self, media_id: str) -> Optional[Path]:
        """Download using cobalt.tools API"""
        try:
            logger.info(f"🌐 Trying cobalt.tools download for media ID: {media_id}")
            
            # Try to get shortcode first
            shortcode = None
            try:
                media_info = self.cl.media_info(media_id)
                shortcode = media_info.code
            except:
                pass
            
            if not shortcode:
                logger.warning("No shortcode available for cobalt download")
                return None
            
            url = f"https://www.instagram.com/reel/{shortcode}/"
            api_url = "https://api.cobalt.tools/api/json"
            
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            payload = {"url": url}
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") == "stream":
                video_url = data.get("url")
                if video_url:
                    video_response = requests.get(video_url, stream=True, timeout=60)
                    video_response.raise_for_status()
                    
                    file_path = DOWNLOADS_DIR / f"{media_id}.mp4"
                    with open(file_path, "wb") as f:
                        for chunk in video_response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    logger.info(f"✅ Cobalt download successful: {file_path}")
                    return file_path
            
        except Exception as e:
            logger.warning(f"⚠️ Cobalt download failed: {e}")
        
        return None

    def download_with_instagrapi(self, media_id: str) -> Optional[Path]:
        """Download using instagrapi as fallback"""
        try:
            logger.info(f"📱 Trying instagrapi download for media ID: {media_id}")
            
            # Try clip download first
            try:
                result = self.cl.clip_download(media_id, folder=DOWNLOADS_DIR)
                if result:
                    logger.info(f"✅ Instagrapi clip download successful: {result}")
                    return result
            except:
                pass
            
            # Try video download
            try:
                result = self.cl.video_download(media_id, folder=DOWNLOADS_DIR)
                if result:
                    logger.info(f"✅ Instagrapi video download successful: {result}")
                    return result
            except:
                pass
            
            # Try with integer ID
            try:
                result = self.cl.clip_download(int(media_id), folder=DOWNLOADS_DIR)
                if result:
                    logger.info(f"✅ Instagrapi int download successful: {result}")
                    return result
            except:
                pass
                
        except Exception as e:
            logger.warning(f"⚠️ Instagrapi download failed: {e}")
        
        return None

    def download_media(self, media_id, media_type):
        """Download media using multiple reliable methods"""
        logger.info(f"🔥 Attempting to download media {media_id} (type: {media_type})")
        
        # Add delay before download
        self.random_delay(2, 5)
        
        # Method 1: yt-dlp (most reliable)
        result = self.download_with_yt_dlp(media_id)
        if result:
            return result
        
        # Method 2: Cobalt.tools API
        result = self.download_with_cobalt(media_id)
        if result:
            return result
        
        # Method 3: Instagrapi fallback
        result = self.download_with_instagrapi(media_id)
        if result:
            return result
        
        logger.error(f"❌ All download methods failed for {media_id}")
        return None

    def upload_reel(self, video_path, caption="Reposted 🔥"):
        """Upload reel to your account with better error handling"""
        try:
            logger.info(f"🚀 Uploading reel from {video_path}")
            
            # Verify file exists and has content
            if not os.path.exists(video_path):
                logger.error(f"❌ Video file not found: {video_path}")
                return False
            
            file_size = os.path.getsize(video_path)
            if file_size == 0:
                logger.error(f"❌ Video file is empty: {video_path}")
                return False
            
            logger.info(f"📁 Video file size: {file_size} bytes")
            
            # Add a random delay before uploading
            self.random_delay(5, 15)
            
            # Try uploading as a clip first
            try:
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
                    logger.info(f"✅ Reel uploaded successfully! Media ID: {result.id}")
                    return True
                
            except Exception as e:
                logger.warning(f"⚠️ Clip upload failed: {e}")
                
                # Fallback to video upload
                try:
                    result = self.cl.video_upload(
                        video_path,
                        caption=caption
                    )
                    
                    if result:
                        logger.info(f"✅ Video uploaded successfully! Media ID: {result.id}")
                        return True
                        
                except Exception as e2:
                    logger.error(f"❌ Video upload also failed: {e2}")
            
            logger.error("❌ All upload methods failed")
            return False
            
        except Exception as e:
            logger.error(f"❌ Critical upload error: {e}")
            return False

    def run(self):
        """Main execution method"""
        logger.info("🚀 Starting Instagram Repost Bot...")
        
        if not self.login():
            logger.error("❌ Cannot proceed without login")
            return

        # Add initial delay
        self.random_delay(2, 5)
        
        try:
            # Get direct messages using V1 method
            threads = self.get_direct_messages()
            
            if not threads:
                logger.info("🤷 No threads found in DMs")
                self.save_processed_ids()
                return
                
            # Find reels in messages using V1 method
            reels = self.find_reels_in_messages(threads)
            
            if not reels:
                logger.info("🤷 No reels found in DMs")
                self.save_processed_ids()
                return
                
            logger.info(f"🎯 Found {len(reels)} reels to process")
            
            # Process each reel
            processed_count = 0
            for i, reel in enumerate(reels):
                if processed_count >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"ℹ️ Reached max repost limit of {MAX_REPOSTS_PER_RUN}")
                    break
                    
                logger.info(f"🔄 Processing reel {i+1}/{len(reels)}: {reel['media_id']}")
                
                # Download the reel
                reel_path = self.download_media(reel['media_id'], reel['media_type'])
                if not reel_path:
                    logger.error(f"❌ Failed to download reel {reel['media_id']}")
                    # Mark as processed to avoid retrying
                    self.processed_ids.add(reel['item_id'])
                    continue
                    
                # Upload the reel
                caption = f"Amazing reel! 🔥\n\n#repost #viral #reel"
                if self.upload_reel(reel_path, caption):
                    logger.info(f"✅ Successfully processed reel {reel['media_id']}")
                    processed_count += 1
                else:
                    logger.error(f"❌ Failed to upload reel {reel['media_id']}")
                
                # Mark as processed
                self.processed_ids.add(reel['item_id'])
                
                # Clean up downloaded file
                try:
                    os.remove(reel_path)
                    logger.info(f"🧹 Cleaned up file: {reel_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to clean up: {e}")
                
                # Add delay between processing
                if i < len(reels) - 1:
                    self.random_delay(10, 30)
            
            logger.info(f"🏁 Completed! Processed {processed_count}/{len(reels)} reels.")
            
        except Exception as e:
            logger.error(f"❌ Critical error in main execution: {e}")
            
        finally:
            self.save_processed_ids()
            logger.info("💾 Processed IDs saved.")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

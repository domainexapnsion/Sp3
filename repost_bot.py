#!/usr/bin/env python3
"""
Instagram Repost Bot - Fixed Version with Improved Media ID Extraction
"""
import os
import json
import time
import random
import logging
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install -q instagrapi requests")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, MediaNotFound
    import requests

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
            if 'inbox' in response:
                inbox = response['inbox']
                threads = inbox.get('threads', [])
                logger.info(f"Found {len(threads)} threads")
                
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
        """Extract media ID from clip data with comprehensive fallback methods"""
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
        
        # Method 5: Look for any URL that might contain the media
        url_fields = ['permalink', 'url', 'video_url', 'thumbnail_url']
        for url_field in url_fields:
            if url_field in clip_data and clip_data[url_field]:
                url = clip_data[url_field]
                shortcode = self.extract_shortcode_from_url(url)
                if shortcode:
                    media_id = self.shortcode_to_media_id(shortcode)
                    if media_id:
                        logger.info(f"✅ Found media ID from URL {url_field}: {media_id}")
                        return media_id
        
        # Method 6: Look for FBID and try to use it directly
        if 'fbid' in clip_data:
            fbid = str(clip_data['fbid'])
            logger.info(f"🔍 Trying FBID as media ID: {fbid}")
            return fbid
        
        # Method 7: Look for any field that looks like an ID
        for key, value in clip_data.items():
            if ('id' in key.lower() or 'pk' in key.lower()) and isinstance(value, (str, int)):
                media_id = str(value).split('_')[0]
                logger.info(f"✅ Found potential media ID ({key}): {media_id}")
                return media_id
        
        logger.warning("❌ Could not extract media ID from clip data")
        return None

    def get_media_info_by_any_id(self, media_id: Union[str, int]) -> Optional[Any]:
        """Try to get media info using various ID formats"""
        logger.info(f"🔍 Trying to get media info for ID: {media_id}")
        
        # Convert to string for processing
        media_id_str = str(media_id)
        
        # Method 1: Try as-is
        try:
            return self.cl.media_info(media_id_str)
        except Exception as e:
            logger.debug(f"Failed with original ID: {e}")
        
        # Method 2: Try as integer
        if media_id_str.isdigit():
            try:
                return self.cl.media_info(int(media_id_str))
            except Exception as e:
                logger.debug(f"Failed with integer ID: {e}")
        
        # Method 3: If it's a compound ID (contains underscore), try just the first part
        if '_' in media_id_str:
            try:
                first_part = media_id_str.split('_')[0]
                return self.cl.media_info(first_part)
            except Exception as e:
                logger.debug(f"Failed with first part {first_part}: {e}")
        
        # Method 4: Try with FBID conversion (if short ID)
        if len(media_id_str) < 15:  # Likely an FBID
            try:
                # Sometimes FBID needs to be used differently
                return self.cl.media_info(f"17841{media_id_str}")
            except Exception as e:
                logger.debug(f"Failed with FBID conversion: {e}")
        
        logger.warning(f"❌ Could not get media info for ID: {media_id}")
        return None

    def find_reels_in_messages(self, threads):
        """Find reels in message threads with improved clip detection"""
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
                    logger.info(f"⏭️ Skipping already processed item: {item_id}")
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
                
                # Method 3: Check for clip shares - IMPROVED DETECTION
                elif 'clip' in item and item['clip']:
                    clip_data = item['clip']
                    reel_type = 'clip'
                    
                    # Use improved media ID extraction
                    media_id = self.extract_media_id_from_clip(clip_data)
                    
                    if media_id:
                        logger.info(f"🎯 Found clip with media ID: {media_id}")
                    else:
                        logger.warning(f"❌ Clip found but no media ID extractable")
                        # Try to find any URL in the clip data
                        for key, value in clip_data.items():
                            if isinstance(value, str) and ('instagram.com' in value or 'instagr.am' in value):
                                shortcode = self.extract_shortcode_from_url(value)
                                if shortcode:
                                    media_id = self.shortcode_to_media_id(shortcode)
                                    if media_id:
                                        logger.info(f"🎯 Found media ID from URL in {key}: {media_id}")
                                        break
                        
                        if not media_id:
                            continue
                
                # Method 4: Check for link items that might be Instagram URLs
                elif 'link' in item and item['link']:
                    link_data = item['link']
                    url = link_data.get('link_url') or link_data.get('url')
                    if url and ('instagram.com' in url or 'instagr.am' in url):
                        shortcode = self.extract_shortcode_from_url(url)
                        if shortcode:
                            media_id = self.shortcode_to_media_id(shortcode)
                            reel_type = 'link'
                            if media_id:
                                logger.info(f"🎯 Found Instagram link: {media_id}")
                
                # If we found a media ID, verify it exists and add to reels list
                if media_id and reel_type:
                    # Try to get media info to verify it exists and get proper details
                    media_info = self.get_media_info_by_any_id(media_id)
                    if media_info:
                        reels.append({
                            'item_id': item_id,
                            'media_id': str(media_info.id),
                            'media_type': media_info.media_type,
                            'type': reel_type,
                            'timestamp': item.get('timestamp', 0),
                            'shortcode': getattr(media_info, 'code', None)
                        })
                        logger.info(f"✅ Verified and added reel: {media_info.id} (type: {reel_type})")
                    else:
                        # If we can't get media info, still try with the original ID
                        reels.append({
                            'item_id': item_id,
                            'media_id': str(media_id),
                            'media_type': 2,  # Assume video for clips
                            'type': reel_type,
                            'timestamp': item.get('timestamp', 0)
                        })
                        logger.info(f"⚠️ Added unverified reel: {media_id} (type: {reel_type})")
        
        # Sort reels by timestamp (newest first)
        reels.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        return reels

    def download_media(self, media_id, media_type):
        """Download media using media ID with comprehensive fallback methods"""
        try:
            logger.info(f"📥 Attempting to download media {media_id} (type: {media_type})")
            
            # Add delay before download
            self.random_delay(2, 5)
            
            # Method 1: Try getting media info first for the most accurate download
            try:
                media_info = self.get_media_info_by_any_id(media_id)
                if media_info:
                    actual_media_id = str(media_info.id)
                    logger.info(f"✅ Got media info for ID: {actual_media_id}")
                    
                    # Use the verified media ID for download
                    if media_info.media_type == 2:  # Video/Reel
                        # Try clip download for reels
                        try:
                            return self.cl.clip_download(actual_media_id, folder=DOWNLOADS_DIR)
                        except Exception:
                            # Fallback to video download
                            try:
                                return self.cl.video_download(actual_media_id, folder=DOWNLOADS_DIR)
                            except Exception:
                                # Try with integer ID
                                return self.cl.clip_download(int(actual_media_id), folder=DOWNLOADS_DIR)
                    
                    elif media_info.media_type == 1:  # Photo
                        return self.cl.photo_download(actual_media_id, folder=DOWNLOADS_DIR)
                    
                    else:  # Unknown type, try as video
                        try:
                            return self.cl.video_download(actual_media_id, folder=DOWNLOADS_DIR)
                        except Exception:
                            return self.cl.clip_download(actual_media_id, folder=DOWNLOADS_DIR)
            
            except Exception as e:
                logger.warning(f"⚠️ Could not get media info for {media_id}: {e}")
            
            # Method 2: Direct download attempts with original ID
            logger.info(f"🔄 Trying direct download methods for {media_id}")
            
            # Try different download methods based on assumed type
            download_methods = []
            if media_type == 2:  # Video
                download_methods = [
                    lambda: self.cl.clip_download(media_id, folder=DOWNLOADS_DIR),
                    lambda: self.cl.video_download(media_id, folder=DOWNLOADS_DIR),
                    lambda: self.cl.clip_download(int(media_id) if str(media_id).isdigit() else media_id, folder=DOWNLOADS_DIR),
                ]
            else:  # Photo or unknown
                download_methods = [
                    lambda: self.cl.photo_download(media_id, folder=DOWNLOADS_DIR),
                    lambda: self.cl.video_download(media_id, folder=DOWNLOADS_DIR),
                    lambda: self.cl.clip_download(media_id, folder=DOWNLOADS_DIR),
                ]
            
            # Try each download method
            for i, method in enumerate(download_methods):
                try:
                    logger.info(f"🔄 Trying download method {i+1}")
                    result = method()
                    if result:
                        logger.info(f"✅ Download successful with method {i+1}")
                        return result
                except Exception as e:
                    logger.debug(f"Download method {i+1} failed: {e}")
            
            # Method 3: Try with ID modifications
            logger.info(f"🔄 Trying modified ID formats")
            
            # If ID contains underscore, try just the first part
            if '_' in str(media_id):
                clean_id = str(media_id).split('_')[0]
                for method_name, method in [('clip', self.cl.clip_download), ('video', self.cl.video_download)]:
                    try:
                        result = method(clean_id, folder=DOWNLOADS_DIR)
                        if result:
                            logger.info(f"✅ Download successful with cleaned ID {clean_id}")
                            return result
                    except Exception as e:
                        logger.debug(f"{method_name} download with cleaned ID failed: {e}")
            
            logger.error(f"❌ All download methods failed for {media_id}")
            return None
                
        except Exception as e:
            logger.error(f"❌ Critical download error for {media_id}: {e}")
            return None

    def upload_reel(self, video_path, caption="Reposted 🔄"):
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
            for i, reel in enumerate(reels):
                if processed_count >= MAX_REPOSTS_PER_RUN:
                    logger.info(f"⏹️ Reached max repost limit of {MAX_REPOSTS_PER_RUN}")
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
                    self.processed_ids.add(reel['item_id'])
                    processed_count += 1
                else:
                    logger.error(f"❌ Failed to upload reel {reel['media_id']}")
                    # Mark as processed to avoid retrying failed uploads
                    self.processed_ids.add(reel['item_id'])
                
                # Clean up downloaded file
                try:
                    if reel_path and os.path.exists(reel_path):
                        os.remove(reel_path)
                        logger.info("🧹 Cleaned up downloaded file")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to clean up file: {e}")
                    
                # Add delay between processing reels
                if i < len(reels) - 1 and processed_count < MAX_REPOSTS_PER_RUN:
                    self.random_delay(15, 45)
            
            logger.info(f"🏁 Mission complete! Successfully processed {processed_count} reels.")
            
        except Exception as e:
            logger.error(f"❌ Critical error in main execution: {e}")
            
        finally:
            # Always save processed IDs
            self.save_processed_ids()
            logger.info("💾 Saved processed IDs")

if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.run()

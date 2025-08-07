#!/usr/bin/env python3
"""
Instagram DM Repost Bot - NUCLEAR FIX
This version completely bypasses Pydantic validation issues by monkey-patching
and using alternative methods that don't trigger the problematic validations.
"""

import os
import json
import time
import random
import logging
import re
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List
import sys

# NUCLEAR FIX #1: Monkey patch Pydantic before importing instagrapi
def patch_pydantic():
    """Monkey patch Pydantic to be more lenient"""
    try:
        import pydantic
        from pydantic import BaseModel
        
        # Store original validate method
        original_validate = BaseModel.model_validate if hasattr(BaseModel, 'model_validate') else BaseModel.parse_obj
        
        def lenient_validate(cls, obj, **kwargs):
            """Lenient validation that skips problematic fields"""
            try:
                return original_validate(obj, **kwargs)
            except Exception as e:
                # If validation fails, try to create a minimal valid object
                if isinstance(obj, dict):
                    # Remove problematic fields
                    cleaned_obj = {}
                    for key, value in obj.items():
                        if key not in ['original_sound_info', 'clips_metadata', 'music_metadata']:
                            cleaned_obj[key] = value
                    try:
                        return original_validate(cleaned_obj, **kwargs)
                    except:
                        # Last resort: create empty object
                        return cls()
                raise e
        
        # Apply the patch
        if hasattr(BaseModel, 'model_validate'):
            BaseModel.model_validate = classmethod(lenient_validate)
        else:
            BaseModel.parse_obj = classmethod(lenient_validate)
            
        logger.info("✅ Pydantic monkey patch applied")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Could not patch Pydantic: {e}")
        return False

# Apply the patch before importing instagrapi
patch_pydantic()

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired, 
    PydanticValidationError,
    LoginRequired,
    MediaNotFound,
    ClientError
)

# ─── Config ────────────────────────────────────────────────────────────────────
USERNAME       = os.getenv("INSTAGRAM_USERNAME")
PASSWORD       = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE   = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR  = Path("downloads")
REEL_REGEX     = re.compile(r"https?://(?:www\.)?instagram\.com/(?:reel|p)/[A-Za-z0-9_\-]+/?")
MAX_REPOSTS    = 5

# Create downloads directory
DOWNLOADS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
logger = logging.getLogger(__name__)

# NUCLEAR FIX #2: Direct API calls bypassing instagrapi models
class DirectInstagramAPI:
    """Direct API calls that bypass problematic Pydantic models"""
    
    def __init__(self, client):
        self.client = client
    
    def get_media_info_raw(self, media_id):
        """Get media info using direct API call"""
        try:
            # Use the underlying HTTP client directly
            data = self.client.private_request(f"media/{media_id}/info/")
            return data.get('items', [{}])[0] if data.get('items') else {}
        except Exception as e:
            logger.warning(f"Direct API call failed: {e}")
            return {}
    
    def extract_media_urls(self, media_data):
        """Extract download URLs from raw media data"""
        urls = {}
        
        try:
            # Video URL
            if media_data.get('video_versions'):
                urls['video'] = media_data['video_versions'][0]['url']
            
            # Image URL
            if media_data.get('image_versions2', {}).get('candidates'):
                urls['image'] = media_data['image_versions2']['candidates'][0]['url']
            
            # Carousel media
            if media_data.get('carousel_media'):
                urls['carousel'] = []
                for item in media_data['carousel_media']:
                    item_urls = self.extract_media_urls(item)
                    urls['carousel'].append(item_urls)
                    
        except Exception as e:
            logger.warning(f"URL extraction failed: {e}")
            
        return urls

# ─── Helper Functions ──────────────────────────────────────────────────────────
def human_delay():
    time.sleep(random.uniform(3, 6))

def load_json(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
    return []

def save_json(path: Path, data):
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Failed to save {path}: {e}")

def download_file(url: str, filename: str) -> Optional[str]:
    """Download file from URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()
        
        filepath = DOWNLOADS_DIR / filename
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"✅ Downloaded: {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"❌ Download failed for {url}: {e}")
        return None

# ─── Main Bot Class ────────────────────────────────────────────────────────────
class NuclearInstagramBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.critical("❌ INSTAGRAM_USERNAME/PASSWORD not set")
            sys.exit(1)
        
        self.cl = Client()
        self.cl.delay_range = [2, 5]
        self.direct_api = DirectInstagramAPI(self.cl)
        self.processed = set(load_json(PROCESSED_FILE))

    def login_safely(self):
        """Login with maximum error handling"""
        # Try session first
        if SESSION_FILE.exists():
            try:
                self.cl.load_settings(str(SESSION_FILE))
                self.cl.account_info()  # Test session
                logger.info("✅ Loaded existing session")
                return True
            except Exception as e:
                logger.warning(f"Session failed: {e}")
                SESSION_FILE.unlink(missing_ok=True)

        # Fresh login
        try:
            logger.info("🔐 Fresh login attempt...")
            self.cl.login(USERNAME, PASSWORD)
            self.cl.dump_settings(str(SESSION_FILE))
            logger.info("✅ Login successful, session saved")
            return True
            
        except ChallengeRequired as e:
            logger.warning("📧 2FA challenge required")
            try:
                code = input("Enter verification code: ").strip()
                self.cl.challenge_resolve(self.cl.last_challenge, code)
                self.cl.dump_settings(str(SESSION_FILE))
                logger.info("✅ 2FA successful")
                return True
            except Exception as e2:
                logger.error(f"❌ 2FA failed: {e2}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            return False

    def extract_media_pk_safe(self, url: str) -> Optional[str]:
        """Extract media PK safely"""
        try:
            return self.cl.media_pk_from_url(url)
        except Exception as e:
            # Manual extraction as fallback
            match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)', url)
            if match:
                shortcode = match.group(1)
                try:
                    return self.cl.media_pk_from_code(shortcode)
                except:
                    pass
            logger.error(f"Could not extract PK from {url}: {e}")
            return None

    def brutal_repost(self, url: str, caption: str = "") -> bool:
        """Nuclear option: bypass all instagrapi models and do everything manually"""
        try:
            logger.info(f"🚀 BRUTAL REPOST: {url}")
            
            # Extract media PK
            media_pk = self.extract_media_pk_safe(url)
            if not media_pk:
                return False

            # Get raw media data
            raw_data = self.direct_api.get_media_info_raw(media_pk)
            if not raw_data:
                logger.error("❌ Could not get raw media data")
                return False

            # Extract URLs
            media_urls = self.direct_api.extract_media_urls(raw_data)
            if not media_urls:
                logger.error("❌ Could not extract media URLs")
                return False

            # Determine media type and download
            downloaded_file = None
            media_type = raw_data.get('media_type', 1)
            
            # Generate filename
            timestamp = int(time.time())
            
            if media_urls.get('video'):
                # It's a video/reel
                filename = f"video_{timestamp}.mp4"
                downloaded_file = download_file(media_urls['video'], filename)
            elif media_urls.get('image'):
                # It's a photo
                filename = f"photo_{timestamp}.jpg"
                downloaded_file = download_file(media_urls['image'], filename)

            if not downloaded_file:
                logger.error("❌ Download failed")
                return False

            # Upload with brutal force
            human_delay()
            
            try:
                # Determine upload method
                if media_urls.get('video') and ('reel' in url.lower() or raw_data.get('product_type') == 'clips'):
                    logger.info("📹 Uploading as reel...")
                    result = self.cl.clip_upload(downloaded_file, caption)
                elif media_urls.get('video'):
                    logger.info("🎥 Uploading as video...")
                    result = self.cl.video_upload(downloaded_file, caption)
                else:
                    logger.info("📸 Uploading as photo...")
                    result = self.cl.photo_upload(downloaded_file, caption)

                if result:
                    logger.info(f"✅ BRUTAL REPOST SUCCESS: {result.pk}")
                    # Cleanup
                    Path(downloaded_file).unlink(missing_ok=True)
                    return True
                else:
                    logger.error("❌ Upload returned no result")
                    return False
                    
            except Exception as upload_error:
                logger.error(f"❌ Upload failed: {upload_error}")
                
                # NUCLEAR FALLBACK: Try all upload methods
                upload_methods = [
                    ('clip_upload', self.cl.clip_upload),
                    ('video_upload', self.cl.video_upload),
                    ('photo_upload', self.cl.photo_upload)
                ]
                
                for method_name, method_func in upload_methods:
                    try:
                        logger.info(f"🔄 Trying {method_name}...")
                        result = method_func(downloaded_file, caption)
                        if result:
                            logger.info(f"✅ SUCCESS with {method_name}: {result.pk}")
                            Path(downloaded_file).unlink(missing_ok=True)
                            return True
                    except Exception as e:
                        logger.warning(f"{method_name} failed: {e}")
                        continue
                
                return False

        except Exception as e:
            logger.error(f"❌ BRUTAL REPOST FAILED: {e}")
            return False

    def process_dms_nuclear(self):
        """Process DMs with nuclear approach"""
        reposts = 0
        
        try:
            # Get threads with minimal validation
            threads_data = self.cl.private_request("direct_v2/inbox/")
            threads = threads_data.get('inbox', {}).get('threads', [])
            
            logger.info(f"📨 Found {len(threads)} threads via direct API")
            
            for thread_data in threads[:10]:  # Limit to 10 threads
                if reposts >= MAX_REPOSTS:
                    break
                    
                thread_id = thread_data.get('thread_id')
                if not thread_id:
                    continue
                
                try:
                    # Get messages directly
                    messages_data = self.cl.private_request(f"direct_v2/threads/{thread_id}/")
                    messages = messages_data.get('thread', {}).get('items', [])
                    
                    for msg_data in messages[:20]:  # Limit messages per thread
                        if reposts >= MAX_REPOSTS:
                            break
                            
                        msg_id = str(msg_data.get('item_id', ''))
                        if msg_id in self.processed:
                            continue
                        
                        # Check for URLs in text
                        text = msg_data.get('text', '')
                        if text:
                            match = REEL_REGEX.search(text)
                            if match:
                                url = match.group(0)
                                logger.info(f"🔗 Found URL: {url}")
                                
                                if self.brutal_repost(url, ""):
                                    reposts += 1
                                    logger.info(f"✅ Repost {reposts}/{MAX_REPOSTS}")
                                
                                self.processed.add(msg_id)
                                human_delay()
                                continue
                        
                        # Check for media shares
                        if msg_data.get('media_share'):
                            media_share = msg_data['media_share']
                            if media_share.get('code'):
                                url = f"https://www.instagram.com/p/{media_share['code']}/"
                                logger.info(f"📱 Found shared media: {url}")
                                
                                if self.brutal_repost(url, text):
                                    reposts += 1
                                    logger.info(f"✅ Repost {reposts}/{MAX_REPOSTS}")
                                
                                self.processed.add(msg_id)
                                human_delay()
                                continue
                        
                        self.processed.add(msg_id)
                        
                except Exception as e:
                    logger.warning(f"⚠️ Thread {thread_id} failed: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ DM processing failed: {e}")
        
        save_json(PROCESSED_FILE, list(self.processed))
        return reposts

    def run(self):
        """Run the nuclear bot"""
        logger.info("🚀 NUCLEAR INSTAGRAM BOT STARTING")
        logger.info("💀 This version bypasses ALL Pydantic validations")
        
        if not self.login_safely():
            logger.error("❌ Login failed - aborting")
            return False
        
        logger.info("✅ Login successful - starting nuclear DM processing")
        reposts = self.process_dms_nuclear()
        
        if reposts > 0:
            logger.info(f"🎉 NUCLEAR SUCCESS: {reposts} reposts completed!")
        else:
            logger.info("📭 No new media found")
        
        return True

if __name__ == "__main__":
    logger.info("🔥 INITIALIZING NUCLEAR INSTAGRAM BOT")
    bot = NuclearInstagramBot()
    bot.run()
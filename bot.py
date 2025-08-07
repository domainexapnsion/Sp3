#!/usr/bin/env python3
"""
Instagram DM Repost Bot - FIXED VERSION
Handles session persistence, manual 2FA fallback, and reposts reels/photos from DMs.
Fixed Pydantic validation errors and added robust error handling.
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

# ─── Helpers ──────────────────────────────────────────────────────────────────
def human_delay():
    time.sleep(random.uniform(2, 5))

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

def download_media_from_url(url: str, filename: str) -> Optional[str]:
    """Download media file from URL"""
    try:
        response = requests.get(url, stream=True, timeout=30)
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

# ─── Bot Class ────────────────────────────────────────────────────────────────
class InstagramBot:
    def __init__(self):
        if not USERNAME or not PASSWORD:
            logger.critical("❌ INSTAGRAM_USERNAME/PASSWORD not set")
            exit(1)
        
        # Initialize client with settings to avoid some validation issues
        self.cl = Client()
        self.cl.delay_range = [1, 3]  # Add delay between requests
        self.processed = set(load_json(PROCESSED_FILE))

    def load_session_from_secret(self):
        """Load session from environment variable"""
        secret = os.environ.get("INSTAGRAM_SESSION_JSON")
        if not secret:
            return False
        try:
            data = json.loads(secret)
            self.cl.set_settings(data)
            # Test the session
            self.cl.account_info()
            logger.info("✅ Loaded session from secret")
            return True
        except Exception as e:
            logger.warning(f"Session from secret failed: {e}")
            return False

    def load_session(self):
        """Load session from file"""
        if not SESSION_FILE.exists():
            return False
        try:
            self.cl.load_settings(str(SESSION_FILE))
            # Test the session
            self.cl.account_info()
            logger.info("✅ Loaded session.json")
            return True
        except Exception as e:
            logger.warning(f"Session load failed: {e}")
            SESSION_FILE.unlink(missing_ok=True)
            return False

    def save_session(self):
        """Save current session to file"""
        try:
            self.cl.dump_settings(str(SESSION_FILE))
            logger.info("💾 session.json saved")
        except Exception as e:
            logger.error(f"❌ Could not save session: {e}")

    def login_with_session(self):
        """Login with session or credentials"""
        # 1) Try GitHub secret session
        if self.load_session_from_secret():
            return True
            
        # 2) Try local session.json
        if self.load_session():
            return True
            
        # 3) Fresh login with manual 2FA fallback
        logger.info("🔐 Attempting credential login…")
        try:
            self.cl.login(USERNAME, PASSWORD)
            self.save_session()
            logger.info("✅ Credential login successful; session saved")
            return True

        except ChallengeRequired:
            logger.warning("📧 Verification required—check your email/SMS for the code.")
            code = input("Enter the 6-digit Instagram verification code: ").strip()
            try:
                self.cl.challenge_resolve(self.cl.last_challenge, code)
                self.save_session()
                logger.info("✅ Logged in after manual verification; session saved")
                return True
            except Exception as e:
                logger.error(f"❌ Challenge resolution failed: {e}")
                return False

        except Exception as e:
            logger.error(f"❌ Credential login failed: {e}")
            return False

    def safe_media_info(self, media_pk: str) -> Optional[Dict]:
        """Get media info with error handling for Pydantic issues"""
        methods = [
            ('media_info', lambda pk: self.cl.media_info(pk)),
            ('media_info_gql', lambda pk: self.cl.media_info_gql(pk)),
        ]
        
        for method_name, method_func in methods:
            try:
                media = method_func(media_pk)
                # Convert to dict to avoid Pydantic validation issues
                if hasattr(media, 'dict'):
                    return media.dict()
                elif hasattr(media, '__dict__'):
                    return {k: v for k, v in vars(media).items() if not k.startswith('_')}
                return media
            except PydanticValidationError as e:
                logger.warning(f"{method_name} Pydantic error: {e}")
                continue
            except Exception as e:
                logger.warning(f"{method_name} failed: {e}")
                continue
        
        return None

    def download_and_repost_media(self, url: str, caption: str = "") -> bool:
        """Download and repost media with robust error handling"""
        try:
            # Extract media PK
            media_pk = self.cl.media_pk_from_url(url)
            if not media_pk:
                logger.error(f"❌ Could not extract media PK from {url}")
                return False

            # Get media info safely
            media_info = self.safe_media_info(media_pk)
            if not media_info:
                logger.error(f"❌ Could not get media info for {media_pk}")
                return False

            # Determine media type and download
            media_type = media_info.get('media_type', 1)
            product_type = media_info.get('product_type', '')
            
            downloaded_file = None
            
            # Try different download methods based on media type
            if product_type == 'clips' or 'reel' in url.lower():
                # It's a reel/clip
                try:
                    downloaded_file = self.cl.clip_download(media_pk, folder=str(DOWNLOADS_DIR))
                    logger.info(f"✅ Downloaded reel: {downloaded_file}")
                except Exception as e:
                    logger.warning(f"Clip download failed, trying video download: {e}")
                    try:
                        downloaded_file = self.cl.video_download(media_pk, folder=str(DOWNLOADS_DIR))
                    except Exception as e2:
                        logger.error(f"Video download also failed: {e2}")
                        return False
            else:
                # It's a photo or regular video
                try:
                    if media_type == 1:  # Photo
                        downloaded_file = self.cl.photo_download(media_pk, folder=str(DOWNLOADS_DIR))
                    else:  # Video
                        downloaded_file = self.cl.video_download(media_pk, folder=str(DOWNLOADS_DIR))
                    logger.info(f"✅ Downloaded media: {downloaded_file}")
                except Exception as e:
                    logger.error(f"Download failed: {e}")
                    return False

            if not downloaded_file or not Path(downloaded_file).exists():
                logger.error("❌ Download failed or file doesn't exist")
                return False

            # Upload the media
            human_delay()  # Delay before upload
            
            if product_type == 'clips' or 'reel' in url.lower():
                # Upload as reel
                result = self.cl.clip_upload(downloaded_file, caption)
            elif media_type == 1:  # Photo
                result = self.cl.photo_upload(downloaded_file, caption)
            else:  # Video
                result = self.cl.video_upload(downloaded_file, caption)

            if result:
                logger.info(f"✅ Successfully reposted: {result.pk}")
                # Clean up downloaded file
                try:
                    Path(downloaded_file).unlink()
                except:
                    pass
                return True
            else:
                logger.error("❌ Upload failed - no result")
                return False

        except Exception as e:
            logger.error(f"❌ Repost failed for {url}: {e}")
            return False

    def process_media_share(self, media_share, caption: str = "") -> bool:
        """Process a media share from DM"""
        try:
            if not media_share:
                return False

            # Try to get the media URL
            media_url = f"https://www.instagram.com/p/{media_share.code}/"
            logger.info(f"📱 Processing shared media: {media_url}")
            
            return self.download_and_repost_media(media_url, caption)

        except Exception as e:
            logger.error(f"❌ Media share processing failed: {e}")
            return False

    def process_dms(self):
        """Process DMs for shared media"""
        reposts = 0
        
        try:
            threads = self.cl.direct_threads(amount=20)
            logger.info(f"📨 Found {len(threads)} DM threads")

            for thread in threads:
                if reposts >= MAX_REPOSTS:
                    break
                
                try:
                    # Get messages from thread
                    messages = self.cl.direct_messages(thread.id, amount=50)
                    
                    for msg in messages:
                        if reposts >= MAX_REPOSTS:
                            break
                            
                        mid = str(msg.id)
                        if mid in self.processed:
                            continue

                        text = getattr(msg, 'text', '') or ""
                        
                        # 1) Check for reel/post links in text
                        match = REEL_REGEX.search(text)
                        if match:
                            url = match.group(0)
                            logger.info(f"🔗 Found URL in message: {url}")
                            
                            if self.download_and_repost_media(url, ""):
                                reposts += 1
                                logger.info(f"✅ Reposted from URL ({reposts}/{MAX_REPOSTS})")
                            
                            self.processed.add(mid)
                            human_delay()
                            continue

                        # 2) Check for media shares
                        if hasattr(msg, 'media_share') and msg.media_share:
                            if self.process_media_share(msg.media_share, text):
                                reposts += 1
                                logger.info(f"✅ Reposted shared media ({reposts}/{MAX_REPOSTS})")
                            
                            self.processed.add(mid)
                            human_delay()
                            continue

                        # Mark as processed even if not reposted
                        self.processed.add(mid)

                except Exception as e:
                    logger.error(f"❌ Error processing thread {thread.id}: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ Error getting DM threads: {e}")

        # Save processed messages
        save_json(PROCESSED_FILE, list(self.processed))
        logger.info(f"🎉 Run complete. Total reposts: {reposts}/{MAX_REPOSTS}")
        return reposts

    def run(self):
        """Main run method"""
        logger.info("🚀 Starting Instagram DM Repost Bot")
        
        if not self.login_with_session():
            logger.error("❌ Login failed; aborting.")
            return False
            
        logger.info("✅ Login successful, processing DMs...")
        reposts = self.process_dms()
        
        if reposts > 0:
            logger.info(f"🎉 Successfully completed {reposts} reposts!")
        else:
            logger.info("📭 No new media found to repost")
            
        return True

if __name__ == "__main__":
    bot = InstagramBot()
    bot.run()
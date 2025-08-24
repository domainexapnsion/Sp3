#!/usr/bin/env python3
"""
Instagram Repost Bot - Fast Version with Multiple Download Methods
Features:
- yt-dlp for reliable downloads
- Cobalt.tools API as backup
- Skip slow media verification
- Direct processing approach
"""

import os
import json
import time
import random
import logging
import sys
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests

try:
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, ClientError
except ImportError:
    print("Installing required packages...")
    os.system(f"{sys.executable} -m pip install -q instagrapi requests")
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired, ClientError

# Configuration
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# File paths
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Fast operational parameters
MAX_REPOSTS_PER_RUN = 3
FAST_MODE = True  # Skip slow verification steps
DOWNLOAD_TIMEOUT = 30  # Max time per download

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('FastRepostBot')

class FastInstagramRepostBot:
    def __init__(self):
        """Initialize with minimal setup for speed"""
        self.cl = Client()
        self.cl.delay_range = [1, 3]  # Faster delays
        self.processed_ids = self._load_processed_ids()
        logger.info(f"🚀 Fast bot initialized. Previously processed {len(self.processed_ids)} messages.")

    def _load_processed_ids(self):
        """Quick load of processed IDs"""
        if PROCESSED_FILE.exists():
            try:
                with PROCESSED_FILE.open('r') as f:
                    return set(json.load(f))
            except:
                return set()
        return set()

    def _save_processed_ids(self):
        """Quick save of processed IDs"""
        try:
            with PROCESSED_FILE.open('w') as f:
                json.dump(list(self.processed_ids), f)
        except Exception as e:
            logger.error(f"Failed to save processed IDs: {e}")

    def quick_login(self):
        """Fast login without extensive verification"""
        logger.info("🔐 Quick login...")
        
        try:
            if SESSION_FILE.exists():
                self.cl.load_settings(SESSION_FILE)
                logger.info("✅ Session loaded")
                return True
        except:
            logger.warning("Session invalid, trying fresh login...")

        if USERNAME and PASSWORD:
            try:
                self.cl.login(USERNAME, PASSWORD)
                self.cl.dump_settings(SESSION_FILE)
                logger.info("✅ Fresh login successful")
                return True
            except Exception as e:
                logger.error(f"❌ Login failed: {e}")
                return False
        
        logger.error("❌ No credentials available")
        return False

    def get_inbox_fast(self):
        """Fast inbox retrieval without retries"""
        try:
            logger.info("📨 Fast inbox fetch...")
            
            response = self.cl.private_request("direct_v2/inbox/", params={
                "visual_message_return_type": "unseen",
                "thread_message_limit": 10,  # Reduced for speed
                "limit": 20,
                "is_prefetching": "false"
            })
            
            if response and "inbox" in response:
                threads = response["inbox"].get("threads", [])
                logger.info(f"📥 Found {len(threads)} threads")
                return threads
            
        except Exception as e:
            logger.error(f"❌ Inbox fetch failed: {e}")
            
        return []

    def extract_media_ids_fast(self, threads):
        """Fast media ID extraction without verification"""
        media_list = []
        
        for thread in threads:
            items = thread.get("items", [])
            
            for item in items:
                item_id = item.get("item_id")
                if not item_id or item_id in self.processed_ids:
                    continue
                
                media_id = None
                media_type = 2  # Assume video for speed
                
                # Quick extraction - no deep verification
                if "clip" in item and item["clip"]:
                    clip_data = item["clip"]
                    media_id = clip_data.get("id") or clip_data.get("pk")
                    
                elif "media_share" in item and item["media_share"]:
                    media_data = item["media_share"]
                    media_id = media_data.get("id") or media_data.get("pk")
                    
                elif "reel_share" in item and item["reel_share"]:
                    reel_data = item["reel_share"]
                    if "media" in reel_data:
                        media_id = reel_data["media"].get("id") or reel_data["media"].get("pk")
                
                if media_id:
                    # Clean media ID
                    media_id = str(media_id).split('_')[0]
                    
                    media_list.append({
                        "item_id": item_id,
                        "media_id": media_id,
                        "media_type": media_type
                    })
                    
                    logger.info(f"⚡ Found media: {media_id}")
                    
                    if len(media_list) >= MAX_REPOSTS_PER_RUN:
                        return media_list
        
        return media_list

    def install_ytdlp(self):
        """Install yt-dlp if not available"""
        try:
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.info("📦 Installing yt-dlp...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], check=True)
                return True
            except subprocess.CalledProcessError:
                logger.error("❌ Failed to install yt-dlp")
                return False

    def download_with_ytdlp(self, media_id):
        """Download using yt-dlp (most reliable method)"""
        try:
            if not self.install_ytdlp():
                return None
            
            # Convert media ID to Instagram URL
            instagram_url = f"https://www.instagram.com/p/{self.media_id_to_shortcode(media_id)}/"
            
            output_path = DOWNLOADS_DIR / f"ytdlp_{media_id}.%(ext)s"
            
            cmd = [
                "yt-dlp",
                "--no-warnings",
                "--timeout", str(DOWNLOAD_TIMEOUT),
                "-o", str(output_path),
                instagram_url
            ]
            
            logger.info(f"🎬 Downloading with yt-dlp: {media_id}")
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
            
            if result.returncode == 0:
                # Find the downloaded file
                for file_path in DOWNLOADS_DIR.glob(f"ytdlp_{media_id}.*"):
                    if file_path.suffix.lower() in ['.mp4', '.mov', '.avi', '.mkv']:
                        logger.info(f"✅ yt-dlp download successful: {file_path.name}")
                        return file_path
            else:
                logger.warning(f"⚠️ yt-dlp failed: {result.stderr}")
                
        except Exception as e:
            logger.warning(f"⚠️ yt-dlp error: {e}")
        
        return None

    def download_with_cobalt(self, media_id):
        """Download using Cobalt.tools API"""
        try:
            instagram_url = f"https://www.instagram.com/p/{self.media_id_to_shortcode(media_id)}/"
            
            logger.info(f"🔧 Trying Cobalt.tools for: {media_id}")
            
            # Cobalt.tools API request
            api_url = "https://api.cobalt.tools/api/json"
            
            payload = {
                "url": instagram_url,
                "vQuality": "720",
                "vCodec": "h264",
                "vFormat": "mp4",
                "isAudioOnly": False,
                "isNoTTWatermark": True,
                "isTTFullAudio": False
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            response = requests.post(api_url, json=payload, headers=headers, timeout=DOWNLOAD_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == "success" or data.get("status") == "redirect":
                    download_url = data.get("url")
                    
                    if download_url:
                        # Download the file
                        file_response = requests.get(download_url, timeout=DOWNLOAD_TIMEOUT)
                        
                        if file_response.status_code == 200:
                            file_path = DOWNLOADS_DIR / f"cobalt_{media_id}.mp4"
                            
                            with open(file_path, 'wb') as f:
                                f.write(file_response.content)
                            
                            logger.info(f"✅ Cobalt download successful: {file_path.name}")
                            return file_path
            
        except Exception as e:
            logger.warning(f"⚠️ Cobalt error: {e}")
        
        return None

    def download_with_instagrapi(self, media_id):
        """Fallback download using instagrapi"""
        try:
            logger.info(f"📱 Trying instagrapi for: {media_id}")
            
            # Quick attempts without extensive verification
            download_methods = [
                lambda: self.cl.clip_download(media_id, folder=DOWNLOADS_DIR),
                lambda: self.cl.video_download(media_id, folder=DOWNLOADS_DIR),
                lambda: self.cl.clip_download(int(media_id), folder=DOWNLOADS_DIR),
            ]
            
            for i, method in enumerate(download_methods):
                try:
                    result = method()
                    if result and result.exists():
                        logger.info(f"✅ Instagrapi method {i+1} successful")
                        return result
                except Exception as e:
                    logger.debug(f"Instagrapi method {i+1} failed: {e}")
                    if i < len(download_methods) - 1:
                        time.sleep(1)  # Brief pause between attempts
            
        except Exception as e:
            logger.warning(f"⚠️ Instagrapi error: {e}")
        
        return None

    def media_id_to_shortcode(self, media_id):
        """Convert media ID to Instagram shortcode (simplified)"""
        # This is a simplified conversion - may not work for all IDs
        try:
            # Basic alphabet for Instagram shortcodes
            alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
            
            # Convert number to base64-like shortcode
            num = int(media_id)
            shortcode = ''
            
            while num > 0:
                shortcode = alphabet[num % 64] + shortcode
                num //= 64
            
            return shortcode if shortcode else media_id
        except:
            return media_id

    def download_media_fast(self, media_id):
        """Fast download with multiple fallback methods"""
        logger.info(f"⚡ Fast download for: {media_id}")
        
        # Method 1: yt-dlp (most reliable)
        file_path = self.download_with_ytdlp(media_id)
        if file_path:
            return file_path
        
        # Method 2: Cobalt.tools API
        file_path = self.download_with_cobalt(media_id)
        if file_path:
            return file_path
        
        # Method 3: Instagrapi fallback
        file_path = self.download_with_instagrapi(media_id)
        if file_path:
            return file_path
        
        logger.error(f"❌ All download methods failed for: {media_id}")
        return None

    def upload_fast(self, file_path, caption=""):
        """Fast upload with minimal verification"""
        try:
            logger.info(f"⚡ Fast upload: {file_path.name}")
            
            if not file_path.exists() or file_path.stat().st_size == 0:
                logger.error("❌ Invalid file")
                return False
            
            # Quick upload attempt
            try:
                result = self.cl.clip_upload(file_path, caption)
                if result:
                    logger.info(f"✅ Upload successful: {result.id}")
                    return True
            except Exception as e:
                logger.warning(f"Clip upload failed: {e}")
                
                # Fallback to video upload
                try:
                    result = self.cl.video_upload(file_path, caption)
                    if result:
                        logger.info(f"✅ Video upload successful: {result.id}")
                        return True
                except Exception as e2:
                    logger.error(f"❌ Both upload methods failed: {e2}")
            
        except Exception as e:
            logger.error(f"❌ Upload error: {e}")
        
        return False

    def run_fast(self):
        """Fast execution with minimal delays"""
        logger.info("🚀 Starting FAST Instagram Repost Bot...")
        
        if not self.quick_login():
            logger.error("❌ Login failed")
            return

        try:
            # Fast inbox fetch
            threads = self.get_inbox_fast()
            if not threads:
                logger.info("📭 No threads found")
                return
            
            # Fast media extraction
            media_list = self.extract_media_ids_fast(threads)
            if not media_list:
                logger.info("🎬 No media found")
                return
            
            logger.info(f"⚡ Processing {len(media_list)} media items...")
            
            success_count = 0
            
            for i, media in enumerate(media_list):
                logger.info(f"⚡ Processing {i+1}/{len(media_list)}: {media['media_id']}")
                
                # Mark as processed immediately
                self.processed_ids.add(media['item_id'])
                
                # Fast download
                file_path = self.download_media_fast(media['media_id'])
                if not file_path:
                    logger.error(f"❌ Download failed: {media['media_id']}")
                    continue
                
                # Fast upload
                caption = f"🔥 Amazing content! 🔄\n\n#repost #viral"
                if self.upload_fast(file_path, caption):
                    success_count += 1
                    logger.info(f"✅ Success {success_count}/{len(media_list)}")
                
                # Cleanup
                try:
                    file_path.unlink()
                except:
                    pass
                
                # Minimal delay between items
                if i < len(media_list) - 1:
                    time.sleep(random.uniform(3, 8))
            
            logger.info(f"🏁 Fast run complete! {success_count}/{len(media_list)} successful")
            
        except Exception as e:
            logger.error(f"❌ Fast run error: {e}")
        
        finally:
            self._save_processed_ids()

if __name__ == "__main__":
    bot = FastInstagramRepostBot()
    bot.run_fast()

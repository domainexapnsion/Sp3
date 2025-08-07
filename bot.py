import os
import json
import re
import logging
import random
import requests
from time import sleep
from urllib.parse import urlparse

# --- Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Constants ---
PROCESSED_FILE = "processed_messages.json"
REEL_REGEX = re.compile(r"https?://www\.instagram\.com/reel/([A-Za-z0-9_\-]+)/?")
POST_REGEX = re.compile(r"https?://www\.instagram\.com/p/([A-Za-z0-9_\-]+)/?")

# --- Utils ---
def save_json(data, filename):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Saved {filename}")
    except Exception as e:
        logger.error(f"❌ Failed to save {filename}: {e}")

def load_json(filename):
    try:
        if os.path.exists(filename):
            with open(filename, "r") as f:
                data = json.load(f)
                logger.info(f"📂 Loaded {filename} with {len(data)} items")
                return data
    except Exception as e:
        logger.warning(f"⚠️ Failed to load {filename}: {e}")
    return []

def human_delay():
    delay = random.uniform(10, 25)
    logger.info(f"⏳ Waiting {delay:.1f} seconds...")
    sleep(delay)

# --- Minimal Instagram Client ---
class MinimalInstagramClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Instagram 275.0.0.27.98 Android (29/10; 300dpi; 720x1440; samsung; SM-A505F; a50; exynos9610; en_US; 458229237)',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'X-Instagram-AJAX': '1',
            'X-Requested-With': 'XMLHttpRequest',
        })
        
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")
        self.user_id = None
        self.csrf_token = None
        
        if not self.username or not self.password:
            raise ValueError("Missing Instagram credentials")

    def login(self):
        """Basic login to get session cookies"""
        try:
            logger.info("🔐 Starting login process...")
            
            # Get initial page to get csrf token
            response = self.session.get('https://www.instagram.com/')
            if response.status_code != 200:
                raise Exception(f"Failed to load Instagram homepage: {response.status_code}")
            
            # Extract csrf token
            csrf_match = re.search(r'"csrf_token":"([^"]+)"', response.text)
            if not csrf_match:
                raise Exception("Could not find CSRF token")
            
            self.csrf_token = csrf_match.group(1)
            logger.info(f"🔑 Got CSRF token: {self.csrf_token[:10]}...")
            
            # Prepare login data
            login_data = {
                'username': self.username,
                'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{int(sleep(0) or time.time())}:{self.password}',
                'queryParams': '{}',
                'optIntoOneTap': 'false'
            }
            
            login_headers = {
                'X-CSRFToken': self.csrf_token,
                'Referer': 'https://www.instagram.com/',
            }
            
            # Perform login
            login_response = self.session.post(
                'https://www.instagram.com/accounts/login/ajax/',
                data=login_data,
                headers=login_headers
            )
            
            if login_response.status_code == 200:
                response_data = login_response.json()
                if response_data.get('authenticated'):
                    logger.info("✅ Login successful")
                    self.user_id = response_data.get('userId')
                    return True
                else:
                    logger.error(f"❌ Login failed: {response_data}")
                    return False
            else:
                logger.error(f"❌ Login request failed: {login_response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            return False

    def get_media_info_from_shortcode(self, shortcode):
        """Get basic media info from shortcode"""
        try:
            url = f'https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis'
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                if 'items' in data and len(data['items']) > 0:
                    return data['items'][0]
            
            # Fallback: try different endpoint
            url = f'https://www.instagram.com/api/v1/media/{shortcode}/info/'
            response = self.session.get(url)
            if response.status_code == 200:
                data = response.json()
                return data.get('items', [{}])[0]
                
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Could not get media info for {shortcode}: {e}")
            return None

    def simple_share_to_story(self, media_url, media_type="video"):
        """Share content to story (simpler than reposting)"""
        try:
            if not self.csrf_token:
                raise Exception("Not logged in")
            
            logger.info(f"📱 Attempting to share {media_type} to story")
            
            # This is a simplified version - in reality, Instagram's story sharing
            # requires more complex API calls and media processing
            share_data = {
                'media_url': media_url,
                'media_type': media_type,
            }
            
            headers = {
                'X-CSRFToken': self.csrf_token,
                'Referer': 'https://www.instagram.com/',
            }
            
            # Note: This is a placeholder - actual story sharing requires
            # uploading media first, then creating the story
            logger.info("📊 Story sharing requires media upload (not implemented in this minimal version)")
            return False
            
        except Exception as e:
            logger.error(f"❌ Story sharing failed: {e}")
            return False

# --- Main Bot Class ---
class SimpleInstagramBot:
    def __init__(self):
        self.client = MinimalInstagramClient()
        self.processed = set(load_json(PROCESSED_FILE))
        
    def process_url(self, url):
        """Process a single Instagram URL"""
        try:
            logger.info(f"🔍 Processing URL: {url}")
            
            # Extract shortcode
            reel_match = REEL_REGEX.search(url)
            post_match = POST_REGEX.search(url)
            
            if reel_match:
                shortcode = reel_match.group(1)
                media_type = "reel"
            elif post_match:
                shortcode = post_match.group(1)
                media_type = "post"
            else:
                logger.warning("⚠️ Could not extract shortcode from URL")
                return False
            
            logger.info(f"📱 Extracted shortcode: {shortcode} (type: {media_type})")
            
            # Get media info
            media_info = self.client.get_media_info_from_shortcode(shortcode)
            if not media_info:
                logger.warning("⚠️ Could not get media info")
                return False
            
            logger.info(f"✅ Got media info for {shortcode}")
            
            # For now, just log what we would do
            # In a full implementation, you would:
            # 1. Download the media
            # 2. Re-upload it as your own post
            # 3. Or share it to your story
            
            logger.info(f"📝 Would repost {media_type}: {shortcode}")
            logger.info(f"👤 Original author: {media_info.get('user', {}).get('username', 'unknown')}")
            
            # Simulate successful repost
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing URL {url}: {e}")
            return False

    def run(self):
        """Main run function"""
        try:
            logger.info("🤖 Starting Simple Instagram Bot")
            
            # Login
            if not self.client.login():
                logger.error("❌ Login failed, cannot continue")
                return
            
            # For demo purposes, let's process some sample URLs
            # In reality, you would get these from DMs or another source
            sample_urls = [
                "https://www.instagram.com/reel/sample123/",  # Replace with actual URLs
                "https://www.instagram.com/p/sample456/",
            ]
            
            reposts = 0
            
            for url in sample_urls:
                url_hash = str(hash(url))
                if url_hash in self.processed:
                    logger.info(f"⏭️ Skipping already processed URL: {url}")
                    continue
                
                if self.process_url(url):
                    self.processed.add(url_hash)
                    reposts += 1
                    human_delay()
                else:
                    # Still mark as processed to avoid retrying
                    self.processed.add(url_hash)
                    
            # Save progress
            save_json(list(self.processed), PROCESSED_FILE)
            logger.info(f"✅ Bot run complete. Processed: {reposts} items")
            
        except Exception as e:
            logger.error(f"❌ Fatal error in bot run: {e}")

# --- Alternative: File-based approach ---
def process_urls_from_file():
    """Process URLs from a text file (simpler approach)"""
    try:
        urls_file = "urls_to_process.txt"
        
        # Create sample file if it doesn't exist
        if not os.path.exists(urls_file):
            with open(urls_file, "w") as f:
                f.write("# Add Instagram URLs here, one per line\n")
                f.write("# https://www.instagram.com/reel/example123/\n")
                f.write("# https://www.instagram.com/p/example456/\n")
            logger.info(f"📝 Created sample {urls_file}")
            return
        
        # Read URLs from file
        with open(urls_file, "r") as f:
            lines = f.readlines()
        
        urls = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        
        if not urls:
            logger.info("📭 No URLs found in file")
            return
        
        logger.info(f"📋 Found {len(urls)} URLs to process")
        
        processed = set(load_json(PROCESSED_FILE))
        new_reposts = 0
        
        for url in urls:
            url_hash = str(hash(url))
            if url_hash in processed:
                logger.info(f"⏭️ Skipping: {url}")
                continue
            
            logger.info(f"🔄 Processing: {url}")
            
            # Extract shortcode for logging
            reel_match = REEL_REGEX.search(url)
            post_match = POST_REGEX.search(url)
            
            if reel_match or post_match:
                shortcode = (reel_match or post_match).group(1)
                logger.info(f"📱 Shortcode: {shortcode}")
                
                # In a real implementation, you would:
                # 1. Use a working Instagram library or API
                # 2. Download the media
                # 3. Re-upload it
                
                logger.info("✅ Would repost this content")
                processed.add(url_hash)
                new_reposts += 1
                human_delay()
            else:
                logger.warning(f"⚠️ Invalid URL format: {url}")
                processed.add(url_hash)  # Mark as processed to skip next time
        
        # Save progress
        save_json(list(processed), PROCESSED_FILE)
        logger.info(f"✅ File processing complete. New reposts: {new_reposts}")
        
    except Exception as e:
        logger.error(f"❌ Error processing URLs from file: {e}")

# --- Main ---
if __name__ == "__main__":
    try:
        logger.info("🚀 Starting Instagram Bot")
        
        # Try the simple bot approach
        try:
            bot = SimpleInstagramBot()
            bot.run()
        except Exception as bot_error:
            logger.error(f"❌ Bot approach failed: {bot_error}")
            logger.info("📄 Trying file-based approach instead...")
            process_urls_from_file()
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        exit(1)
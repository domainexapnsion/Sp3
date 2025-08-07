import os
import json
import re
import logging
import random
from time import sleep
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, PleaseWaitFewMinutes
from pydantic_core import ValidationError

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
SESSION_FILE = "session.json"
PROCESSED_FILE = "processed_messages.json"
REEL_REGEX = re.compile(r"https?://www\.instagram\.com/reel/[A-Za-z0-9_\-]+/?")

# --- Utils ---
def save_json(data, filename):
    try:
        with open(filename, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Failed to save {filename}: {e}")

def load_json(filename):
    try:
        if os.path.exists(filename):
            with open(filename, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {filename}: {e}")
    return []

def human_delay():
    delay = random.uniform(8, 20)  # Longer delays to avoid detection
    logger.info(f"Waiting {delay:.1f} seconds...")
    sleep(delay)

# --- Bot Class ---
class InstagramRepostBot:
    def __init__(self):
        self.cl = Client()
        # Configure client settings
        self.cl.set_user_agent("Instagram 275.0.0.27.98 Android (29/10; 300dpi; 720x1440; samsung; SM-A505F; a50; exynos9610; en_US; 458229237)")
        self.cl.set_country_code(1)  # US country code
        self.cl.set_locale("en_US")
        self.cl.set_timezone_offset(-18000)  # EST timezone
        
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")
        
        if not self.username or not self.password:
            logger.error("❌ Instagram credentials not found in environment variables")
            raise ValueError("Missing Instagram credentials")
            
        self.processed = set(load_json(PROCESSED_FILE))
        logger.info(f"📋 Loaded {len(self.processed)} processed messages")

    def login_with_retry(self, max_retries=3):
        """Login with retry mechanism"""
        for attempt in range(max_retries):
            try:
                # Try existing session first
                if os.path.exists(SESSION_FILE) and attempt == 0:
                    try:
                        self.cl.load_settings(SESSION_FILE)
                        # Simple validation
                        self.cl.user_id
                        logger.info("✅ Session restored")
                        return True
                    except Exception as e:
                        logger.warning(f"⚠️ Session invalid: {e}")
                        try:
                            os.remove(SESSION_FILE)
                        except:
                            pass

                # Fresh login
                logger.info(f"🔐 Fresh login attempt {attempt + 1}/{max_retries}")
                self.cl.login(self.username, self.password)
                self.cl.dump_settings(SESSION_FILE)
                logger.info("✅ Login successful")
                return True
                
            except ChallengeRequired as e:
                logger.error(f"❌ Challenge required: {e}")
                return False
                
            except PleaseWaitFewMinutes as e:
                wait_time = 600 + (attempt * 300)  # Long waits for rate limits
                logger.warning(f"⏳ Rate limited. Waiting {wait_time} seconds...")
                sleep(wait_time)
                
            except Exception as e:
                logger.error(f"❌ Login attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    sleep(120)  # 2 minute wait between attempts
        
        return False

    def get_threads_safely(self):
        """Get DM threads with comprehensive error handling"""
        max_retries = 5
        
        for attempt in range(max_retries):
            try:
                logger.info(f"📥 Fetching DM threads (attempt {attempt + 1}/{max_retries})")
                
                # Use a more basic approach to avoid validation errors
                threads = self.cl.direct_threads(amount=20)  # Limit to recent threads
                
                logger.info(f"📬 Successfully retrieved {len(threads)} threads")
                return threads
                
            except ValidationError as e:
                logger.warning(f"⚠️ Validation error (attempt {attempt + 1}): {e}")
                
                # If it's the clips metadata error, try alternative approach
                if "clips_metadata" in str(e) or "original_sound_info" in str(e):
                    logger.info("🔧 Detected clips metadata validation error, trying workaround...")
                    
                    try:
                        # Try to get threads with minimal data
                        response = self.cl.private_request("direct_v2/inbox/")
                        if response and "inbox" in response:
                            threads_data = response["inbox"].get("threads", [])
                            logger.info(f"📬 Retrieved {len(threads_data)} threads via workaround")
                            
                            # Create minimal thread objects
                            threads = []
                            for thread_data in threads_data[:10]:  # Process only first 10
                                try:
                                    # Extract basic thread info
                                    thread = type('Thread', (), {
                                        'thread_id': thread_data.get('thread_id'),
                                        'messages': []
                                    })()
                                    
                                    # Get messages for this thread separately
                                    try:
                                        messages_response = self.cl.private_request(
                                            f"direct_v2/threads/{thread.thread_id}/"
                                        )
                                        if messages_response and "thread" in messages_response:
                                            messages_data = messages_response["thread"].get("items", [])
                                            
                                            for msg_data in messages_data[:5]:  # Only recent messages
                                                try:
                                                    msg = type('Message', (), {
                                                        'id': msg_data.get('item_id'),
                                                        'text': msg_data.get('text', ''),
                                                        'media_share': None
                                                    })()
                                                    
                                                    # Handle media share if present
                                                    if 'media_share' in msg_data and msg_data['media_share']:
                                                        media_data = msg_data['media_share']
                                                        msg.media_share = type('MediaShare', (), {
                                                            'pk': media_data.get('pk'),
                                                            'media_type': media_data.get('media_type', 0),
                                                            'user': type('User', (), {
                                                                'username': media_data.get('user', {}).get('username', '')
                                                            })()
                                                        })()
                                                    
                                                    thread.messages.append(msg)
                                                except Exception as msg_e:
                                                    logger.debug(f"Skipping message due to error: {msg_e}")
                                                    continue
                                    except Exception as msgs_e:
                                        logger.debug(f"Could not get messages for thread: {msgs_e}")
                                    
                                    threads.append(thread)
                                    
                                except Exception as thread_e:
                                    logger.debug(f"Skipping thread due to error: {thread_e}")
                                    continue
                            
                            return threads
                            
                    except Exception as workaround_e:
                        logger.warning(f"⚠️ Workaround failed: {workaround_e}")
                
                # Standard retry logic
                if attempt < max_retries - 1:
                    wait_time = 60 + (attempt * 30)
                    logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                    sleep(wait_time)
                else:
                    logger.error("❌ All attempts to get threads failed")
                    return []
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error getting threads: {e}")
                if attempt < max_retries - 1:
                    sleep(60)
                else:
                    return []
        
        return []

    def simple_repost_by_url(self, url):
        """Simplified reposting method that avoids complex metadata"""
        try:
            logger.info(f"🎯 Attempting simple repost for: {url}")
            
            # Extract shortcode from URL
            shortcode_match = re.search(r'/reel/([A-Za-z0-9_\-]+)', url)
            if not shortcode_match:
                raise Exception("Could not extract shortcode from URL")
            
            shortcode = shortcode_match.group(1)
            logger.info(f"📱 Extracted shortcode: {shortcode}")
            
            # Get media PK from shortcode
            media_pk = self.cl.media_pk_from_code(shortcode)
            logger.info(f"🆔 Media PK: {media_pk}")
            
            # Try different repost methods
            methods = [
                lambda: self.cl.clip_upload_by_url(url, caption=""),
                lambda: self.cl.media_repost(media_pk, ""),
            ]
            
            for i, method in enumerate(methods, 1):
                try:
                    logger.info(f"🔄 Trying repost method {i}")
                    method()
                    logger.info(f"✅ Success with method {i}")
                    return True
                except Exception as method_e:
                    logger.warning(f"⚠️ Method {i} failed: {method_e}")
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Simple repost failed: {e}")
            return False

    def process_dms(self):
        """Main DM processing with error resilience"""
        threads = self.get_threads_safely()
        if not threads:
            logger.error("❌ Could not retrieve any threads")
            return
        
        reposts = 0
        
        for thread_idx, thread in enumerate(threads[:5]):  # Process only first 5 threads
            logger.info(f"🧵 Processing thread {thread_idx + 1}")
            
            if not hasattr(thread, 'messages') or not thread.messages:
                logger.info("📭 Thread has no messages")
                continue
            
            for msg in thread.messages[:3]:  # Only recent messages
                try:
                    msg_id = str(getattr(msg, 'id', f'unknown_{random.randint(1000,9999)}'))
                    
                    if msg_id in self.processed:
                        continue
                    
                    logger.info(f"💬 Processing message: {msg_id}")
                    
                    # Check for reel URL in text
                    text = getattr(msg, 'text', '') or ""
                    if text:
                        reel_match = REEL_REGEX.search(text)
                        if reel_match:
                            url = reel_match.group(0)
                            logger.info(f"🔗 Found reel URL: {url}")
                            
                            if self.simple_repost_by_url(url):
                                self.processed.add(msg_id)
                                reposts += 1
                                human_delay()
                                continue
                    
                    # Check for media share
                    if hasattr(msg, 'media_share') and msg.media_share:
                        logger.info("📤 Found media share")
                        try:
                            media = msg.media_share
                            media_pk = getattr(media, 'pk', None)
                            if media_pk:
                                self.cl.media_repost(media_pk, "")
                                logger.info("✅ Media share reposted")
                                self.processed.add(msg_id)
                                reposts += 1
                                human_delay()
                                continue
                        except Exception as media_e:
                            logger.warning(f"⚠️ Media share repost failed: {media_e}")
                    
                    # Mark as processed even if no action taken
                    self.processed.add(msg_id)
                    
                except Exception as msg_e:
                    logger.error(f"❌ Error processing message: {msg_e}")
                    continue
        
        # Save progress
        save_json(list(self.processed), PROCESSED_FILE)
        logger.info(f"✅ Processing complete. Reposts: {reposts}")

# --- Main ---
if __name__ == "__main__":
    try:
        bot = InstagramRepostBot()
        
        if bot.login_with_retry():
            bot.process_dms()
        else:
            logger.error("❌ Login failed")
            exit(1)
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        exit(1)
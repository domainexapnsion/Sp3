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
    delay = random.uniform(5, 15)  # Random delay between 5-15 seconds
    logger.info(f"Waiting {delay:.1f} seconds...")
    sleep(delay)

# --- Bot Class ---
class InstagramRepostBot:
    def __init__(self):
        self.cl = Client()
        # Set user agent to avoid detection
        self.cl.set_user_agent("Instagram 219.0.0.12.117 Android")
        
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")
        
        if not self.username or not self.password:
            logger.error("❌ Instagram credentials not found in environment variables")
            raise ValueError("Missing Instagram credentials")
            
        self.processed = set(load_json(PROCESSED_FILE))
        logger.info(f"📋 Loaded {len(self.processed)} processed messages")

    def login_with_retry(self, max_retries=3):
        """Login with retry mechanism and better session handling"""
        for attempt in range(max_retries):
            try:
                # Try to load existing session first
                if os.path.exists(SESSION_FILE) and attempt == 0:
                    try:
                        self.cl.load_settings(SESSION_FILE)
                        # Test if session is still valid
                        self.cl.get_timeline_feed()
                        logger.info("✅ Session restored and validated")
                        return True
                    except (LoginRequired, Exception) as e:
                        logger.warning(f"⚠️ Existing session invalid: {e}")
                        # Delete invalid session file
                        try:
                            os.remove(SESSION_FILE)
                        except:
                            pass

                # Fresh login
                logger.info(f"🔐 Attempting fresh login (attempt {attempt + 1}/{max_retries})")
                self.cl.login(self.username, self.password)
                
                # Save session after successful login
                self.cl.dump_settings(SESSION_FILE)
                logger.info("✅ Login successful, session saved")
                return True
                
            except ChallengeRequired as e:
                logger.error(f"❌ Instagram challenge required: {e}")
                logger.error("You may need to verify your account manually")
                return False
                
            except PleaseWaitFewMinutes as e:
                wait_time = 300 + (attempt * 180)  # Increase wait time with each attempt
                logger.warning(f"⏳ Rate limited. Waiting {wait_time} seconds...")
                sleep(wait_time)
                continue
                
            except Exception as e:
                logger.error(f"❌ Login attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 60 + (attempt * 30)
                    logger.info(f"⏳ Waiting {wait_time} seconds before retry...")
                    sleep(wait_time)
                else:
                    logger.error("❌ All login attempts failed")
                    return False
        
        return False

    def get_threads_safely(self, max_retries=3):
        """Get DM threads with error handling and retries"""
        for attempt in range(max_retries):
            try:
                logger.info(f"📥 Fetching DM threads (attempt {attempt + 1}/{max_retries})")
                threads = self.cl.direct_threads()
                logger.info(f"📬 Found {len(threads)} DM threads")
                return threads
                
            except ValidationError as e:
                logger.error(f"❌ ValidationError getting threads: {e}")
                if attempt < max_retries - 1:
                    logger.info("⏳ Waiting 30 seconds before retry...")
                    sleep(30)
                else:
                    logger.error("❌ Failed to get threads after all retries")
                    return []
                    
            except Exception as e:
                logger.error(f"❌ Unexpected error getting threads: {e}")
                if attempt < max_retries - 1:
                    sleep(30)
                else:
                    return []
        
        return []

    def repost_reel_by_url(self, url, msg_id):
        """Repost reel from URL with fallback methods"""
        try:
            # Method 1: Try to extract media PK and repost
            logger.info(f"🎯 Method 1: Extracting media PK from URL: {url}")
            media_pk = self.cl.media_pk_from_url(url)
            logger.info(f"📱 Media PK: {media_pk}")
            
            # Validate media exists and is accessible
            media_info = self.cl.media_info(media_pk)
            if not media_info:
                raise Exception("Media not found or not accessible")
            
            logger.info(f"📋 Media type: {media_info.media_type}, User: {media_info.user.username}")
            
            # Try to repost
            self.cl.media_repost(media_pk, "")
            logger.info("✅ Successfully reposted via media_repost")
            return True
            
        except Exception as e1:
            logger.warning(f"⚠️ Method 1 failed: {e1}")
            
            try:
                # Method 2: Download and re-upload
                logger.info("🎯 Method 2: Download and re-upload")
                media_pk = self.cl.media_pk_from_url(url)
                media_info = self.cl.media_info(media_pk)
                
                if media_info.video_url:
                    # Download video
                    video_path = f"temp_video_{media_pk}.mp4"
                    self.cl.video_download(media_pk, folder=".")
                    
                    # Upload as reel
                    self.cl.clip_upload(video_path, caption="")
                    
                    # Clean up
                    try:
                        os.remove(video_path)
                    except:
                        pass
                        
                    logger.info("✅ Successfully reposted via download/upload")
                    return True
                    
            except Exception as e2:
                logger.warning(f"⚠️ Method 2 failed: {e2}")
                
                try:
                    # Method 3: Simple clip_upload_by_url (last resort)
                    logger.info("🎯 Method 3: Simple upload by URL")
                    self.cl.clip_upload_by_url(url, caption="")
                    logger.info("✅ Successfully reposted via upload_by_url")
                    return True
                    
                except Exception as e3:
                    logger.error(f"❌ All methods failed for URL {url}: {e3}")
                    return False

    def repost_media_share(self, media, text, msg_id):
        """Repost forwarded media with better handling"""
        try:
            media_pk = media.pk
            media_type = getattr(media, "media_type", 0)
            
            logger.info(f"📱 Media PK: {media_pk}, Type: {media_type}")
            
            if media_type == 2:  # Video/Reel
                logger.info("🎬 Reposting video/reel")
                try:
                    self.cl.media_repost(media_pk, "")
                    return True
                except:
                    # Fallback: try clip_repost
                    self.cl.clip_repost(media_pk)
                    return True
                    
            elif media_type == 1:  # Photo
                logger.info("📸 Reposting photo")
                caption = text if text.strip() else ""
                self.cl.photo_repost(media_pk, caption=caption)
                return True
                
            else:
                logger.warning(f"⚠️ Unknown media type: {media_type}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to repost media share: {e}")
            return False

    def process_dms(self):
        """Main DM processing function"""
        threads = self.get_threads_safely()
        if not threads:
            logger.error("❌ No threads to process")
            return
        
        reposts = 0
        processed_this_run = []
        
        for thread_idx, thread in enumerate(threads):
            logger.info(f"🧵 Processing thread {thread_idx + 1}/{len(threads)}")
            
            # Process only recent messages (last 10 to avoid processing too many)
            recent_messages = thread.messages[:10] if thread.messages else []
            
            for msg in recent_messages:
                try:
                    msg_id = str(msg.id)
                    if msg_id in self.processed:
                        continue
                    
                    logger.info(f"💬 Processing message ID: {msg_id}")
                    text = getattr(msg, 'text', '') or ""
                    
                    # Case 1: Reel URL in text
                    reel_match = REEL_REGEX.search(text)
                    if reel_match:
                        url = reel_match.group(0)
                        logger.info(f"🔗 Found reel URL: {url}")
                        
                        if self.repost_reel_by_url(url, msg_id):
                            self.processed.add(msg_id)
                            processed_this_run.append(msg_id)
                            reposts += 1
                            human_delay()
                            continue
                    
                    # Case 2: Forwarded media (media_share)
                    if hasattr(msg, "media_share") and msg.media_share:
                        logger.info("📤 Found media share")
                        
                        if self.repost_media_share(msg.media_share, text, msg_id):
                            self.processed.add(msg_id)
                            processed_this_run.append(msg_id)
                            reposts += 1
                            human_delay()
                            continue
                    
                    # Mark as processed even if we couldn't handle it
                    self.processed.add(msg_id)
                    processed_this_run.append(msg_id)
                    
                except Exception as e:
                    logger.error(f"❌ Error processing message {getattr(msg, 'id', 'unknown')}: {e}")
                    continue
        
        # Save processed messages
        save_json(list(self.processed), PROCESSED_FILE)
        
        logger.info(f"✅ Run complete!")
        logger.info(f"📊 Total reposts: {reposts}")
        logger.info(f"📝 Messages processed this run: {len(processed_this_run)}")
        logger.info(f"💾 Total processed messages: {len(self.processed)}")

# --- Main ---
if __name__ == "__main__":
    try:
        bot = InstagramRepostBot()
        
        if bot.login_with_retry():
            bot.process_dms()
        else:
            logger.error("❌ Failed to login, aborting")
            exit(1)
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        exit(1)
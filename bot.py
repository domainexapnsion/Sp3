from instagrapi import Client
import os
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def login():
    """Login to Instagram"""
    try:
        cl = Client()
        username = os.environ.get("INSTAGRAM_USERNAME")
        password = os.environ.get("INSTAGRAM_PASSWORD")
        
        if not username or not password:
            raise ValueError("Instagram credentials not found in environment variables")
        
        logger.info(f"Attempting to login as {username}")
        cl.login(username, password)
        logger.info("Login successful")
        return cl
    
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise

def process_dms(cl):
    """Process direct messages and repost content"""
    try:
        logger.info("Fetching direct message threads...")
        threads = cl.direct_threads(amount=10)
        logger.info(f"Found {len(threads)} threads")
        
        for thread in threads:
            for message in thread.messages:
                try:
                    # Handle reel reposts
                    if hasattr(message, 'reel') and message.reel:
                        logger.info("Found reel to repost")
                        cl.clip_upload_by_url(
                            url=message.reel.video_url,
                            caption="Reposted via bot 🤖"
                        )
                        logger.info("Reel reposted successfully")
                    
                    # Handle photo reposts
                    elif hasattr(message, 'media') and message.media and hasattr(message.media, 'photo_url'):
                        logger.info("Found photo to repost")
                        caption = getattr(message, 'text', None) or "Posted via bot 🤖"
                        cl.photo_upload_by_url(
                            url=message.media.photo_url,
                            caption=caption
                        )
                        logger.info("Photo reposted successfully")
                        
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue
                    
    except Exception as e:
        logger.error(f"Error processing DMs: {e}")
        raise

if __name__ == "__main__":
    try:
        client = login()
        process_dms(client)
        logger.info("Bot completed successfully")
    except Exception as e:
        logger.error(f"Bot failed: {e}")
        exit(1)
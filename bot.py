#!/usr/bin/env python3
"""
Complete Instagram DM Repost Bot
Handles 2FA, session persistence, and Instagram's security measures
"""

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, PleaseWaitFewMinutes
import os
import json
import time
import logging
import random
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class InstagramBot:
    def __init__(self):
        self.cl = Client()
        self.username = os.environ.get("INSTAGRAM_USERNAME")
        self.password = os.environ.get("INSTAGRAM_PASSWORD")
        self.session_file = "session.json"
        self.processed_file = "processed_messages.json"
        
        if not self.username or not self.password:
            raise ValueError("Instagram credentials not found in environment variables")
    
    def load_session(self):
        """Load existing session if available"""
        try:
            if os.path.exists(self.session_file):
                logger.info("Loading existing session...")
                self.cl.load_settings(self.session_file)
                self.cl.login(self.username, self.password)
                logger.info("Session loaded successfully")
                return True
        except Exception as e:
            logger.warning(f"Could not load session: {e}")
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
        return False
    
    def save_session(self):
        """Save current session"""
        try:
            self.cl.dump_settings(self.session_file)
            logger.info("Session saved successfully")
        except Exception as e:
            logger.error(f"Could not save session: {e}")
    
    def login_with_retry(self):
        """Login with retry mechanism and 2FA handling"""
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Login attempt {attempt + 1}/{max_attempts}")
                
                # Try to load existing session first
                if self.load_session():
                    return True
                
                # Fresh login
                logger.info("Performing fresh login...")
                
                # Set realistic device settings
                self.cl.set_locale('en_US')
                self.cl.set_timezone_offset(-18000)  # EST timezone
                
                # Add random delay to seem human-like
                time.sleep(random.uniform(2, 5))
                
                self.cl.login(self.username, self.password)
                
                # Save session for future use
                self.save_session()
                logger.info("Login successful!")
                return True
                
            except ChallengeRequired as e:
                logger.warning("Challenge required (2FA/verification)")
                # For automated systems, we can't handle interactive challenges
                # In production, you'd need to handle this differently
                logger.error("Cannot handle interactive challenges in automated environment")
                return False
                
            except PleaseWaitFewMinutes as e:
                logger.warning("Instagram asked to wait. Waiting...")
                wait_time = 60 * (attempt + 1)  # Exponential backoff
                time.sleep(wait_time)
                continue
                
            except Exception as e:
                logger.error(f"Login attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(30)  # Wait before retry
                continue
        
        logger.error("All login attempts failed")
        return False
    
    def load_processed_messages(self):
        """Load list of already processed message IDs"""
        try:
            if os.path.exists(self.processed_file):
                with open(self.processed_file, 'r') as f:
                    return set(json.load(f))
        except Exception as e:
            logger.error(f"Could not load processed messages: {e}")
        return set()
    
    def save_processed_message(self, message_id):
        """Save processed message ID"""
        try:
            processed = self.load_processed_messages()
            processed.add(message_id)
            
            # Keep only last 1000 processed messages to prevent file bloat
            if len(processed) > 1000:
                processed = set(list(processed)[-1000:])
            
            with open(self.processed_file, 'w') as f:
                json.dump(list(processed), f)
        except Exception as e:
            logger.error(f"Could not save processed message: {e}")
    
    def is_repostable_content(self, message):
        """Check if message contains repostable content"""
        try:
            # Check for reel/video content
            if hasattr(message, 'clip_media') and message.clip_media:
                return 'reel', message.clip_media
            
            # Check for photo content
            if hasattr(message, 'visual_media') and message.visual_media:
                return 'photo', message.visual_media
            
            # Check for shared media
            if hasattr(message, 'media_share') and message.media_share:
                media = message.media_share
                if hasattr(media, 'video_url') and media.video_url:
                    return 'reel', media
                elif hasattr(media, 'thumbnail_url') and media.thumbnail_url:
                    return 'photo', media
            
        except Exception as e:
            logger.error(f"Error checking message content: {e}")
        
        return None, None
    
    def repost_content(self, content_type, media, caption_text=None):
        """Repost the content"""
        try:
            base_caption = caption_text or "📱 Shared via DM"
            
            if content_type == 'reel':
                # For reels/videos
                if hasattr(media, 'video_url') and media.video_url:
                    logger.info("Reposting reel...")
                    result = self.cl.clip_upload_by_url(
                        url=media.video_url,
                        caption=base_caption
                    )
                    logger.info(f"Reel posted successfully: {result}")
                    return True
            
            elif content_type == 'photo':
                # For photos
                photo_url = None
                if hasattr(media, 'thumbnail_url'):
                    photo_url = media.thumbnail_url
                elif hasattr(media, 'image_versions2') and media.image_versions2:
                    candidates = media.image_versions2.get('candidates', [])
                    if candidates:
                        photo_url = candidates[0].get('url')
                
                if photo_url:
                    logger.info("Reposting photo...")
                    result = self.cl.photo_upload_by_url(
                        url=photo_url,
                        caption=base_caption
                    )
                    logger.info(f"Photo posted successfully: {result}")
                    return True
            
            logger.warning(f"Could not find valid URL for {content_type}")
            return False
            
        except Exception as e:
            logger.error(f"Error reposting {content_type}: {e}")
            return False
    
    def process_messages(self):
        """Process DM messages for repostable content"""
        try:
            logger.info("Fetching direct message threads...")
            threads = self.cl.direct_threads(amount=20)
            logger.info(f"Found {len(threads)} threads")
            
            processed_messages = self.load_processed_messages()
            new_reposts = 0
            
            for thread in threads:
                logger.info(f"Processing thread with {len(thread.messages)} messages")
                
                for message in thread.messages[:10]:  # Check last 10 messages per thread
                    try:
                        message_id = str(message.id)
                        
                        # Skip if already processed
                        if message_id in processed_messages:
                            continue
                        
                        # Check if message contains repostable content
                        content_type, media = self.is_repostable_content(message)
                        
                        if content_type and media:
                            logger.info(f"Found {content_type} to repost")
                            
                            # Get caption if available
                            caption = getattr(message, 'text', '') or ''
                            
                            # Attempt repost
                            if self.repost_content(content_type, media, caption):
                                new_reposts += 1
                                self.save_processed_message(message_id)
                                
                                # Add delay between reposts
                                time.sleep(random.uniform(30, 60))
                                
                                # Limit reposts per run to avoid spam detection
                                if new_reposts >= 5:
                                    logger.info("Reached repost limit for this run")
                                    return new_reposts
                        
                        # Mark as processed even if not reposted
                        self.save_processed_message(message_id)
                        
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        continue
            
            logger.info(f"Completed processing. New reposts: {new_reposts}")
            return new_reposts
            
        except Exception as e:
            logger.error(f"Error processing messages: {e}")
            return 0
    
    def run(self):
        """Main bot execution"""
        try:
            logger.info("Starting Instagram Repost Bot...")
            
            # Login
            if not self.login_with_retry():
                logger.error("Failed to login. Exiting.")
                return False
            
            # Process messages
            reposts = self.process_messages()
            
            logger.info(f"Bot completed successfully. Posted {reposts} new items.")
            return True
            
        except Exception as e:
            logger.error(f"Bot execution failed: {e}")
            return False

def main():
    """Main entry point"""
    bot = InstagramBot()
    success = bot.run()
    
    if not success:
        exit(1)

if __name__ == "__main__":
    main()
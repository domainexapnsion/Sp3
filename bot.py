#!/usr/bin/env python3
"""
Complete Instagram DM Repost Bot
Handles session persistence and avoids login issues in CI
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
        self.session_json = os.environ.get("INSTAGRAM_SESSION_JSON")  # New: from GitHub secrets
        self.session_file = "session.json"
        self.processed_file = "processed_messages.json"

        if not self.username or not self.password:
            raise ValueError("Instagram credentials not found in environment variables")

    def load_session_from_secret(self):
        """Load session from GitHub secret"""
        try:
            if self.session_json:
                logger.info("Loading session from GitHub secret...")
                
                # Parse JSON and save to file
                session_data = json.loads(self.session_json)
                with open(self.session_file, 'w') as f:
                    json.dump(session_data, f)
                
                # Load into client
                self.cl.set_settings(session_data)
                
                # Verify session is still valid
                try:
                    self.cl.get_timeline_feed()  # Test API call
                    logger.info("✅ Session from secret is valid")
                    return True
                except Exception as e:
                    logger.warning(f"Session from secret invalid: {e}")
                    return False
            
            return False
        except Exception as e:
            logger.error(f"Could not load session from secret: {e}")
            return False

    def load_session(self):
        """Load existing session if available"""
        try:
            if os.path.exists(self.session_file):
                logger.info("Loading existing session file...")
                self.cl.load_settings(self.session_file)
                
                # Test if session is still valid
                try:
                    self.cl.get_timeline_feed()  # Test API call
                    logger.info("Session file is valid")
                    return True
                except Exception as e:
                    logger.warning(f"Session file invalid: {e}")
                    os.remove(self.session_file)
        except Exception as e:
            logger.warning(f"Could not load session file: {e}")
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

    def login_with_session(self):
        """Login using session (preferred) or fallback to credentials"""
        
        # Method 1: Try loading from GitHub secret
        if self.load_session_from_secret():
            logger.info("✅ Logged in using GitHub secret session")
            return True
        
        # Method 2: Try loading from existing session file
        if self.load_session():
            logger.info("✅ Logged in using existing session file")
            return True
        
        # Method 3: Fallback to credential login (will likely fail in CI)
        logger.warning("⚠️ No valid session found, attempting credential login...")
        logger.warning("This will likely fail in CI environments due to 2FA/device verification")
        
        try:
            # Set realistic device settings
            self.cl.set_locale('en_US')
            self.cl.set_timezone_offset(-18000)
            
            time.sleep(random.uniform(2, 5))
            self.cl.login(self.username, self.password)
            
            self.save_session()
            logger.info("✅ Credential login successful")
            return True
            
        except Exception as e:
            logger.error(f"❌ Credential login failed: {e}")
            logger.error("💡 Make sure you've added INSTAGRAM_SESSION_JSON secret to GitHub")
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

            # Login using session
            if not self.login_with_session():
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
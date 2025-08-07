import os
import json
import logging
from pathlib import Path
from time import sleep

# The correct library for interacting with the Instagram Private API
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

# Pydantic is used by instagrapi for data models, we need to catch its errors
from pydantic import ValidationError

# --- 1. Basic Setup ---

# Setup logging to see what the bot is doing
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# Define file paths for state and session
# Using Path for better cross-platform compatibility
CWD = Path(__file__).resolve().parent
PROCESSED_FILE = CWD / "processed_messages.json"
SESSION_FILE = CWD / "session.json"

# --- 2. Helper Functions for State Management ---

def load_processed_ids(filepath: Path) -> set:
    """Loads the set of processed message IDs from a JSON file."""
    if not filepath.exists():
        return set()
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
            # Ensure we return a set for fast lookups
            return set(data)
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"⚠️ Could not load processed messages from {filepath}, starting fresh: {e}")
        return set()

def save_processed_ids(filepath: Path, ids: set):
    """Saves the set of processed message IDs to a JSON file."""
    try:
        with open(filepath, "w") as f:
            # Convert set to list for JSON serialization
            json.dump(list(ids), f, indent=4)
    except IOError as e:
        logging.error(f"❌ Failed to save processed messages to {filepath}: {e}")

# --- 3. The Main Bot Class ---

class RepostBot:
    """
    A bot to automatically repost videos/reels from DMs to stories.
    """
    def __init__(self):
        # Load credentials securely from environment variables
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")

        if not self.username or not self.password:
            raise ValueError("❌ Missing INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD environment variables.")

        self.client = Client()
        self.processed_ids = load_processed_ids(PROCESSED_FILE)
        logging.info(f"📂 Loaded {len(self.processed_ids)} processed message IDs.")

    def login(self):
        """
        Logs into Instagram using a saved session if available,
        otherwise performs a new login.
        """
        try:
            if SESSION_FILE.exists():
                logging.info("Attempting to log in using session file...")
                self.client.load_settings(SESSION_FILE)
                self.client.login(self.username, self.password)
                # Check if session is still valid
                self.client.get_timeline_feed()
                logging.info("✅ Session login successful!")
            else:
                logging.info("No session file found, performing a new login...")
                self.client.login(self.username, self.password)
                self.client.dump_settings(SESSION_FILE)
                logging.info("✅ New login successful, session file created.")
        except LoginRequired:
            logging.warning("⚠️ Session was invalid, performing a new login...")
            self.client.login(self.username, self.password)
            self.client.dump_settings(SESSION_FILE)
            logging.info("✅ Re-login successful, session file updated.")
        except Exception as e:
            logging.error(f"❌ An unexpected error occurred during login: {e}")
            raise

    def repost_media_to_story(self, media_pk: str):
        """Downloads a video and uploads it to the story."""
        logging.info(f"📥 Downloading video with PK: {media_pk}...")
        try:
            path = self.client.video_download(media_pk)
            logging.info(f"✅ Download complete: {path.name}")
            
            logging.info("📤 Uploading to story...")
            self.client.video_upload_to_story(path)
            logging.info("✅ Story repost successful!")
            
            # Clean up the downloaded file
            path.unlink()
            logging.info(f"🗑️ Deleted temporary file: {path.name}")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to repost video PK {media_pk}: {e}")
            return False

    def process_direct_messages(self):
        """
        Fetches recent direct message threads, finds unprocessed videos,
        and reposts them to the story.
        """
        logging.info("Checking for new messages in DMs...")
        # Fetch a reasonable number of recent threads
        threads = self.client.direct_threads(amount=20)
        reposts_in_run = 0

        for thread in threads:
            for message in thread.messages:
                if message.id in self.processed_ids:
                    continue # Skip already processed messages

                try:
                    # Default media_pk to None
                    media_pk_to_repost = None
                    
                    # Check if the message contains a Reel or Video
                    # message.clip is for shared reels/posts
                    if message.clip and message.clip.media_type == 1: # 1 = Video
                        logging.info(f"Found a new Reel in DM from '{thread.users[0].username}': {message.clip.pk}")
                        media_pk_to_repost = message.clip.pk
                    
                    # message.video is for videos sent directly
                    elif message.video and message.video.media_type == 1:
                        logging.info(f"Found a new Video in DM from '{thread.users[0].username}': {message.video.pk}")
                        media_pk_to_repost = message.video.pk

                    if media_pk_to_repost:
                        if self.repost_media_to_story(media_pk_to_repost):
                            reposts_in_run += 1
                            sleep(15) # Wait a bit between reposts to look more human

                except ValidationError as e:
                    # THIS IS THE FIX for your original error.
                    # It catches posts with missing data and skips them.
                    logging.warning(f"⚠️ Skipping message {message.id} due to a data validation error (likely missing audio info). Error: {e}")
                
                except Exception as e:
                    logging.error(f"❌ An unexpected error occurred while processing message {message.id}: {e}")
                
                finally:
                    # Mark the message as processed whether it succeeded or failed,
                    # to prevent trying to process a broken message repeatedly.
                    self.processed_ids.add(message.id)
        
        logging.info(f"✅ DM check complete. New posts reposted in this run: {reposts_in_run}")

    def run(self):
        """The main execution flow of the bot."""
        logging.info("🚀 Starting Instagram Repost Bot...")
        try:
            self.login()
            self.process_direct_messages()
        finally:
            # Always save the state of processed messages, even if an error occurs
            save_processed_ids(PROCESSED_FILE, self.processed_ids)
            logging.info("🤖 Bot run finished.")

# --- 4. Script Execution ---

if __name__ == "__main__":
    try:
        # Before running, ensure you have set up your environment and dependencies
        # 1. pip install instagrapi
        # 2. Set environment variables:
        #    export INSTAGRAM_USERNAME="your_username"
        #    export INSTAGRAM_PASSWORD="your_password"
        bot = RepostBot()
        bot.run()
    except Exception as e:
        logging.critical(f"A fatal error occurred: {e}")
        exit(1)

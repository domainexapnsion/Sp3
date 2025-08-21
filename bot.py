#!/usr/bin/env python3
"""
Ultimate Instagram Repost Bot - Enterprise-Grade Reliability
Author: DeepSeek
Date: August 9, 2025
Description: Military-grade repost bot with multi-layered fail-safes, advanced error handling,
and forensic logging. Survives API changes, network failures, and validation errors.
MODIFIED: To handle OTP, private accounts, and persistent sessions.
"""

import os
import json
import time
import random
import logging
import sys
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

# Install dependencies if missing
try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired, ChallengeRequired,
        PydanticValidationError, ClientError,
        ClientConnectionError, ClientThrottledError
    )
except ImportError:
    print("Installing required packages...")
    os.system("pip install -q instagrapi requests tqdm")
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired, ChallengeRequired,
        PydanticValidationError, ClientError,
        ClientConnectionError, ClientThrottledError
    )

# --- Compatibility Configuration ---
USERNAME = os.getenv("INSTAGRAM_USERNAME")
PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
SESSION_FILE = Path("session.json")
PROCESSED_FILE = Path("processed_messages.json")
DOWNLOADS_DIR = Path("downloads")
CONFIG_FILE = Path("bot_config.json")

# Operational Parameters
MAX_REPOSTS = 5
MAX_RETRIES = 7
# SELF_DESTRUCT = 72 # MODIFICATION: Removed to prevent forced logout.

# --- Setup Logging ---
DOWNLOADS_DIR.mkdir(exist_ok=True, mode=0o700)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(module)s:%(funcName)s:%(lineno)d - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", mode='a'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('IG_SPECOPS')
logger.setLevel(logging.INFO)

class CyberWarfareUnit:
    def __init__(self):
        self.validate_credentials()
        self.cl = Client()
        self.cl.delay_range = [3, 8]
        self.cl.request_timeout = 45
        self.processed = self.load_processed_ids()
        self.config = self.load_config()
        logger.info(f"🛡️ Active defense protocols engaged. Known targets: {len(self.processed)}")

    def validate_credentials(self):
        if not USERNAME or not PASSWORD:
            logger.critical("⛔ CREDENTIALS NOT FOUND IN WAR CHEST")
            sys.exit("TERMINATING: Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD env vars")

    def load_config(self):
        defaults = {
            "last_run": None,
            "failure_count": 0,
            "total_reposts": 0
        }
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text())
            except Exception as e:
                logger.warning(f"⚠️ Config corrupted: {e}. Using defaults")
        return defaults

    def save_config(self):
        self.config['last_run'] = datetime.now().isoformat()
        CONFIG_FILE.write_text(json.dumps(self.config, indent=2))

    def load_processed_ids(self):
        if PROCESSED_FILE.exists():
            try:
                data = PROCESSED_FILE.read_text()
                return set(json.loads(data))
            except:
                logger.warning("⚠️ Processed IDs file compromised! Starting fresh")
        return set()

    def save_processed_ids(self):
        PROCESSED_FILE.write_text(json.dumps(list(self.processed)))

    def tactical_login(self):
        """Multi-phase authentication with OTP/2FA support and persistent sessions."""
        logger.info("🔑 Initiating black ops authentication")

        # MODIFICATION: The 72-hour session expiry check was removed for persistence.

        # Phase 1: Session-based auth
        if SESSION_FILE.exists():
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(USERNAME, PASSWORD) # Re-login is necessary to verify session
                self.cl.get_timeline_feed()
                logger.info("✅ Session authentication valid")
                return True
            except (LoginRequired, ClientConnectionError) as e:
                logger.warning(f"⚠️ Session compromised: {e}. Activating countermeasures")

        # Phase 2: Credential assault
        logger.info("🚀 Deploying fresh credentials")
        try:
            self.cl.login(USERNAME, PASSWORD)
            self.cl.dump_settings(SESSION_FILE)
            logger.info("🔥 Authentication successful. New session deployed")
            return True
        except ChallengeRequired:
            # MODIFICATION: Added interactive OTP/2FA handling.
            logger.warning("🛡️ OTP/2FA CHALLENGE REQUIRED!")
            try:
                otp = input("Please enter the 6-digit code from your authenticator app or SMS: ").strip()
                if self.cl.challenge_code(otp):
                    logger.info("✅ OTP Accepted. Authentication successful!")
                    self.cl.dump_settings(SESSION_FILE)
                    return True
                else:
                    logger.critical("☠️ Invalid OTP code. Terminating operation.")
                    return False
            except Exception as e:
                logger.critical(f"☠️ An error occurred during OTP validation: {e}")
                return False
        except Exception as e:
            logger.critical(f"☠️ FATAL LOGIN FAILURE: {e}")

        return False

    def extract_media(self, message: dict) -> tuple:
        """Commando extraction of media from hostile territory"""
        media_share = message.get('media_share') or {}
        media_pk = media_share.get('pk')
        caption = (media_share.get('caption') or {}).get('text', '') if media_share.get('caption') else ''
        user_id = message.get('user_id')

        if not media_pk:
            return None, None, None

        logger.info(f"🎯 Target acquired: Media {media_pk} from User {user_id}")
        return media_pk, caption, user_id

    def download_asset(self, media_pk: str, media_type: int) -> Path:
        """MODIFICATION: Uses instagrapi's native downloader for private account compatibility."""
        logger.info(f"📥 Acquiring asset {media_pk}...")
        try:
            if media_type == 2: # Video
                filepath = self.cl.video_download(media_pk, folder=DOWNLOADS_DIR)
            elif media_type == 1: # Photo
                filepath = self.cl.photo_download(media_pk, folder=DOWNLOADS_DIR)
            else: # Album (download first item)
                resources = self.cl.media_resources(media_pk)
                first_item_pk = resources[0].pk
                if resources[0].media_type == 2:
                    filepath = self.cl.video_download(first_item_pk, folder=DOWNLOADS_DIR)
                else:
                    filepath = self.cl.photo_download(first_item_pk, folder=DOWNLOADS_DIR)
            
            logger.info(f"💾 Asset secured at {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"☢️ Download failed for media {media_pk}: {e}")
            return None

    def deploy_content(self, filepath: Path, caption: str) -> bool:
        """Multi-spectrum deployment with fallback positions"""
        ext = filepath.suffix.lower()
        logger.info(f"🚀 Launching content deployment: {filepath.name}")

        try:
            if ext == '.mp4':
                logger.info("⚡ Deploying as a Reel...")
                result = self.cl.clip_upload(filepath, caption)
            elif ext in ('.jpg', '.jpeg', '.png'):
                logger.info("⚡ Deploying as a Photo...")
                result = self.cl.photo_upload(filepath, caption)
            else:
                logger.error(f"🛑 Unsupported file type: {ext}")
                return False

            if result:
                logger.info(f"🎯 DIRECT HIT! ID: {result.pk}")
                return True
        except Exception as e:
            logger.warning(f"💥 Deployment failure: {type(e).__name__} - {str(e)[:100]}")

        logger.error("☠️ DEPLOYMENT FAILED")
        return False

    def execute_mission(self):
        """Main combat operation"""
        if not self.tactical_login():
            return

        logger.info("📡 Establishing SIGINT connection to Instagram HQ")
        try:
            inbox = self.cl.direct_threads(thread_count=20, selected_filter="unread")
            logger.info(f"📨 Intel received: {len(inbox)} active unread threads")

            repost_count = 0
            for thread in inbox:
                if repost_count >= MAX_REPOSTS:
                    logger.info("⚠️ Mission quota reached. Tactical withdrawal")
                    break

                for msg in thread.messages:
                    if repost_count >= MAX_REPOSTS:
                        break

                    if msg.id in self.processed:
                        continue

                    media_pk, caption, sender_id = self.extract_media(msg.dict())
                    if not media_pk:
                        self.processed.add(msg.id) # Mark as processed even if not media
                        continue

                    try:
                        media = self.cl.media_info(media_pk)
                        logger.info(f"🎬 Target validated: Type {media.media_type}")

                        asset_path = self.download_asset(media.pk, media.media_type)
                        if not asset_path:
                            continue

                        if self.deploy_content(asset_path, caption):
                            repost_count += 1
                            self.config['total_reposts'] = self.config.get('total_reposts', 0) + 1
                            logger.info(f"✅ TARGET NEUTRALIZED | Total for run: {repost_count}/{MAX_REPOSTS}")

                        asset_path.unlink() # Cleanup downloaded file
                        self.processed.add(msg.id)

                        sleep_time = random.randint(15, 30)
                        logger.info(f"😴 Evasion protocol: Sleeping {sleep_time}s")
                        time.sleep(sleep_time)

                    except PydanticValidationError as e:
                        logger.error(f"🛡️ Validation shield engaged: {e}")
                    except Exception as e:
                        logger.critical(f"☢️ CRITICAL MISSION FAILURE on media {media_pk}: {e}")
                        self.config['failure_count'] = self.config.get('failure_count', 0) + 1
            
            logger.info(f"🏁 MISSION COMPLETE | Reposts This Run: {repost_count}")

        except Exception as e:
            logger.critical(f"☠️ OPERATION FAILED: {e}", exc_info=True)
        finally:
            self.save_processed_ids()
            self.save_config()
            logger.info("🔒 Safe mode engaged. All systems secured")

def main():
    print("\n" + "="*60)
    print("🔥 INSTAGRAM REPOST BOT - MODIFIED EDITION 🔥".center(60))
    print("="*60 + "\n")

    unit = CyberWarfareUnit()
    unit.execute_mission()

    print("\n" + "="*60)
    print("✅ OPERATION COMPLETED".center(60))
    print("="*60)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Debug Version - Instagram DM Repost Bot
Now only processes:
  • Reel URLs shared in DM text
  • Photo attachments with text as caption
"""

from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, PleaseWaitFewMinutes
import os
import json
import time
import logging
import random
import re

# Configure logging with more detail
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class InstagramBot:
    REEL_REGEX = re.compile(r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?")
    
    def __init__(self):
        self.cl = Client()
        self.username = os.environ.get("INSTAGRAM_USERNAME")
        self.password = os.environ.get("INSTAGRAM_PASSWORD")
        self.session_json = os.environ.get("INSTAGRAM_SESSION_JSON")
        self.session_file = "session.json"
        self.processed_file = "processed_messages.json"

        if not self.username or not self.password:
            raise ValueError("Missing Instagram credentials in environment variables")

        logger.debug(f"Init: username set, session_json {'found' if self.session_json else 'not set'}")

    def load_session_from_secret(self):
        if not self.session_json:
            return False
        try:
            logger.debug("Loading session from secret...")
            data = json.loads(self.session_json)
            with open(self.session_file, 'w') as f:
                json.dump(data, f)
            self.cl.set_settings(data)
            # test
            self.cl.user_info_by_username(self.username)
            logger.debug("Session from secret valid")
            return True
        except Exception as e:
            logger.warning(f"Secret session invalid: {e}")
            return False

    def load_session(self):
        if not os.path.exists(self.session_file):
            return False
        try:
            logger.debug("Loading session file...")
            self.cl.load_settings(self.session_file)
            self.cl.user_info_by_username(self.username)
            logger.debug("Session file valid")
            return True
        except Exception as e:
            logger.warning(f"Session file invalid, removing: {e}")
            os.remove(self.session_file)
            return False

    def save_session(self):
        try:
            self.cl.dump_settings(self.session_file)
            logger.debug("Session saved")
        except Exception as e:
            logger.error(f"Could not save session: {e}")

    def login_with_session(self):
        if self.load_session_from_secret() or self.load_session():
            logger.info("Logged in via saved session")
            return True
        try:
            logger.info("Performing fresh login...")
            self.cl.login(self.username, self.password)
            self.save_session()
            return True
        except Exception as e:
            logger.error(f"Fresh login failed: {e}")
            return False

    def load_processed(self):
        if os.path.exists(self.processed_file):
            try:
                return set(json.load(open(self.processed_file)))
            except:
                pass
        return set()

    def save_processed(self, processed):
        json.dump(list(processed), open(self.processed_file, "w"))

    def process_messages(self):
        processed = self.load_processed()
        threads = self.cl.direct_threads(amount=20)
        reposts = 0

        for thread in threads:
            for msg in thread.messages:
                mid = str(msg.id)
                if mid in processed:
                    continue

                text = msg.text or ""

                # 1) Reel link in text
                m = self.REEL_REGEX.search(text)
                if m:
                    url = m.group(0)
                    logger.info(f"Reposting reel link: {url}")
                    try:
                        self.cl.clip_upload_by_url(url, caption="")
                        reposts += 1
                    except Exception as e:
                        logger.error(f"Reel repost failed: {e}")
                    processed.add(mid)
                    time.sleep(random.uniform(1,3))
                    if reposts >= 5:
                        break
                    continue

                # 2) Photo attachment + text caption
                if hasattr(msg, 'media_share') and msg.media_share:
                    media = msg.media_share
                    photo_url = getattr(media, 'thumbnail_url', None)
                    if photo_url:
                        caption = text.strip()
                        logger.info(f"Reposting photo: {photo_url} with caption: {caption}")
                        try:
                            self.cl.photo_upload_by_url(photo_url, caption=caption)
                            reposts += 1
                        except Exception as e:
                            logger.error(f"Photo repost failed: {e}")
                        processed.add(mid)
                        time.sleep(random.uniform(1,3))
                        if reposts >= 5:
                            break
                        continue

                # mark processed anyway
                processed.add(mid)

            if reposts >= 5:
                break

        self.save_processed(processed)
        logger.info(f"Run complete. Total reposts: {reposts}")

    def run(self):
        logger.info("Starting bot...")
        if not self.login_with_session():
            logger.error("Login failed, exiting")
            return
        self.process_messages()

if __name__ == "__main__":
    InstagramBot().run()
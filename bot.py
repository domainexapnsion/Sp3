import os
import json
import re
import logging
from time import sleep
from instagrapi import Client
from pydantic_core import ValidationError # <-- IMPORT THIS

# ... (rest of your setup code is fine) ...

class InstagramRepostBot:
    def __init__(self):
        self.cl = Client()
        self.username = os.getenv("INSTAGRAM_USERNAME")
        self.password = os.getenv("INSTAGRAM_PASSWORD")
        self.processed = set(load_json(PROCESSED_FILE))

    def login(self):
        # ... (your login function is fine) ...
        if os.path.exists(SESSION_FILE):
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(self.username, self.password)
                logger.info("✅ Session restored.")
                return
            except Exception as e:
                logger.warning(f"⚠️ Failed to load session: {e}")

        logger.info("🔐 Logging in fresh.")
        self.cl.login(self.username, self.password)
        self.cl.dump_settings(SESSION_FILE)


    def process_dms(self):
        threads = [] # Initialize as empty list
        try:
            # --- THIS IS THE CRITICAL PART ---
            # The error happens here, so we wrap it
            threads = self.cl.direct_threads()
            # ---------------------------------
        except ValidationError as e:
            logger.error(f"CRITICAL: Failed to parse DM threads from Instagram. The API might have changed. Error: {e}")
            logger.error("Aborting this run to prevent further issues.")
            return # Exit the function gracefully

        reposts = 0
        for thread in threads:
            for msg in thread.messages:
                msg_id = str(msg.id)
                if msg_id in self.processed:
                    continue

                # The rest of your logic from here is good because
                # it already has its own error handling for uploads.
                text = msg.text or ""

                # Case 1: Reel URL in text
                m = REEL_REGEX.search(text)
                if m:
                    url = m.group(0)
                    logger.info(f"🎯 Reposting reel URL: {url}")
                    try:
                        # Using clip_upload_by_url for reels from DMs is more reliable
                        media_pk = self.cl.media_pk_from_url(url)
                        self.cl.media_info(media_pk) # Check if media is valid
                        self.cl.clip_repost(media_pk)
                        self.processed.add(msg_id)
                        reposts += 1
                        human_delay()
                    except Exception as e:
                        logger.warning(f"❌ Failed to repost reel from URL {url}: {e}")
                    continue

                # Case 2: Forwarded reel (media_share)
                if hasattr(msg, "media_share") and msg.media_share:
                    media = msg.media_share
                    if getattr(media, "media_type", 0) == 2: # 2 means video/reel
                        logger.info(f"↪️ Reposting forwarded reel: {media.pk}")
                        try:
                            self.cl.clip_repost(media.pk)
                            self.processed.add(msg_id)
                            reposts += 1
                            human_delay()
                        except Exception as e:
                            logger.warning(f"❌ Failed to repost forwarded reel {media.pk}: {e}")
                        continue
                    
                    # Case 3: Image with optional caption
                    if getattr(media, "media_type", 0) == 1: # 1 means photo
                        logger.info(f"🖼️ Reposting image post: {media.pk}")
                        try:
                            self.cl.photo_repost(media.pk, caption=text)
                            self.processed.add(msg_id)
                            reposts += 1
                            human_delay()
                        except Exception as e:
                            logger.warning(f"❌ Failed to repost image {media.pk}: {e}")
                        continue

        logger.info(f"✅ Run complete. Total reposts: {reposts}")
        save_json(list(self.processed), PROCESSED_FILE)

# --- Main ---
if __name__ == "__main__":
    bot = InstagramRepostBot()
    bot.login()
    bot.process_dms()

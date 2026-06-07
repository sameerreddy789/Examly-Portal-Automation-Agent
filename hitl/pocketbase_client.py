"""
hitl/pocketbase_client.py — Human-in-the-Loop PocketBase Integration

This module connects the browser agent to a local PocketBase database,
allowing it to pause, upload a screenshot, and wait for your response
through the Streamlit dashboard.

Think of it like a "phone-a-friend" system:
- The bot gets stuck on a CAPTCHA or confusing page
- It takes a screenshot and "pauses"
- You see the screenshot on the dashboard and type a solution
- The bot reads your answer and continues

Usage:
    from hitl import HITLClient

    client = HITLClient()
    
    # When the bot gets stuck:
    user_response = await client.pause_for_user(page, "I can't solve this CAPTCHA")
"""

import asyncio
import base64
from loguru import logger
import os
import time
from typing import Optional

logger = logger.bind(name="browser_use.hitl")

# How often to check PocketBase for user responses (in seconds)
POLL_INTERVAL = 2.0

# Maximum time to wait for user response (in seconds) — 10 minutes
MAX_WAIT_TIME = 600


class HITLClient:
    """
    Manages communication between the browser agent and the HITL dashboard.
    
    Lifecycle:
    1. Bot runs normally (state = RUNNING)
    2. Bot encounters a problem → calls pause_for_user() → state = PAUSED_FOR_USER
    3. Dashboard shows the screenshot and a text input
    4. User types response and clicks Resume → state = RUNNING, user_response is set
    5. Bot reads the response and continues
    """
    
    def __init__(self, pocketbase_url: Optional[str] = None):
        """
        Initialize the HITL client.
        
        Args:
            pocketbase_url: URL of the PocketBase server (default: from .env or http://127.0.0.1:8090).
        """
        self._pb_url = pocketbase_url or os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090")
        self._pb = None
        self._record_id = None
        self._connected = False
        
    def _connect(self) -> bool:
        """Try to connect to PocketBase and ensure the bot_state collection exists."""
        if self._connected:
            return True
            
        try:
            from pocketbase import PocketBase
            
            self._pb = PocketBase(self._pb_url)
            
            # Try to get or create the initial bot_state record
            try:
                records = self._pb.collection("bot_state").get_list(1, 1)
                if records.items:
                    self._record_id = records.items[0].id
                else:
                    # Create the initial record
                    record = self._pb.collection("bot_state").create({
                        "state": "IDLE",
                        "message": "Bot initialized",
                        "screenshot_b64": "",
                        "user_response": "",
                        "timestamp": time.time(),
                    })
                    self._record_id = record.id
            except Exception:
                # Collection might not exist yet — setup_pocketbase.py needs to run first
                logger.warning(
                    "⚠️ [HITL]: Could not access 'bot_state' collection. "
                    "Run 'python hitl/setup_pocketbase.py' first to create the collection."
                )
                return False
            
            self._connected = True
            logger.info(f"✅ [HITL]: Connected to PocketBase at {self._pb_url}")
            return True
            
        except ImportError:
            logger.warning("⚠️ [HITL]: pocketbase package not installed. HITL disabled.")
            return False
        except Exception as e:
            logger.warning(f"⚠️ [HITL]: Cannot connect to PocketBase at {self._pb_url}: {e}")
            logger.info("ℹ️ [HITL]: HITL dashboard features disabled. Bot will fall back to terminal input.")
            return False
    
    def update_state(self, state: str, message: str = "", screenshot_b64: str = "") -> bool:
        """
        Update the bot's state in PocketBase.
        
        States:
        - IDLE: Bot hasn't started yet
        - RUNNING: Bot is working normally
        - PAUSED_FOR_USER: Bot is stuck and waiting for your help
        - COMPLETED: Bot finished its task
        - ERROR: Bot encountered a fatal error
        
        Args:
            state: One of the states above.
            message: Description of what's happening.
            screenshot_b64: Base64-encoded screenshot (optional).
        
        Returns:
            True if update succeeded, False otherwise.
        """
        if not self._connect():
            return False
        
        try:
            self._pb.collection("bot_state").update(self._record_id, {
                "state": state,
                "message": message,
                "screenshot_b64": screenshot_b64,
                "user_response": "",  # Clear previous response
                "timestamp": time.time(),
            })
            logger.info(f"📡 [HITL]: State updated to {state}: {message}")
            return True
        except Exception as e:
            logger.error(f"❌ [HITL]: Failed to update state: {e}")
            return False
    
    def check_for_user_response(self) -> Optional[str]:
        """
        Check if the user has submitted a response via the dashboard.
        
        Returns:
            The user's response string, or None if no response yet.
        """
        if not self._connected or not self._pb:
            return None
        
        try:
            record = self._pb.collection("bot_state").get_one(self._record_id)
            response = getattr(record, "user_response", "")
            state = getattr(record, "state", "")
            
            # User has responded if state changed back to RUNNING and there's a response
            if response and state == "RUNNING":
                return response
            return None
        except Exception as e:
            logger.error(f"❌ [HITL]: Error checking for user response: {e}")
            return None
    
    async def pause_for_user(self, page, reason: str, timeout: float = MAX_WAIT_TIME) -> Optional[str]:
        """
        Pause the bot and wait for user input via the dashboard.
        
        This is the main function — call it when the bot gets stuck.
        It will:
        1. Take a screenshot of the current page
        2. Upload it to PocketBase with the reason
        3. Wait for you to respond through the Streamlit dashboard
        4. Return your response so the bot can continue
        
        Args:
            page: Playwright page object (for screenshot).
            reason: Why the bot is paused (shown on the dashboard).
            timeout: Maximum seconds to wait (default: 10 minutes).
        
        Returns:
            The user's response text, or None if timed out.
        """
        if not self._connect():
            # Fallback to terminal input if PocketBase isn't available
            logger.info("ℹ️ [HITL]: PocketBase unavailable, falling back to terminal input.")
            return await self._terminal_fallback(reason)
        
        # Take a screenshot
        try:
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.error(f"❌ [HITL]: Failed to take screenshot: {e}")
            screenshot_b64 = ""
        
        # Update state to PAUSED
        self.update_state("PAUSED_FOR_USER", reason, screenshot_b64)
        
        print(f"\n\033[93m🤖 [HITL]: Bot paused — {reason}\033[0m")
        print(f"\033[93m   Open the Streamlit dashboard to respond, or type here:\033[0m")
        
        # Poll for user response (check both PocketBase and terminal)
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            # Check PocketBase for dashboard response
            response = self.check_for_user_response()
            if response:
                logger.info(f"✅ [HITL]: Received user response via dashboard: {response}")
                return response
            
            await asyncio.sleep(POLL_INTERVAL)
        
        logger.warning(f"⚠️ [HITL]: Timed out waiting for user response after {timeout}s")
        self.update_state("RUNNING", "Timeout — bot resuming without user input")
        return None
    
    async def _terminal_fallback(self, reason: str) -> str:
        """Fallback: ask the user in the terminal when PocketBase is unavailable."""
        print(f"\n\033[93m🤖 [HITL FALLBACK]: {reason}\033[0m")
        response = await asyncio.to_thread(input, "👉 Your Response: ")
        return response.strip()
    
    async def upload_screenshot(self, page, message: str = "Live screenshot") -> bool:
        """
        Upload a live screenshot without pausing. Just for dashboard monitoring.
        
        Args:
            page: Playwright page object.
            message: Status message to show alongside the screenshot.
        
        Returns:
            True if upload succeeded.
        """
        if not self._connect():
            return False
        
        try:
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            self.update_state("RUNNING", message, screenshot_b64)
            return True
        except Exception as e:
            logger.error(f"❌ [HITL]: Screenshot upload failed: {e}")
            return False

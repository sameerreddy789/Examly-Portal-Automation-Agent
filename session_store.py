"""
session_store.py — Persistent Session Storage with Redis + Local Fallback

Backs up browser cookies and session data so the bot can restore logins
across runs, even if the browser profile folder gets corrupted.

Two storage backends:
1. Redis (if available) — fast, supports TTL, sharable across machines
2. Local JSON files (fallback) — works without any extra setup

Usage:
    from session_store import SessionStore

    store = SessionStore()  # Automatically detects Redis availability
    
    # After logging in, save the session
    await store.backup_session(browser_context, "examly_main")
    
    # On next run, restore the session
    await store.restore_session(browser_context, "examly_main")
"""

import json
from loguru import logger
import os
from datetime import datetime
from typing import Optional

logger = logger.bind(name="browser_use.session_store")

# Directory for local JSON fallback storage
SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")


class SessionStore:
    """
    Manages browser session backup and restore.
    
    Think of it like a "save game" system for your browser sessions:
    - After you successfully log in, it saves all the cookies
    - Next time you run the bot, it loads those cookies back
    - This way you don't have to log in every single time
    
    Redis is used if available (faster, supports expiry), otherwise
    it falls back to saving JSON files in the sessions/ folder.
    """
    
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        """
        Initialize the session store.
        
        Args:
            redis_host: Redis server hostname (default: localhost).
            redis_port: Redis server port (default: 6379).
        """
        self._redis = None
        self._using_redis = False
        
        # Redis checking disabled to speed up startup times.
        logger.info(
            f"ℹ️ [SESSION STORE]: Redis checking disabled. "
            f"Using local JSON file storage in {SESSIONS_DIR}/"
        )
        
        # Ensure the local sessions directory exists (used as fallback or primary)
        os.makedirs(SESSIONS_DIR, exist_ok=True)
    
    async def backup_session(self, context, session_id: str, ttl_seconds: int = 86400) -> bool:
        """
        Extract cookies from a Playwright browser context and save them.
        
        What this does:
        1. Grabs all cookies from the current browser session
        2. Serializes them to JSON
        3. Stores them in Redis (with a 24-hour expiry) or a local JSON file
        
        Args:
            context: Playwright BrowserContext object.
            session_id: A name for this session (e.g., "examly_main", "github_login").
            ttl_seconds: How long to keep the session in Redis (default: 24 hours).
        
        Returns:
            True if backup succeeded, False otherwise.
        """
        try:
            # Extract cookies from the browser context
            cookies = await context.cookies()
            
            session_data = {
                "session_id": session_id,
                "cookies": cookies,
                "saved_at": datetime.now().isoformat(),
                "cookie_count": len(cookies),
            }
            
            serialized = json.dumps(session_data, indent=2, default=str)
            
            # Save to Redis if available
            if self._using_redis and self._redis:
                try:
                    self._redis.set(
                        f"browser_session:{session_id}", 
                        serialized, 
                        ex=ttl_seconds
                    )
                    logger.info(
                        f"✅ [SESSION STORE]: Backed up {len(cookies)} cookies to Redis "
                        f"(session: '{session_id}', TTL: {ttl_seconds}s)"
                    )
                except Exception as redis_err:
                    logger.warning(f"⚠️ [SESSION STORE]: Redis save failed ({redis_err}), falling back to local file.")
                    self._save_local(session_id, serialized)
            else:
                self._save_local(session_id, serialized)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ [SESSION STORE]: Failed to backup session '{session_id}': {e}")
            return False
    
    async def restore_session(self, context, session_id: str) -> bool:
        """
        Load saved cookies and inject them into a Playwright browser context.
        
        What this does:
        1. Loads the previously saved cookies from Redis or local file
        2. Injects them into the browser context
        3. The browser now "remembers" the previous login
        
        Args:
            context: Playwright BrowserContext object.
            session_id: The name of the session to restore.
        
        Returns:
            True if restore succeeded, False if session not found or failed.
        """
        try:
            session_data = self._load_session(session_id)
            
            if session_data is None:
                logger.info(f"ℹ️ [SESSION STORE]: No saved session found for '{session_id}'.")
                return False
            
            cookies = session_data.get("cookies", [])
            
            if not cookies:
                logger.warning(f"⚠️ [SESSION STORE]: Session '{session_id}' exists but has no cookies.")
                return False
            
            # Inject the cookies into the browser context
            await context.add_cookies(cookies)
            
            saved_at = session_data.get("saved_at", "unknown")
            logger.info(
                f"✅ [SESSION STORE]: Restored {len(cookies)} cookies for session '{session_id}' "
                f"(saved at: {saved_at})"
            )
            return True
            
        except Exception as e:
            logger.error(f"❌ [SESSION STORE]: Failed to restore session '{session_id}': {e}")
            return False
    
    def list_sessions(self) -> list[dict]:
        """
        List all saved sessions with metadata.
        
        Returns:
            List of dicts with session_id, saved_at, and cookie_count.
        """
        sessions = []
        
        # Check Redis first
        if self._using_redis and self._redis:
            try:
                keys = self._redis.keys("browser_session:*")
                for key in keys:
                    data = self._redis.get(key)
                    if data:
                        parsed = json.loads(data)
                        sessions.append({
                            "session_id": parsed.get("session_id"),
                            "saved_at": parsed.get("saved_at"),
                            "cookie_count": parsed.get("cookie_count", 0),
                            "source": "redis",
                        })
            except Exception as e:
                logger.warning(f"⚠️ [SESSION STORE]: Error listing Redis sessions: {e}")
        
        # Also check local files
        if os.path.exists(SESSIONS_DIR):
            for filename in os.listdir(SESSIONS_DIR):
                if filename.endswith(".json"):
                    filepath = os.path.join(SESSIONS_DIR, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            parsed = json.load(f)
                            sid = parsed.get("session_id", filename.replace(".json", ""))
                            # Avoid duplicates if same session is in both Redis and local
                            if not any(s["session_id"] == sid for s in sessions):
                                sessions.append({
                                    "session_id": sid,
                                    "saved_at": parsed.get("saved_at"),
                                    "cookie_count": parsed.get("cookie_count", 0),
                                    "source": "local",
                                })
                    except Exception:
                        pass
        
        return sessions
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a saved session from both Redis and local storage.
        
        Args:
            session_id: The session to delete.
        
        Returns:
            True if at least one session was deleted.
        """
        deleted = False
        
        # Delete from Redis
        if self._using_redis and self._redis:
            try:
                result = self._redis.delete(f"browser_session:{session_id}")
                if result > 0:
                    deleted = True
                    logger.info(f"🗑️ [SESSION STORE]: Deleted session '{session_id}' from Redis.")
            except Exception as e:
                logger.warning(f"⚠️ [SESSION STORE]: Error deleting from Redis: {e}")
        
        # Delete local file
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted = True
            logger.info(f"🗑️ [SESSION STORE]: Deleted session '{session_id}' from local storage.")
        
        return deleted
    
    def _save_local(self, session_id: str, serialized: str) -> None:
        """Save session data to a local JSON file."""
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(serialized)
        logger.info(f"✅ [SESSION STORE]: Saved session '{session_id}' to {filepath}")
    
    def _load_session(self, session_id: str) -> Optional[dict]:
        """Load session data from Redis (preferred) or local file."""
        # Try Redis first
        if self._using_redis and self._redis:
            try:
                data = self._redis.get(f"browser_session:{session_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"⚠️ [SESSION STORE]: Redis read failed ({e}), trying local file.")
        
        # Fall back to local file
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ [SESSION STORE]: Failed to read local session file: {e}")
        
        return None

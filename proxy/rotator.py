"""
proxy/rotator.py — Proxy Pool & Rotation Manager

Manages a pool of proxy servers and provides rotation for Playwright.
Uses Playwright's built-in proxy support (no mitmproxy needed).

How it works:
- You provide a list of proxy URLs in your .env file
- The rotator cycles through them round-robin style
- If a proxy fails, it gets marked as dead and skipped
- If all proxies fail, it falls back to direct connection

Usage:
    from proxy import ProxyRotator

    rotator = ProxyRotator.from_env()  # Reads PROXY_LIST from .env
    proxy_config = rotator.get_playwright_proxy_config()
    
    # Pass to BrowserProfile
    browser_profile = BrowserProfile(proxy=proxy_config, ...)
"""

from loguru import logger
import os
from urllib.parse import urlparse
from typing import Optional

logger = logger.bind(name="browser_use.proxy")


class ProxyRotator:
    """
    Manages a pool of proxy servers for browser automation.
    
    Think of it like a revolving door for internet connections:
    - Instead of always using your home IP (which can get blocked),
      each request goes through a different proxy server
    - If one proxy stops working, it moves to the next one
    - If you have no proxies configured, it just uses your normal connection
    """
    
    def __init__(self, proxy_list: list[str]):
        """
        Initialize with a list of proxy URLs.
        
        Args:
            proxy_list: List of proxy URLs like ["http://user:pass@proxy1.com:8000", ...]
        """
        self._all_proxies = [p.strip() for p in proxy_list if p.strip()]
        self._alive_proxies = list(self._all_proxies)
        self._dead_proxies: list[str] = []
        self._current_index = 0
        self._enabled = len(self._alive_proxies) > 0
        
        if self._enabled:
            logger.info(f"✅ [PROXY]: Initialized with {len(self._alive_proxies)} proxies.")
        else:
            logger.info("ℹ️ [PROXY]: No proxies configured. Using direct connection.")
    
    @classmethod
    def from_env(cls) -> "ProxyRotator":
        """
        Create a ProxyRotator from the PROXY_LIST environment variable.
        
        The PROXY_LIST should be comma-separated proxy URLs:
            PROXY_LIST=http://user:pass@proxy1.com:8000,http://user:pass@proxy2.com:8000
        
        Returns:
            A ProxyRotator instance (empty pool if no proxies configured).
        """
        proxy_str = os.getenv("PROXY_LIST", "")
        proxies = [p.strip() for p in proxy_str.split(",") if p.strip()]
        return cls(proxies)
    
    @property
    def is_enabled(self) -> bool:
        """Whether proxy rotation is active (at least one proxy configured)."""
        return self._enabled and len(self._alive_proxies) > 0
    
    @property
    def alive_count(self) -> int:
        """Number of currently alive proxies."""
        return len(self._alive_proxies)
    
    @property
    def dead_count(self) -> int:
        """Number of proxies that have been marked as dead."""
        return len(self._dead_proxies)
    
    def get_next_proxy(self) -> Optional[str]:
        """
        Get the next proxy URL in round-robin order.
        
        Returns:
            A proxy URL string, or None if no proxies are available.
        """
        if not self._alive_proxies:
            return None
        
        proxy = self._alive_proxies[self._current_index % len(self._alive_proxies)]
        self._current_index += 1
        
        # Log without exposing credentials
        parsed = urlparse(proxy)
        safe_display = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        logger.info(f"🔄 [PROXY]: Using proxy {safe_display}")
        
        return proxy
    
    def mark_proxy_dead(self, proxy: str) -> None:
        """
        Mark a proxy as dead (failed/unreachable). It will be skipped in future rotations.
        
        Args:
            proxy: The proxy URL to mark as dead.
        """
        if proxy in self._alive_proxies:
            self._alive_proxies.remove(proxy)
            self._dead_proxies.append(proxy)
            
            parsed = urlparse(proxy)
            safe_display = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            logger.warning(
                f"💀 [PROXY]: Marked {safe_display} as dead. "
                f"{len(self._alive_proxies)} proxies remaining."
            )
            
            if not self._alive_proxies:
                logger.warning("⚠️ [PROXY]: All proxies are dead! Falling back to direct connection.")
    
    def revive_all_proxies(self) -> None:
        """
        Move all dead proxies back to the alive pool.
        Useful for periodic retry — maybe they were just temporarily down.
        """
        if self._dead_proxies:
            self._alive_proxies.extend(self._dead_proxies)
            count = len(self._dead_proxies)
            self._dead_proxies.clear()
            logger.info(f"♻️ [PROXY]: Revived {count} dead proxies. Total alive: {len(self._alive_proxies)}")
    
    def get_playwright_proxy_config(self) -> Optional[dict]:
        """
        Get a proxy configuration dict compatible with Playwright's BrowserProfile.
        
        Returns:
            A dict like {"server": "http://proxy:8000", "username": "user", "password": "pass"}
            or None if no proxies are available.
        """
        proxy_url = self.get_next_proxy()
        
        if proxy_url is None:
            return None
        
        parsed = urlparse(proxy_url)
        
        config = {
            "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        }
        
        if parsed.username:
            config["username"] = parsed.username
        if parsed.password:
            config["password"] = parsed.password
        
        return config
    
    def get_status(self) -> dict:
        """
        Get a summary of the proxy pool status.
        
        Returns:
            Dict with alive/dead counts, enabled status, and proxy list (sanitized).
        """
        def sanitize(url: str) -> str:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        
        return {
            "enabled": self.is_enabled,
            "alive_count": self.alive_count,
            "dead_count": self.dead_count,
            "alive_proxies": [sanitize(p) for p in self._alive_proxies],
            "dead_proxies": [sanitize(p) for p in self._dead_proxies],
        }

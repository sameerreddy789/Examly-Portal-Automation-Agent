"""
stealth.py — Anti-Bot & TLS Fingerprinting Module

Provides two layers of anti-detection:
1. playwright-stealth: Injects scripts to hide automation signals (navigator.webdriver, etc.)
2. curl_cffi: Makes HTTP requests with real Chrome TLS fingerprints for direct scraping.

Usage:
    from stealth import apply_stealth, stealth_http_get

    # Apply stealth to a Playwright page
    await apply_stealth(page)

    # Make a stealth HTTP request (mimics Chrome TLS fingerprint)
    html = stealth_http_get("https://example.com")
"""

from typing import Optional
from loguru import logger
from playwright_stealth import Stealth

# Create a single Stealth instance for reuse
_stealth = Stealth()


async def apply_stealth(page) -> None:
    """
    Apply stealth scripts to a Playwright page to hide automation indicators.
    
    What this does:
    - Removes `navigator.webdriver = true` flag
    - Patches `navigator.plugins` and `navigator.languages` to look real
    - Hides Playwright-specific JS variables that bots detect
    - Makes the browser pass common bot-detection tests
    
    Call this on every new page BEFORE navigating to the target URL.
    """
    try:
        await _stealth.apply_stealth_async(page)
        logger.info("✅ [STEALTH]: Anti-detection scripts injected successfully.")
    except Exception as e:
        logger.warning(f"⚠️ [STEALTH]: Failed to apply stealth scripts: {e}")


def stealth_http_get(url: str, headers: Optional[dict] = None) -> str:
    """
    Make an HTTP GET request that mimics a real Chrome browser's TLS fingerprint.
    
    Why this matters:
    - Normal Python `requests.get()` has a TLS handshake that looks nothing like Chrome.
    - Cloudflare and Akamai check the TLS fingerprint (JA3/JA4) and block non-browser requests.
    - `curl_cffi` impersonates Chrome's exact TLS signature, so the request looks legitimate.
    
    Args:
        url: The URL to fetch.
        headers: Optional additional HTTP headers.
    
    Returns:
        The response body as a string.
    """
    from curl_cffi import requests as curl_requests
    
    default_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    }
    
    if headers:
        default_headers.update(headers)
    
    try:
        response = curl_requests.get(
            url,
            headers=default_headers,
            impersonate="chrome",  # Mimic Chrome's TLS fingerprint
            timeout=30,
        )
        logger.info(f"✅ [STEALTH HTTP]: GET {url} -> Status {response.status_code}")
        return response.text
    except Exception as e:
        logger.error(f"❌ [STEALTH HTTP]: Request to {url} failed: {e}")
        raise


async def stealth_http_post(url: str, data: Optional[dict] = None, 
                             json_data: Optional[dict] = None,
                             headers: Optional[dict] = None) -> str:
    """
    Make an HTTP POST request with Chrome TLS fingerprint impersonation.
    
    Args:
        url: The URL to POST to.
        data: Form data (if sending form-encoded).
        json_data: JSON body (if sending JSON).
        headers: Optional additional HTTP headers.
    
    Returns:
        The response body as a string.
    """
    from curl_cffi import requests as curl_requests
    
    default_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    
    if headers:
        default_headers.update(headers)
    
    try:
        response = curl_requests.post(
            url,
            headers=default_headers,
            data=data,
            json=json_data,
            impersonate="chrome",
            timeout=30,
        )
        logger.info(f"✅ [STEALTH HTTP]: POST {url} -> Status {response.status_code}")
        return response.text
    except Exception as e:
        logger.error(f"❌ [STEALTH HTTP]: POST to {url} failed: {e}")
        raise


def get_stealth_browser_args() -> list[str]:
    """
    Returns extra Chromium launch arguments that help avoid bot detection.
    
    These flags disable automation-revealing features in Chrome:
    - AutomationControlled: Removes the "Chrome is being controlled" infobar
    - enable-automation: Prevents setting `navigator.webdriver = true`
    - Various other fingerprinting and tracking vectors
    """
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-backgrounding-occluded-windows",
    ]

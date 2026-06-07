"""
visual_grounding.py — Multimodal Visual Coordinate Grounding

Instead of relying on CSS selectors (which break when websites change),
this module takes a screenshot and asks Gemini AI to find elements visually.

Think of it like showing someone a picture of a webpage and asking:
"Where is the Login button?" — they point to it, and we click there.

Usage:
    from visual_grounding import click_element_visually, find_element_coordinates

    # Click a button by describing what it looks like
    await click_element_visually(page, "the blue Login button")
    
    # Just get coordinates without clicking
    x, y = await find_element_coordinates(page, "the search bar at the top")
"""

import base64
import json
from loguru import logger
import re
from typing import Optional

from google import genai

logger = logger.bind(name="browser_use.visual_grounding")

# Gemini client (uses GOOGLE_API_KEY from environment automatically)
_client = None


def _get_client():
    """Lazy-initialize the Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


async def find_element_coordinates(page, element_description: str) -> Optional[tuple[float, float]]:
    """
    Takes a screenshot and asks Gemini to find the center coordinates of a described element.
    
    How it works:
    1. Takes a PNG screenshot of the current viewport
    2. Sends it to Gemini with a prompt like "find the Login button"
    3. Gemini returns X,Y coordinates as percentages (0-100)
    4. We convert those percentages to actual pixel coordinates
    
    Args:
        page: Playwright page object.
        element_description: Natural language description of the element to find.
            Example: "the blue Submit button", "the email input field", "the hamburger menu icon"
    
    Returns:
        Tuple of (x_pixels, y_pixels) if found, None if Gemini can't locate it.
    """
    try:
        # Take screenshot of what the browser currently shows
        screenshot_bytes = await page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        client = _get_client()
        
        # Ask Gemini to find the element
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                f"Look at this webpage screenshot. Find '{element_description}' in the image.\n\n"
                                "Return ONLY a JSON object with the center coordinates of that element as percentages "
                                "of the image dimensions (0 to 100).\n\n"
                                "Format: {\"x\": <number>, \"y\": <number>, \"found\": true}\n"
                                "If the element is not visible, return: {\"x\": 0, \"y\": 0, \"found\": false}\n\n"
                                "IMPORTANT: Return ONLY the JSON, no other text."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": screenshot_b64,
                            }
                        },
                    ],
                }
            ],
        )
        
        # Parse Gemini's response
        response_text = response.text.strip()
        
        # Try to extract JSON from the response (handle markdown code blocks too)
        json_match = re.search(r"\{[^}]+\}", response_text)
        if not json_match:
            logger.warning(f"⚠️ [VISUAL]: Could not parse coordinates from Gemini response: {response_text}")
            return None
        
        coords = json.loads(json_match.group())
        
        if not coords.get("found", False):
            logger.info(f"ℹ️ [VISUAL]: Gemini could not find '{element_description}' on the page.")
            return None
        
        x_percent = float(coords["x"])
        y_percent = float(coords["y"])
        
        # Sanity check — coordinates should be between 0 and 100
        if not (0 <= x_percent <= 100 and 0 <= y_percent <= 100):
            logger.warning(f"⚠️ [VISUAL]: Coordinates out of range: x={x_percent}, y={y_percent}")
            return None
        
        # Convert percentages to actual pixel coordinates
        viewport = page.viewport_size
        if not viewport:
            viewport = {"width": 1280, "height": 720}
        
        x_pixels = (x_percent / 100) * viewport["width"]
        y_pixels = (y_percent / 100) * viewport["height"]
        
        logger.info(
            f"🎯 [VISUAL]: Found '{element_description}' at ({x_pixels:.0f}, {y_pixels:.0f}) "
            f"[{x_percent:.1f}%, {y_percent:.1f}%]"
        )
        
        return (x_pixels, y_pixels)
        
    except Exception as e:
        logger.error(f"❌ [VISUAL]: Error finding '{element_description}': {e}")
        return None


async def click_element_visually(page, element_description: str, retry_count: int = 2) -> bool:
    """
    Find an element by visual description and click on it.
    
    This is the main function you'll use. It:
    1. Finds the element's coordinates using Gemini
    2. Moves the mouse there and clicks
    3. If it doesn't seem to work, retries with a new screenshot
    
    Args:
        page: Playwright page object.
        element_description: What the element looks like (e.g., "the red Delete button").
        retry_count: How many times to retry if the first attempt fails.
    
    Returns:
        True if clicked successfully, False if the element couldn't be found.
    """
    for attempt in range(retry_count + 1):
        coords = await find_element_coordinates(page, element_description)
        
        if coords is None:
            if attempt < retry_count:
                logger.info(f"🔄 [VISUAL]: Retry {attempt + 1}/{retry_count} — scrolling and trying again...")
                # Scroll down a bit in case the element is below the fold
                await page.evaluate("window.scrollBy(0, 300)")
                await page.wait_for_timeout(500)
                continue
            else:
                logger.error(f"❌ [VISUAL]: Could not find '{element_description}' after {retry_count + 1} attempts.")
                return False
        
        x, y = coords
        
        # Click at the coordinates
        try:
            await page.mouse.click(x, y)
            logger.info(f"✅ [VISUAL]: Clicked '{element_description}' at ({x:.0f}, {y:.0f})")
            return True
        except Exception as e:
            logger.error(f"❌ [VISUAL]: Click failed at ({x:.0f}, {y:.0f}): {e}")
            if attempt < retry_count:
                continue
            return False
    
    return False


async def visual_scroll_to(page, element_description: str, max_scrolls: int = 10) -> bool:
    """
    Scrolls the page until the described element becomes visible.
    
    How it works:
    - Takes a screenshot, asks Gemini "is this element visible?"
    - If not, scrolls down and checks again
    - Repeats up to max_scrolls times
    
    Args:
        page: Playwright page object.
        element_description: What to look for (e.g., "the Submit button at the bottom").
        max_scrolls: Maximum number of scroll attempts.
    
    Returns:
        True if the element was found after scrolling, False if not found.
    """
    for scroll_num in range(max_scrolls):
        coords = await find_element_coordinates(page, element_description)
        
        if coords is not None:
            logger.info(f"✅ [VISUAL SCROLL]: Found '{element_description}' after {scroll_num} scrolls.")
            return True
        
        # Scroll down by one viewport height
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
        await page.wait_for_timeout(800)  # Wait for content to load/render
        logger.info(f"📜 [VISUAL SCROLL]: Scroll {scroll_num + 1}/{max_scrolls} — looking for '{element_description}'...")
    
    logger.warning(f"⚠️ [VISUAL SCROLL]: Could not find '{element_description}' after {max_scrolls} scrolls.")
    return False


async def describe_page_visually(page) -> str:
    """
    Takes a screenshot and asks Gemini to describe what's on the page.
    
    Useful for debugging or when the agent needs to understand the current page state.
    
    Returns:
        A text description of what Gemini sees on the page.
    """
    try:
        screenshot_bytes = await page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        client = _get_client()
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "Describe what you see on this webpage screenshot. "
                                "Focus on: page title, main content area, visible buttons, "
                                "forms, navigation elements, and any popups or modals. "
                                "Be concise but thorough."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": screenshot_b64,
                            }
                        },
                    ],
                }
            ],
        )
        
        description = response.text.strip()
        logger.info(f"📝 [VISUAL]: Page description generated ({len(description)} chars)")
        return description
        
    except Exception as e:
        logger.error(f"❌ [VISUAL]: Error describing page: {e}")
        return f"Error: Could not describe page — {str(e)}"

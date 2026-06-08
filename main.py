import os
import sys
import asyncio
import argparse
import json
import re
import io

from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser.session import BrowserSession
from browser_use.browser.profile import BrowserProfile
from google import genai
from PIL import Image
from python_ghost_cursor.playwright_async import create_cursor

# New architecture modules
from stealth import apply_stealth, get_stealth_browser_args
from visual_grounding import click_element_visually, find_element_coordinates, visual_scroll_to, describe_page_visually
from session_store import SessionStore
from proxy import ProxyRotator
from hitl import HITLClient
from memory_manager import memory_manager
from parsers.crawlee_parser import extract_page_data_crawlee

# Set up logging configuration
from loguru import logger

class FallbackChatGoogle:
    """
    A custom wrapper class that satisfies the browser_use BaseChatModel Protocol.
    If the primary model fails, it seamlessly falls back to a secondary model.
    """
    _verified_api_keys = False

    def __init__(self, main_llm: ChatGoogle, fallback_llm: ChatGoogle):
        self.main_llm = main_llm
        self.fallback_llm = fallback_llm
        self.model = main_llm.model
        self.logger = logger.bind(name="browser_use.fallback_chat_google")

    @property
    def provider(self) -> str:
        return self.main_llm.provider

    @property
    def name(self) -> str:
        return self.main_llm.name

    @property
    def model_name(self) -> str:
        return self.main_llm.model_name

    async def ainvoke(self, messages, output_format=None, **kwargs):
        try:
            self.logger.info(f"Attempting call using primary model: {self.main_llm.model}")
            return await self.main_llm.ainvoke(messages, output_format=output_format, **kwargs)
        except Exception as e:
            self.logger.warning(
                f"Primary model {self.main_llm.model} failed: {e}. "
                f"Retrying and falling back to secondary model: {self.fallback_llm.model}"
            )
            return await self.fallback_llm.ainvoke(messages, output_format=output_format, **kwargs)

# Initialize Controller for custom actions
controller = Controller()

# Helper for synchronous blocking input in worker thread
def sync_get_user_input(prompt: str) -> str:
    print(f"\n\033[93m[AGENT CLARIFICATION NEEDED]: {prompt}\033[0m")
    return input(">> Your Response: ").strip()

@controller.action(
    description="Asks the user (Sir) a clarifying question in the terminal and waits for their input. "
                "Use this when you hit a coding question and need to know the preferred language, "
                "when you encounter ambiguity (e.g. two similar links), or when you need details not specified in the task."
)
async def request_user_input(question_prompt: str) -> str:
    response = await asyncio.to_thread(sync_get_user_input, question_prompt)
    return response

@controller.action(
    description="Saves a lesson learned, site-specific fix, or error-recovery workaround for future runs. "
                "Use this when you successfully bypass a bug, enable a disabled button, close a blocking overlay, "
                "or interact with a complex editor using custom JS."
)
def save_agent_knowledge(site_name: str, error_description: str, solution_javascript: str) -> str:
    observation = f"Error: {error_description}. Fix script: {solution_javascript}"
    memory_manager.store_knowledge(site_name, observation)
    return f"Successfully saved knowledge for {site_name}. It will be loaded automatically on next run."

@controller.action(
    description="Solves a text-based image CAPTCHA on the current webpage by screenshotting the image element and using Gemini AI."
)
async def solve_captcha_image(image_selector: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        element = await page.query_selector(image_selector)
        if not element:
            return f"Error: CAPTCHA image element with selector '{image_selector}' not found."
            
        screenshot_bytes = await element.screenshot()
        image = Image.open(io.BytesIO(screenshot_bytes))
        
        client = genai.Client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                image,
                "Identify the alphanumeric characters in this CAPTCHA image. "
                "Reply ONLY with the solved characters. Do not include spaces, "
                "punctuation, or any introductory/explanatory text. If there are Persian/Farsi digits, "
                "convert them to standard English digits. If no characters are clear, return an empty response."
            ]
        )
        
        solution = response.text.strip().replace(" ", "")
        logger.info(f"🤖 [CAPTCHA SOLVER]: Solved CAPTCHA as '{solution}'")
        return solution
    except Exception as e:
        logger.error(f"Error solving captcha: {e}")
        return f"Error: Failed to solve CAPTCHA due to: {str(e)}"

@controller.action(
    description="Clicks on an element using a human-like curved mouse path (ghost cursor) to bypass anti-bot systems."
)
async def human_click(selector: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        element = await page.query_selector(selector)
        if not element:
            return f"Error: Element with selector '{selector}' not found."
            
        cursor = await create_cursor(page)
        await cursor.click(element)
        logger.info(f"🖱️ [GHOST CURSOR]: Human-like click on '{selector}' completed.")
        return f"Successfully clicked element '{selector}' using human-like cursor movements."
    except Exception as e:
        logger.error(f"Error in human_click: {e}")
        return f"Error: Human-like click failed: {str(e)}"

@controller.action(
    description="Hovers over an element using a human-like curved mouse path (ghost cursor) to trigger hover behaviors."
)
async def human_hover(selector: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        element = await page.query_selector(selector)
        if not element:
            return f"Error: Element with selector '{selector}' not found."
            
        cursor = await create_cursor(page)
        await cursor.move_to(element)
        logger.info(f"🖱️ [GHOST CURSOR]: Human-like hover on '{selector}' completed.")
        return f"Successfully hovered over element '{selector}' using human-like cursor movements."
    except Exception as e:
        logger.error(f"Error in human_hover: {e}")
        return f"Error: Human-like hover failed: {str(e)}"

# ── Visual Grounding Actions ──────────────────────────────────────────────────

@controller.action(
    description="Clicks an element by visually describing it (e.g., 'the blue Login button'). "
                "Uses AI vision to find the element on a screenshot and click its coordinates. "
                "Use this when CSS selectors fail or the page layout has changed unexpectedly."
)
async def visual_click(element_description: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        success = await click_element_visually(page, element_description)
        if success:
            return f"Successfully clicked '{element_description}' using visual grounding."
        else:
            return f"Could not find '{element_description}' on the page visually."
    except Exception as e:
        logger.error(f"Error in visual_click: {e}")
        return f"Error: Visual click failed: {str(e)}"

@controller.action(
    description="Finds the pixel coordinates of an element by describing what it looks like. "
                "Returns the x,y position without clicking. Useful for inspecting element positions."
)
async def visual_find(element_description: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        coords = await find_element_coordinates(page, element_description)
        if coords:
            return f"Found '{element_description}' at pixel coordinates ({coords[0]:.0f}, {coords[1]:.0f})."
        else:
            return f"Could not find '{element_description}' on the page."
    except Exception as e:
        logger.error(f"Error in visual_find: {e}")
        return f"Error: Visual find failed: {str(e)}"

@controller.action(
    description="Extracts all text data efficiently from a specific CSS selector using Crawlee. "
                "Use this when you need to read a lot of text or scrape a list without taking screenshots."
)
async def scrape_text_data(url: str, selector: str = "body") -> str:
    try:
        logger.info(f"🕸️ Extracting text from {url} using selector {selector}")
        data = await extract_page_data_crawlee(url, selector)
        return f"Extracted Data:\n{data[:2000]}...\n[Truncated if too long]"
    except Exception as e:
        logger.error(f"Error in scrape_text_data: {e}")
        return f"Error: Scraping failed: {str(e)}"

@controller.action(
    description="Scrolls the page until a described element becomes visible. "
                "Use when you need to find something that might be below the fold."
)
async def visual_scroll(element_description: str, browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        found = await visual_scroll_to(page, element_description)
        if found:
            return f"Scrolled until '{element_description}' became visible."
        else:
            return f"Could not find '{element_description}' after scrolling the entire page."
    except Exception as e:
        logger.error(f"Error in visual_scroll: {e}")
        return f"Error: Visual scroll failed: {str(e)}"

@controller.action(
    description="Takes a screenshot and asks AI to describe everything visible on the current page. "
                "Use this when you're unsure what's on screen or need to understand the page layout."
)
async def visual_describe_page(browser_session: BrowserSession) -> str:
    try:
        page = await browser_session.get_current_page()
        description = await describe_page_visually(page)
        return f"Page description: {description}"
    except Exception as e:
        logger.error(f"Error in visual_describe_page: {e}")
        return f"Error: Could not describe page: {str(e)}"

# ── HITL (Human-in-the-Loop) Action ───────────────────────────────────────────

# Global HITL client instance (initialized in main)
_hitl_client: HITLClient | None = None

@controller.action(
    description="Pauses the bot and asks the human operator for help via the dashboard. "
                "Use this when stuck on a 3D CAPTCHA, complex verification, or any blocker "
                "that you absolutely cannot solve on your own. The bot will pause and wait "
                "for the user to respond through the HITL dashboard or terminal."
)
async def pause_for_human_help(reason: str, browser_session: BrowserSession) -> str:
    global _hitl_client
    try:
        page = await browser_session.get_current_page()
        if _hitl_client:
            response = await _hitl_client.pause_for_user(page, reason)
            if response:
                if response == "__FORCE_STOP__":
                    return "User requested force stop. Ending task."
                if response == "__SKIP__":
                    return "User skipped this step. Continuing with best effort."
                return f"User responded: {response}"
            else:
                return "No user response received (timed out). Continuing with best effort."
        else:
            # Fallback to terminal
            print(f"\n\033[93m[HITL]: {reason}\033[0m")
            response = await asyncio.to_thread(input, ">> Your Response: ")
            return f"User responded: {response.strip()}"
    except Exception as e:
        logger.error(f"Error in pause_for_human_help: {e}")
        return f"Error: HITL pause failed: {str(e)}"

# Load environment variables
load_dotenv()

async def main():
    print("\n--- AI Browser Agent Guided Intake Wizard ---")
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description="General-Purpose Browser Automation Agent with Self-Healing Memory")
    parser.add_argument("--url", help="Target website URL")
    parser.add_argument("--email", help="Login email")
    parser.add_argument("--password", help="Login password")
    parser.add_argument("--task", help="The goal or task description in plain English")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--user-data-dir", default="./agent_profile", help="Path to save cookies/session persistently")
    parser.add_argument("--restore-session", type=str, default=None, help="Restore a previously saved session by ID")
    parser.add_argument("--no-stealth", action="store_true", default=False, help="Disable stealth/anti-detection mode")
    parser.add_argument("--fresh-profile", action="store_true", default=False, help="Delete cached browser profile and start fresh")
    parser.add_argument("--queue", action="store_true", default=False, help="Dispatch task to Taskiq Redis worker queue instead of running locally")
    args, unknown = parser.parse_known_args()
    
    # 1. Determine Target Website URL
    target_url = args.url or os.getenv("TARGET_URL")
    if not target_url:
        target_url = input("Enter target website URL [default: https://mbu931.examly.io/]: ").strip()
    if not target_url:
        target_url = "https://mbu931.examly.io/"
        
    # 2. Determine Task/Goal
    task_goal = args.task
    if not task_goal:
        task_goal = input("What task would you like to perform today? (e.g. 'Take the Day 13 Assessment'): ").strip()
    while not task_goal:
        task_goal = input("Task is required. What would you like to do?: ").strip()

    # Determine platform/domain name
    from urllib.parse import urlparse
    parsed = urlparse(target_url)
    domain = parsed.netloc or parsed.path
    if domain.startswith("www."):
        domain = domain[4:]
    if "/" in domain:
        domain = domain.split("/")[0]
        
    print(f"\nDetecting requirements for site: {domain}...")
    
    # 3. Gather Credentials based on site
    domain_prefix = domain.split('.')[0].upper()
    env_email_key = f"{domain_prefix}_EMAIL"
    env_pass_key = f"{domain_prefix}_PASSWORD"
    
    if "examly" in domain.lower():
        email = args.email or os.getenv("EXAMLY_EMAIL")
        password = args.password or os.getenv("EXAMLY_PASSWORD")
    else:
        email = args.email or os.getenv(env_email_key) or os.getenv("EXAMLY_EMAIL")
        password = args.password or os.getenv(env_pass_key) or os.getenv("EXAMLY_PASSWORD")
        
    # Only ask if completely missing
    if not email:
        email = input(f"Enter username/email for {domain}: ").strip()
    if not password:
        password = input(f"Enter password for {domain}: ").strip()
            
    if not email or not password:
        print("Error: Email and password are required to run the agent.")
        return

    # For Examly, check if COURSE_NAME and TARGET_DATE are present
    course_name = ""
    target_date = ""
    if "examly" in domain.lower():
        course_name = os.getenv("COURSE_NAME")
        if not course_name:
            course_name = input("Enter Examly course name: ").strip()
            
        target_date = os.getenv("TARGET_DATE")
        day_match = re.search(r"Day\s*\d+", task_goal, re.IGNORECASE)
        if day_match:
            parsed_date = day_match.group(0)
            target_date = parsed_date
        if not target_date:
            target_date = input("Enter target assessment date (e.g. Day 13): ").strip()

    # Load persistent agent memory
    agent_memory_content = memory_manager.get_relevant_knowledge(domain)
    if not agent_memory_content:
        agent_memory_content = "None"

    # Check if the website is Examly to append specialized guidelines
    is_examly = "examly.io" in target_url.lower()
    
    # Base instructions based on user inputs
    task_instructions = f"""
    You are an automated browser assistant. Your goal is: '{task_goal}'
    
    Here is the starting configuration:
    - Target URL: {target_url}
    - Credentials: Email/Username is '{email}' and Password is '{password}'
    """
    
    if is_examly:
        task_instructions += f"""
    === EXAMLY PLATFORM SPECIAL RULES ===
    CRITICAL RULE: DO NOT open new tabs to search for answers. Tab switching is strictly tracked by the platform and will cause the test to auto-submit and fail. Do everything within the primary tab.

    1. Navigate to {target_url}
    2. On the login page, type the email '{email}' and click 'Next'.
    3. Wait for password page, type password '{password}' and click 'Login'.
    4. Once logged in, click 'Courses' in the sidebar. Find and open the course named exactly '{course_name}'.
    5. Find the dropdown for '{target_date}' and click it.
    6. Below that dropdown, click the specific assessment (e.g., '1. {target_date} Assessment').
    7. Click 'Take Test' / 'Resume Test'.
    8. Click 'Agree and proceed' (or similar) to accept the conditions.
    9. WAIT for the test to fully load.
    10. Once the test starts, check the available sections. Notice the 'Section' dropdown at the top (e.g., 'Section: 1/2'). For each question:
        - If it is a Multiple Choice Question (MCQ): Read the question, evaluate the options, select the correct answer, and move to the next question.
        - If it is a Coding (DSA) question: Read the entire problem statement, including expected inputs/outputs. Try to get the OPTIMIZED code solution, type/inject your code carefully into the code editor area, and run/verify it.
        - CRITICAL SECTION NAVIGATION: Once you complete a section, or if you are completely stuck and cannot solve the current question, you MUST click the 'Section' dropdown at the top of the page and select the next section.
    11. Proceed through all questions in all sections until the end.
    12. CRITICAL DATA SAVING REQUIREMENT: For EVERY question you solve, immediately append the question text and your answer (or injected code) into a local file named 'answers_{task_goal.replace(' ', '_')}.txt' using the 'write_file' or 'append_to_file' tool. Number them clearly.
    13. Once completed, click 'Submit Test', type the exact text 'END' into the confirmation box, and submit.
    """
    else:
        task_instructions += f"""
    === GENERAL PLATFORM RULES ===
    1. Navigate to {target_url}
    2. If the page is public and does not require signing in to complete the goal, skip steps 3 and 4 and proceed directly to step 5.
    3. Look for any 'Sign In', 'Log In', or user icon buttons. Click them.
    4. Enter the email '{email}' and password '{password}' in the corresponding login form inputs, then click 'Submit' or 'Login'.
    5. Search the page dynamically to locate the target elements required to complete: '{task_goal}'.
    6. Dynamically decide which elements to click, scroll, or input text into to progress towards the goal.
    """

    task_instructions += f"""
    === PERSISTENT WORKAROUNDS & LESSONS LEARNED ===
    Here are fixes and DOM selectors that were successfully used on previous runs on these sites:
    {agent_memory_content}
    
    If you encounter any of these errors on the corresponding sites, execute the provided 'fix_js' directly using 'evaluate' to bypass them!

    === CRITICAL TROUBLESHOOTING & SELF-HEALING PROTOCOLS ===
    If you get stuck, run into errors, or find things not working, use the following self-healing instructions:

    1. OPTIMIZED DSA CODE GENERATION:
       Before injecting any code into the editor for a coding/DSA question, you MUST ensure your solution is highly optimized for time and space complexity (e.g., O(N) or O(N log N) instead of O(N^2) where applicable).
       The code MUST be flawless, handle edge cases, and compile without errors. Double-check your logic before generating the final string.

    2. MONACO CODE EDITOR INJECTION:
       Do NOT try to type code line-by-line using basic keyboard inputs or by modifying standard input text fields. The Monaco Editor requires setting values directly on its internal model.
       To inject code, execute a custom JavaScript function using the 'evaluate' tool:
       ```javascript
       (function() {{
           try {{
               if (window.monaco && window.monaco.editor) {{
                   const models = window.monaco.editor.getModels();
                   if (models && models.length > 0) {{
                       models[0].setValue(`YOUR_CODE_HERE`);
                       const textarea = document.querySelector('.monaco-editor textarea');
                       if (textarea) textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                       return "Monaco updated successfully";
                   }}
               }}
               // Fallback: search for editable areas
               const el = document.querySelector('textarea, div[contenteditable="true"]');
               if (el) {{
                   el.value = `YOUR_CODE_HERE`;
                   el.innerText = `YOUR_CODE_HERE`;
                   el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                   return "Standard editor updated";
               }}
               return "No editor found";
           }} catch(e) {{
               return "Error: " + e.toString();
           }}
       }})()
       ```

    2. DISMISSING BLOCKING MODALS & DIALOGS:
       If any warning alerts, confirmation modals, or loading overlay backdrops block the screen, immediately click 'Yes', 'Okay', or 'Close'.
       If a modal cannot be dismissed or is stuck, run this JavaScript via 'evaluate' to forcefully remove all blocking overlays and restore screen usability:
       ```javascript
       const overlays = document.querySelectorAll('.modal-backdrop, .modal, [class*="modal"], [id*="modal"]');
       overlays.forEach(el => el.remove());
       document.body.classList.remove('modal-open');
       ```

    3. ENABLING DISABLED BUTTONS:
       If the 'Compile & Run' or 'Submit Code' buttons remain disabled (even after you've entered the code), run this JavaScript via 'evaluate' to force-enable them:
       ```javascript
       const compileBtn = document.getElementById('programme-compile');
       if (compileBtn) compileBtn.disabled = false;
       const submitBtn = document.getElementById('tt-footer-submit-answer') || document.getElementById('tt-footer-submit-ans');
       if (submitBtn) submitBtn.disabled = false;
       ```

    4. ASK USER FOR CLARIFICATION:
       If you encounter a coding question and the preferred programming language is not specified in the task description or previous memory, or if you run into any ambiguity or blocker that you cannot confidently solve on your own, you MUST call 'request_user_input' to ask the user (Sir) for clarification. The process will pause and wait for the user's response in the terminal. Do NOT try to guess.

    5. RECORDING BUGS & WORKAROUNDS:
       If you encounter any new site-specific error, blocker, or element interaction bug, and you find a successful workaround or custom JS script to solve it, you MUST document the fix immediately by calling the tool 'save_agent_knowledge'. Specify the site name (domain), the error details, and the JS script that resolved it.

    6. CAPTCHA & ANTI-BOT BYPASS PROTOCOLS:
       If you encounter an image-based text CAPTCHA, locate the CAPTCHA image element and its corresponding text input field. Use the 'solve_captcha_image' action with the CAPTCHA image's selector to get the solved text, then input it into the text field. If the website has aggressive anti-bot protections (like Cloudflare, etc.), use the 'human_click' and 'human_hover' actions to interact with links, buttons, and inputs in a realistic, human-like manner rather than using default clicks/hovers.

    7. VISUAL GROUNDING (AI VISION FALLBACK):
       If you cannot find an element using CSS selectors, or if the page layout seems different from what you expect, use the visual actions:
       - 'visual_click': Describe the element you want to click in plain English (e.g., "the blue Login button" or "the Submit button at the bottom"). The AI will take a screenshot, find it visually, and click it.
       - 'visual_find': Describe an element to get its pixel coordinates without clicking.
       - 'visual_scroll': Describe an element and the page will scroll until it's visible.
       - 'visual_describe_page': Get an AI-generated description of everything currently visible on screen. Use this when you're confused about the page state.
       These visual tools are your LAST RESORT when normal selectors fail.

    8. HUMAN-IN-THE-LOOP (HITL) ESCALATION:
       If you encounter a problem you absolutely cannot solve on your own (e.g., complex 3D CAPTCHA, multi-step verification, or any blocker where even visual grounding fails), call 'pause_for_human_help' with a clear description of why you're stuck. The bot will pause and show a screenshot on the dashboard so the human can help. Only use this as a last resort after trying other approaches.
    """

    # Set up models: gemini-3.1-flash-lite as main, and gemini-1.5-flash as fallback for rate limits / 503s
    main_llm = ChatGoogle(
        model="gemini-3.1-flash-lite", 
        max_retries=5, 
        retry_base_delay=3.0, 
        retry_max_delay=30.0
    )
    fallback_llm = ChatGoogle(
        model="gemma-4-31b", 
        max_retries=5, 
        retry_base_delay=3.0, 
        retry_max_delay=30.0
    )
    llm = FallbackChatGoogle(main_llm, fallback_llm)

    # ── Initialize Proxy Rotation ─────────────────────────────────────────────
    proxy_rotator = ProxyRotator.from_env()
    proxy_config = proxy_rotator.get_playwright_proxy_config() if proxy_rotator.is_enabled else None
    
    if proxy_config:
        print(f"[PROXY] Proxy rotation enabled with {proxy_rotator.alive_count} proxies.")
    else:
        print("[PROXY] No proxies configured. Using direct connection.")

    # ── Initialize BrowserProfile with Stealth & Proxy ───────────────────────
    stealth_args = get_stealth_browser_args() if not args.no_stealth else ["--disable-blink-features=AutomationControlled"]
    
    # Handle --fresh-profile: delete old cached profile to start clean
    user_data_dir = args.user_data_dir
    if args.fresh_profile and os.path.exists(user_data_dir):
        import shutil
        print(f"[CLEANUP] Deleting old browser profile at '{user_data_dir}'...")
        shutil.rmtree(user_data_dir, ignore_errors=True)
        print("[CLEANUP] Fresh profile will be created.")
    
    browser_profile_kwargs = dict(
        headless=args.headless,
        user_data_dir=user_data_dir,
        disable_security=False,
        args=stealth_args,
    )
    
    # Add proxy if configured
    if proxy_config:
        browser_profile_kwargs["proxy"] = proxy_config
    
    browser_profile = BrowserProfile(**browser_profile_kwargs)
    browser = BrowserSession(browser_profile=browser_profile)

    # ── Initialize Session Store ─────────────────────────────────────────────
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    session_store = SessionStore(redis_host=redis_host, redis_port=redis_port)

    # ── Initialize HITL Client ───────────────────────────────────────────────
    global _hitl_client
    _hitl_client = HITLClient()
    _hitl_client.update_state("RUNNING", f"Starting task: {task_goal}")

    # ── Initialize the Agent ─────────────────────────────────────────────────
    agent = Agent(
        task=task_instructions,
        llm=llm,
        controller=controller,
        browser=browser,
        max_failures=10,
        max_actions_per_step=5,
    )
    
    # ── Apply Stealth & Restore Session ──────────────────────────────────────
    print(f"\nFiring up the browser and starting task '{task_goal}' on '{target_url}'...")
    
    if not args.no_stealth:
        print("[STEALTH] Stealth mode: ENABLED (anti-bot protections active)")
    
    # Run the agent (either locally or via Taskiq worker queue)
    if args.queue:
        from tasks import broker, run_browser_agent_task
        print("[QUEUE] Dispatching job to Taskiq Redis queue...")
        await broker.startup()
        task = await run_browser_agent_task.kiq(task_instructions, target_url)
        print(f"[+] Job enqueued successfully. Task ID: {task.task_id}")
        print("[!] Ensure you have a Taskiq worker running: 'taskiq worker tasks:broker'")
        await broker.shutdown()
        return
    else:
        result = await agent.run()
    
    # ── Post-Run: Backup Session ─────────────────────────────────────────────
    try:
        # Generate a session ID from the domain
        session_id = domain.replace(".", "_")
        browser_context = browser.browser_context
        if browser_context:
            await session_store.backup_session(browser_context, session_id)
            print(f"[SESSION] Session backed up as '{session_id}'")
        else:
            logger.warning("Could not backup session: browser context not available")
    except Exception as e:
        logger.warning(f"Could not backup session: {e}")
    
    # ── Update HITL State ────────────────────────────────────────────────────
    print("\n--- Agent Execution Finished ---")
    if result.is_successful():
        print("Success! Final result:")
        _hitl_client.update_state("COMPLETED", "Task completed successfully!")
    else:
        print("Agent finished (or stopped). Final message:")
        _hitl_client.update_state("COMPLETED", "Task finished (may not have fully succeeded).")
    
    # Safely print the final result without dumping massive objects to Windows terminal
    final_output = result.final_result()
    if final_output:
        print(final_output.encode('ascii', 'ignore').decode('ascii'))
    else:
        print("No final output string returned.")

if __name__ == "__main__":
    asyncio.run(main())

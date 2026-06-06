import os
import sys
import asyncio
import logging
import argparse
import json

from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle, Controller
from browser_use.agent.views import ActionResult

# Set up logging configuration
logging.basicConfig(level=logging.INFO)

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
        self.logger = logging.getLogger("browser_use.fallback_chat_google")

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

@controller.action(
    description="Saves a lesson learned, site-specific fix, or error-recovery workaround for future runs. "
                "Use this when you successfully bypass a bug, enable a disabled button, close a blocking overlay, "
                "or interact with a complex editor using custom JS."
)
def save_agent_knowledge(site_name: str, error_description: str, solution_javascript: str) -> str:
    import json
    import os
    
    file_path = "agent_memory.json"
    memory = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                memory = json.load(f)
        except Exception:
            pass
            
    if site_name not in memory:
        memory[site_name] = []
        
    # Prevent duplicate saves of the same JS solution for the same error
    existing_fixes = memory[site_name]
    if not any(f.get("fix_js") == solution_javascript for f in existing_fixes):
        memory[site_name].append({
            "error": error_description,
            "fix_js": solution_javascript
        })
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=4)
        return f"Successfully saved knowledge for {site_name}. It will be loaded automatically on next run."
    
    return f"Fix for {site_name} already exists in persistent memory."

# Load environment variables
load_dotenv()

async def main():
    print("\n--- General-Purpose & Self-Healing Agent Setup ---")
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description="General-Purpose Browser Automation Agent with Self-Healing Memory")
    parser.add_argument("--url", help="Target website URL (default: Examly)")
    parser.add_argument("--email", help="Login email")
    parser.add_argument("--password", help="Login password")
    parser.add_argument("--task", help="The goal or task description in plain English")
    args, unknown = parser.parse_known_args()

    # Determine URL
    target_url = args.url or os.getenv("TARGET_URL") or "https://mbu931.examly.io/"
    
    # Determine Credentials
    email = args.email or os.getenv("EXAMLY_EMAIL")
    password = args.password or os.getenv("EXAMLY_PASSWORD")
    
    # If credentials are not set, ask for them interactively
    if not email:
        email = input("Enter email/username: ").strip()
    if not password:
        password = input("Enter password: ").strip()
        
    if not email or not password:
        print("Error: Email and password are required to run the agent.")
        return

    # Determine Task
    task_goal = args.task
    if not task_goal:
        print(f"\nTarget website: {target_url}")
        print(f"Logged in as: {email}")
        task_goal = input("\nWhat task would you like me to perform today? (e.g., 'Take the Day 13 Assessment' or 'Download Week 1 syllabus from Coursera'): ").strip()
        
    if not task_goal:
        print("Error: A task description is required.")
        return

    # Load persistent agent memory
    agent_memory_content = "None"
    memory_file = "agent_memory.json"
    if os.path.exists(memory_file):
        try:
            with open(memory_file, "r", encoding="utf-8") as f:
                memory_data = json.load(f)
                agent_memory_content = json.dumps(memory_data, indent=2)
        except Exception:
            pass

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
        course_name = os.getenv("COURSE_NAME", "2028_MBU_60 days Skill Development Assessment Course")
        target_date = os.getenv("TARGET_DATE", "Day 13")
        
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
    12. Once completed, click 'Submit Test', type the exact text 'END' into the confirmation box, and submit.
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

    1. MONACO CODE EDITOR INJECTION:
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

    4. RECORDING BUGS & WORKAROUNDS:
       If you encounter any new site-specific error, blocker, or element interaction bug, and you find a successful workaround or custom JS script to solve it, you MUST document the fix immediately by calling the tool 'save_agent_knowledge'. Specify the site name (domain), the error details, and the JS script that resolved it.
    """

    # Set up models: gemini-3.1-flash-lite as main, and gemini-2.5-flash as fallback for 503s
    main_llm = ChatGoogle(
        model="gemini-3.1-flash-lite", 
        max_retries=5, 
        retry_base_delay=3.0, 
        retry_max_delay=30.0
    )
    fallback_llm = ChatGoogle(
        model="gemini-2.5-flash", 
        max_retries=5, 
        retry_base_delay=3.0, 
        retry_max_delay=30.0
    )
    llm = FallbackChatGoogle(main_llm, fallback_llm)

    # Initialize the agent
    agent = Agent(
        task=task_instructions,
        llm=llm,
        controller=controller,
        max_failures=10,
        max_actions_per_step=5,
    )
    
    # Run the agent
    print(f"\nFiring up the browser and starting task '{task_goal}' on '{target_url}'...")
    result = await agent.run()
    
    print("\n--- Agent Execution Finished ---")
    if result.is_successful():
        print("Success! Final result:")
    else:
        print("Agent finished (or stopped). Final message:")
    
    # Safely print the final result without dumping massive objects to Windows terminal
    final_output = result.final_result()
    if final_output:
        print(final_output.encode('ascii', 'ignore').decode('ascii'))
    else:
        print("No final output string returned.")

if __name__ == "__main__":
    asyncio.run(main())

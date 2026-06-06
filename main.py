import os
import asyncio
import logging

from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle

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

# Load environment variables
load_dotenv()

async def main():
    print("\n--- Examly Auto-Solver Setup ---")
    
    # Get inputs from environment variables
    email = os.getenv("EXAMLY_EMAIL")
    password = os.getenv("EXAMLY_PASSWORD")
    course_name = os.getenv("COURSE_NAME")
    target_date = os.getenv("TARGET_DATE")

    # Check if all required variables are set
    if not all([email, password, course_name, target_date]):
        print("Error: Missing required environment variables.")
        print("Please check your .env file and ensure EXAMLY_EMAIL, EXAMLY_PASSWORD, COURSE_NAME, and TARGET_DATE are set.")
        return
    
    print("\nInitializing Browser Agent with Gemini 3.1 Flash Lite (Native Wrapper)...")
    
    # Construct the highly detailed task prompt
    task_instructions = f"""
    You are an automated exam-taking assistant. Follow these exact steps carefully. 
    CRITICAL RULE: DO NOT open new tabs to search for answers. Tab switching is strictly tracked by the platform and will cause the test to auto-submit and fail. Do everything within the primary tab.

    1. Navigate to https://mbu931.examly.io/
    2. On the login page, type the email '{email}' into the Email field and click 'Next'.
    3. Wait for the password page to appear. Type the password '{password}' into the Password field and click 'Login'.
    4. Once logged in, you will be on the dashboard/courses page. Find and open the course named exactly '{course_name}'.
    5. On the course page, look at the left-side menu. Find the section for '{target_date}' and click its dropdown button.
    6. Below that dropdown, click the specific assessment button (e.g., '1. {target_date} Assessment').
    7. The right side of the page will update. Click the 'Take Test' button.
    8. Click 'Agree and proceed' (or similar) to accept the conditions.
    9. WAIT for the test to fully load. 
    10. Once the test starts, check the available sections. Notice the 'Section' dropdown at the top (e.g., 'Section: 1/2'). For each question:
        - If it is a Multiple Choice Question (MCQ): Read the question, evaluate the options, select the correct answer, and move to the next question.
        - If it is a Coding (DSA) question: Read the entire problem statement, including the expected inputs and outputs. Try to get the OPTIMIZED code solution for the question, type your code carefully into the code editor area, and run/verify it.
        - CRITICAL SECTION NAVIGATION: Once you complete a section, or if you are completely stuck and cannot solve the current question, you MUST click the 'Section' dropdown at the top of the page and select the next section.
    11. Proceed through all questions in all sections until the end.
    12. Once all questions are completed, find and click the final 'Submit Test' button.
    13. A dialog box will appear asking for confirmation. You MUST type the exact text 'END' into that confirmation box, and then click 'Yes' or 'Submit' to finally submit.
    14. Do not stop execution until the test is fully submitted and you see the completion screen.

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
       If any warning alerts, confirmation modals, or loading overlay backdrops block the screen (e.g. when clearing code or due to alert popups), immediately click 'Yes', 'Okay', or 'Close'.
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
        max_failures=10,
        max_actions_per_step=5,
    )
    
    # Run the agent
    print(f"\nFiring up the browser and starting '{course_name}' for '{target_date}'...")
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

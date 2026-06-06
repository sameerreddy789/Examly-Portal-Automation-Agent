import os
import asyncio

from dotenv import load_dotenv
from browser_use import Agent, ChatGoogle

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
    """

    # Initialize the agent — using gemini-3.1-flash-lite for high free tier limits and agentic support
    agent = Agent(
        task=task_instructions,
        llm=ChatGoogle(
            model="gemini-3.1-flash-lite", 
            max_retries=10, 
            retry_base_delay=5.0, 
            retry_max_delay=60.0
        ),
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

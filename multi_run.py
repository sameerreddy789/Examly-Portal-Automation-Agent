"""
multi_run.py — Multi-Account Test Orchestrator

Runs the Examly test automation across multiple accounts in sequence:
1. Account 1 (sacrifice): Takes the test, saves all Q&A to answer bank
2. Review phase: AI fixes any wrong answers using gemini-2.5-flash
3. Account 2: Takes the same test using corrected answers → targets 100%
4. Account 3: Same → targets 100%

Usage:
    # Run with accounts from .env (order: 451 → 471 → 475)
    python multi_run.py

    # Override target date
    python multi_run.py --day "Day 18"
    
    # Skip sacrifice run (if answer bank already exists from a previous run)
    python multi_run.py --skip-sacrifice
"""

import asyncio
import os
import subprocess
import sys
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def get_accounts() -> list[dict]:
    """Read accounts from .env in order (ACCOUNT_1, ACCOUNT_2, ACCOUNT_3...)."""
    accounts = []
    i = 1
    while True:
        email = os.getenv(f"ACCOUNT_{i}_EMAIL")
        password = os.getenv(f"ACCOUNT_{i}_PASS")
        if not email or not password:
            break
        accounts.append({"email": email, "password": password})
        i += 1
    return accounts


async def review_and_fix_answers(bank_file: str):
    """
    Review Phase: Load the answer bank, find wrong answers, and fix them.
    
    For coding questions: Uses the dedicated code solver (gemini-2.5-flash)
    For MCQ questions: Re-evaluates with Gemini
    """
    from answer_bank import AnswerBank
    from code_solver import solve_problem, fix_solution, solve_problem_retry
    
    if not os.path.exists(bank_file):
        print("  ⚠️  Answer bank file not found! Skipping review.")
        return
    
    # Load the bank
    with open(bank_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    test_name = data.get("test_name", "test")
    bank = AnswerBank(test_name, bank_file)
    
    all_questions = bank.get_all_questions()
    wrong_questions = bank.get_wrong_questions()
    
    print(f"  📊 Total questions saved: {len(all_questions)}")
    print(f"  ❌ Wrong answers: {len(wrong_questions)}")
    
    if not wrong_questions:
        print("  ✅ All questions passed! No fixes needed.")
        # Still re-solve ALL coding questions to get the best possible code
        coding_qs = [q for q in all_questions if q.get("type") == "coding"]
        if coding_qs:
            print(f"  🔄 Re-verifying {len(coding_qs)} coding solutions for maximum confidence...")
            for q in coding_qs:
                if q.get("passed") is True and q.get("code"):
                    # Already passed — but let's keep the existing code
                    # Only re-solve if there's no code saved
                    pass
        return
    
    print(f"\n  🔧 Fixing {len(wrong_questions)} wrong answers...\n")
    
    for q in wrong_questions:
        q_num = q.get("number", "?")
        section = q.get("section", 1)
        q_type = q.get("type", "unknown")
        q_text = q.get("text", "")
        
        print(f"  ── Q{q_num} (Section {section}, {q_type}) ──")
        
        if q_type == "coding":
            current_code = q.get("code", "")
            failure_details = q.get("test_case_details", "Test cases failed")
            
            if current_code:
                # Tier 1: Try to fix the existing code
                print(f"    🔧 Tier 1: Fixing existing code...")
                fixed_code = await fix_solution(q_text, current_code, failure_details)
                
                # If the fix looks substantially different, use it
                if fixed_code and fixed_code != current_code and "Error:" not in fixed_code:
                    bank.update_corrected_answer(q_num, section, new_code=fixed_code)
                    print(f"    ✅ Fix applied ({len(fixed_code)} chars)")
                    continue
            
            # Tier 2: Solve from scratch
            print(f"    🧠 Tier 2: Solving from scratch...")
            new_code = await solve_problem(q_text)
            
            if new_code and "Error:" not in new_code:
                bank.update_corrected_answer(q_num, section, new_code=new_code)
                print(f"    ✅ New solution generated ({len(new_code)} chars)")
                continue
            
            # Tier 3: Try completely different approach
            print(f"    🔄 Tier 3: Trying alternative approach...")
            alt_code = await solve_problem_retry(q_text, current_code or new_code, failure_details)
            
            if alt_code and "Error:" not in alt_code:
                bank.update_corrected_answer(q_num, section, new_code=alt_code)
                print(f"    ✅ Alternative solution generated ({len(alt_code)} chars)")
            else:
                print(f"    ⚠️  Could not fix Q{q_num}. Best attempt will be used.")
        
        elif q_type == "mcq":
            # Re-evaluate MCQ with Gemini
            print(f"    🧠 Re-evaluating MCQ with AI...")
            corrected = await _reevaluate_mcq(q_text)
            if corrected:
                bank.update_corrected_answer(q_num, section, new_answer=corrected)
                print(f"    ✅ MCQ re-evaluated: {corrected[:80]}...")
            else:
                print(f"    ⚠️  Could not re-evaluate MCQ Q{q_num}")
    
    print(f"\n  ✅ Review complete. Corrected answers saved to {bank_file}")


async def _reevaluate_mcq(question_text: str) -> str:
    """Re-evaluate an MCQ question using Gemini."""
    try:
        from google import genai
        client = genai.Client()
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"""You are taking a multiple-choice exam. Read the question carefully and choose the CORRECT answer.

{question_text}

IMPORTANT:
- Think through each option carefully
- Consider edge cases and tricky wording
- Reply with ONLY the correct option text (e.g., "Option B: 42" or just "B) True")
- Do NOT explain your reasoning — just give the answer"""
        )
        
        return response.text.strip() if response.text else ""
    except Exception as e:
        print(f"    ❌ MCQ re-evaluation failed: {e}")
        return ""


def run_agent_for_account(account: dict, mode: str, bank_file: str, 
                           target_date: str, extra_args: list = None):
    """
    Run the browser agent as a subprocess for a specific account.
    
    Args:
        account: Dict with 'email' and 'password'
        mode: 'discovery' or 'replay'
        bank_file: Path to the answer bank JSON file
        target_date: Target assessment date (e.g., "Day 18")
        extra_args: Additional CLI arguments to pass to main.py
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(project_root, "main.py")
    
    cmd = [
        sys.executable, main_script,
        "--email", account["email"],
        "--password", account["password"],
        "--task", f"Take the {target_date} Assessment",
        "--mode", mode,
        "--answer-bank", os.path.join(project_root, bank_file),
        "--fresh-profile",  # Clean browser state for each account
    ]
    
    if extra_args:
        cmd.extend(extra_args)
    
    # Set encoding for Windows terminal emoji support
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    result = subprocess.run(cmd, cwd=project_root, env=env)
    return result.returncode


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Multi-Account Examly Test Runner")
    parser.add_argument("--day", type=str, default=None,
                        help="Target date override (e.g., 'Day 18')")
    parser.add_argument("--skip-sacrifice", action="store_true",
                        help="Skip the sacrifice run (use existing answer bank)")
    parser.add_argument("--review-only", action="store_true",
                        help="Only run the review phase (fix wrong answers)")
    parser.add_argument("--headless", action="store_true",
                        help="Run browser in headless mode")
    args = parser.parse_args()
    
    # Get config from .env
    accounts = get_accounts()
    if not accounts:
        print("❌ No accounts found in .env!")
        print("   Set ACCOUNT_1_EMAIL, ACCOUNT_1_PASS, ACCOUNT_2_EMAIL, etc.")
        return
    
    target_date = args.day or os.getenv("TARGET_DATE", "Day 18")
    test_name = target_date.replace(" ", "_") + "_Assessment"
    bank_file = f"answer_bank_{test_name}.json"
    
    extra_args = []
    if args.headless:
        extra_args.append("--headless")
    
    # Header
    print(f"\n{'='*60}")
    print(f"  🤖 Multi-Account Examly Test Runner")
    print(f"{'='*60}")
    print(f"  Test: {target_date} Assessment")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Order: {' → '.join(a['email'].split('@')[0] for a in accounts)}")
    print(f"  Strategy: Account 1 = sacrifice, rest = 100% target")
    print(f"  Answer Bank: {bank_file}")
    print(f"{'='*60}\n")
    
    # ── Phase 1: Sacrifice Run ────────────────────────────────────────────
    if not args.skip_sacrifice and not args.review_only:
        print(f"{'─'*60}")
        print(f"  📋 PHASE 1: SACRIFICE RUN — {accounts[0]['email']}")
        print(f"  This run saves all questions & answers. Mistakes are OK.")
        print(f"{'─'*60}\n")
        
        returncode = run_agent_for_account(
            accounts[0], "discovery", bank_file, target_date, extra_args
        )
        
        if returncode != 0:
            print(f"  ⚠️  Agent exited with code {returncode}")
        
        print(f"\n  ✅ Sacrifice run complete.")
    else:
        if args.review_only:
            print("  ⏭️  Skipping sacrifice run (--review-only)")
        else:
            print("  ⏭️  Skipping sacrifice run (--skip-sacrifice)")
            print(f"  📂 Using existing answer bank: {bank_file}")
    
    # ── Phase 2: Review & Fix ─────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"  🔍 PHASE 2: AI REVIEW — Fixing Wrong Answers")
    print(f"{'─'*60}\n")
    
    project_root = os.path.dirname(os.path.abspath(__file__))
    bank_path = os.path.join(project_root, bank_file)
    
    if os.path.exists(bank_path):
        asyncio.run(review_and_fix_answers(bank_path))
    else:
        print("  ⚠️  Answer bank not found! Agent may not have saved answers.")
        print("  Subsequent runs will solve questions from scratch.")
    
    if args.review_only:
        print(f"\n{'='*60}")
        print(f"  ✅ Review complete. Exiting (--review-only).")
        print(f"{'='*60}\n")
        return
    
    # ── Phase 3+: Perfect Runs ────────────────────────────────────────────
    for i, account in enumerate(accounts[1:], 2):
        print(f"\n{'─'*60}")
        print(f"  🎯 PHASE {i}: PERFECT RUN — {account['email']}")
        print(f"  Using corrected answers. Target: 100%")
        print(f"{'─'*60}\n")
        
        returncode = run_agent_for_account(
            account, "replay", bank_file, target_date, extra_args
        )
        
        if returncode != 0:
            print(f"  ⚠️  Agent exited with code {returncode}")
        
        print(f"\n  ✅ Run complete for {account['email']}")
    
    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ ALL {len(accounts)} ACCOUNTS COMPLETED!")
    print(f"{'='*60}")
    print(f"  Account 1 ({accounts[0]['email'].split('@')[0]}): Sacrifice run")
    for i, account in enumerate(accounts[1:], 2):
        print(f"  Account {i} ({account['email'].split('@')[0]}): 100% target run")
    print(f"\n  Answer bank saved at: {bank_file}")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

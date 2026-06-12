"""
code_solver.py — Dedicated DSA/Competitive Coding Solver

Uses gemini-2.5-flash (full thinking model) specifically for solving coding questions.
This is separate from the navigation LLM (gemini-3.1-flash-lite) because coding problems
require deep algorithmic reasoning that lightweight models can't handle.

Think of it like having two brains:
- Navigation brain (lite model): Clicks buttons, reads pages, navigates the website
- Coding brain (this module): Solves DSA problems with optimal algorithms

Usage:
    from code_solver import solve_problem, fix_solution
    
    # Solve a new problem
    code = await solve_problem("Given an array...", language="cpp")
    
    # Fix a failing solution
    fixed_code = await fix_solution(
        problem="Given an array...", 
        current_code="...", 
        failure="Expected: 5, Got: 3",
        language="cpp"
    )
"""

import re
from google import genai
from loguru import logger

logger = logger.bind(name="browser_use.code_solver")

# Lazy-initialized Gemini client (reuses the same GOOGLE_API_KEY from .env)
_client = None


def _get_client():
    """Lazy-initialize the Gemini client."""
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _extract_code(response_text: str, language: str = "cpp") -> str:
    """
    Extract clean, ready-to-paste code from the AI response.
    
    The AI might return code wrapped in markdown fences like:
        ```cpp
        #include <bits/stdc++.h>
        ...
        ```
    
    This function strips all that and returns just the raw code.
    """
    # Pattern 1: Code in markdown fences with language tag
    lang_aliases = {
        "cpp": r"(?:cpp|c\+\+|cc|cxx)",
        "c": r"(?:c)",
        "python": r"(?:python|py|python3)",
        "java": r"(?:java)",
    }
    lang_pattern = lang_aliases.get(language, language)
    
    # Try language-specific code block first
    match = re.search(
        rf"```{lang_pattern}\s*\n(.*?)```", 
        response_text, 
        re.DOTALL | re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    
    # Pattern 2: Generic code block (no language specified)
    match = re.search(r"```\s*\n(.*?)```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Pattern 3: No code blocks — try to find code by looking for C++ markers
    lines = response_text.strip().split('\n')
    code_start_markers = [
        '#include', 'using namespace', 'int main', 'class ', 'struct ',
        'void ', 'typedef ', '#define', '#pragma',
        # Python markers
        'def ', 'import ', 'from ', 'class ',
        # Java markers  
        'public class', 'import java',
    ]
    
    code_started = False
    code_lines = []
    
    for line in lines:
        stripped = line.strip()
        if not code_started:
            if any(stripped.startswith(marker) for marker in code_start_markers):
                code_started = True
                code_lines.append(line)
        else:
            # Stop if we hit obvious non-code text (explanation paragraphs)
            if stripped and not any(c in stripped for c in ['{', '}', ';', '(', ')', '#', '//', '/*', '*/', '=', '+', '-', '<', '>', '[', ']', '"', "'", 'return', 'if', 'else', 'for', 'while', 'int', 'long', 'void', 'char', 'string', 'vector', 'cout', 'cin', 'endl', 'include', 'using', 'namespace', 'auto', 'const', 'bool', 'true', 'false', 'null', 'NULL', 'nullptr', 'class', 'struct', 'public', 'private', 'template', 'typename', 'sizeof', 'break', 'continue', 'switch', 'case', 'default', 'do', 'try', 'catch', 'throw', 'new', 'delete', 'static', 'virtual', 'override', 'map', 'set', 'queue', 'stack', 'priority_queue', 'pair', 'unordered', 'sort', 'max', 'min', 'abs', 'swap', 'push', 'pop', 'insert', 'erase', 'find', 'begin', 'end', 'size', 'empty', 'front', 'back', 'first', 'second', '\t', '  ']):
                # This line doesn't look like code — might be end of code section
                # But only break if it's a long line that looks like prose
                if len(stripped) > 40 and ' ' in stripped and not stripped.startswith('//'):
                    break
            code_lines.append(line)
    
    if code_lines:
        return '\n'.join(code_lines).strip()
    
    # Last resort: return the entire response (maybe the model returned just code)
    return response_text.strip()


def _get_response_text(response) -> str:
    """
    Safely extract text from a Gemini API response.
    Handles both standard and thinking model response formats.
    """
    try:
        # Standard approach
        return response.text
    except Exception:
        pass
    
    try:
        # Fallback: access candidates directly
        for candidate in response.candidates:
            for part in reversed(candidate.content.parts):
                if hasattr(part, 'text') and part.text:
                    return part.text
    except Exception:
        pass
    
    return ""


async def solve_problem(problem_statement: str, language: str = "cpp") -> str:
    """
    Solve a coding problem using gemini-2.5-flash with deep algorithmic reasoning.
    
    This is the main entry point. Pass the COMPLETE problem statement (including
    sample inputs/outputs and constraints) and get back clean, optimal code.
    
    Args:
        problem_statement: The COMPLETE problem text including sample I/O and constraints.
        language: Programming language (default: "cpp" for C++).
    
    Returns:
        Clean, ready-to-paste code string (no markdown, no explanations).
    """
    client = _get_client()
    
    lang_name = {
        "cpp": "C++", "c": "C", "python": "Python", "java": "Java"
    }.get(language, language)
    
    prompt = f"""You are a world-class competitive programmer (Codeforces Legendary Grandmaster level).
Solve this coding problem in {lang_name}. Your solution MUST pass ALL test cases including hidden ones.

=== PROBLEM ===
{problem_statement}
=== END PROBLEM ===

MANDATORY REQUIREMENTS FOR {lang_name.upper()} CODE:
1. Use the MOST EFFICIENT algorithm possible. Analyze constraints to determine required complexity.
2. For C++:
   - Start with: #include <bits/stdc++.h> and using namespace std;
   - Add fast I/O: ios_base::sync_with_stdio(false); cin.tie(NULL);
   - Use 'long long' for ANY value that could exceed 2^31 (sums, products, large counts)
   - Use '\\n' instead of endl (faster output flushing)
3. Read input from stdin (cin), write output to stdout (cout).
4. Output EXACTLY what the problem asks — no extra text like "Enter:", "Result:", "Answer:" etc.
5. Match the output format PRECISELY:
   - Check if outputs should be space-separated or newline-separated
   - Check for trailing spaces or newlines
   - Check if there should be a newline at the very end
6. Handle ALL edge cases:
   - Empty input / zero-length arrays
   - Single element
   - Maximum constraint values (watch for overflow!)
   - Negative numbers if applicable
   - Duplicate values
7. The code must compile with C++14 or C++17 standard without warnings.

ALGORITHM SELECTION (match the problem pattern):
- Counting subsequences/subsets → DP (NOT brute force enumeration)
- Shortest path in graph → BFS (unweighted) or Dijkstra (weighted)
- Subarray sum / window → Sliding window or prefix sums
- String matching → KMP or Z-algorithm (NOT O(n*m) naive)
- Palindrome → DP or Manacher's algorithm
- Range queries → Segment tree, BIT, or sparse table
- Sorting-based → merge sort, quicksort, or STL sort
- Greedy → sort + greedy selection with proof
- Tree DP → DFS with memoization
- Combinatorics → modular arithmetic with fast exponentiation

THINK THROUGH THESE STEPS:
1. What is the problem asking? (Restate in one sentence)
2. What are the constraints? (Determines required time complexity)
3. What algorithm pattern does this match?
4. What are the edge cases?
5. Mentally trace through Sample Input 1 to verify your approach works.
6. Write the code.

OUTPUT: Return ONLY the complete {lang_name} code. No explanations, no markdown fences, no comments about the approach — JUST the raw code that can be directly compiled and run."""

    try:
        logger.info("🧠 [CODE SOLVER]: Generating initial solution with gemini-2.5-flash...")
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        raw_response = _get_response_text(response)
        
        if not raw_response:
            logger.error("❌ [CODE SOLVER]: Empty response from gemini-2.5-flash")
            return f"// Error: Empty response from code solver"
        
        code = _extract_code(raw_response, language)
        
        logger.info(f"✅ [CODE SOLVER]: Generated {lang_name} solution ({len(code)} chars, {code.count(chr(10))+1} lines)")
        return code
        
    except Exception as e:
        logger.error(f"❌ [CODE SOLVER]: Failed to solve problem: {e}")
        return f"// Error: Code solver failed — {str(e)}"


async def fix_solution(problem_statement: str, current_code: str, 
                        failure_details: str, language: str = "cpp") -> str:
    """
    Fix a failing solution by analyzing the test case failure.
    
    Instead of blindly rewriting from scratch, this analyzes what went wrong
    and makes targeted fixes. If the algorithm is fundamentally wrong, it
    will replace it entirely.
    
    Args:
        problem_statement: The original problem text.
        current_code: The code that's currently failing.
        failure_details: What went wrong — expected vs actual output, error messages, etc.
        language: Programming language (default: "cpp").
    
    Returns:
        Fixed code string ready to paste.
    """
    client = _get_client()
    
    lang_name = {
        "cpp": "C++", "c": "C", "python": "Python", "java": "Java"
    }.get(language, language)
    
    prompt = f"""You are a world-class competitive programmer debugging a failing solution.

=== PROBLEM ===
{problem_statement}
=== END PROBLEM ===

=== CURRENT FAILING CODE ===
{current_code}
=== END CODE ===

=== FAILURE DETAILS ===
{failure_details}
=== END FAILURE ===

DEBUG CHECKLIST — Check each one systematically:
1. INTEGER OVERFLOW: Are any intermediate calculations exceeding int range? Should int be long long?
2. OFF-BY-ONE: Are loop bounds correct? (< vs <=, 0-indexed vs 1-indexed)
3. I/O FORMAT: Does the output format EXACTLY match expectations? (spaces, newlines, trailing whitespace)
4. INPUT PARSING: Is ALL input being read correctly? Any leftover data in the buffer?
5. EDGE CASES: Does the code handle n=0, n=1, negative values, empty strings?
6. WRONG ALGORITHM: Is the fundamental approach incorrect? (e.g., greedy when DP is needed)
7. COMPARISON OPERATORS: Are < and <= used correctly? > and >= ?
8. ARRAY BOUNDS: Are array accesses within valid ranges?
9. UNINITIALIZED VARIABLES: Are all variables properly initialized?
10. MODULAR ARITHMETIC: If the answer should be modulo 10^9+7, is it applied correctly everywhere?

INSTRUCTIONS:
- If the bug is a small fix (overflow, off-by-one, format): Make the targeted fix.
- If the algorithm is FUNDAMENTALLY WRONG: Rewrite with the correct approach.
- Mentally trace your fixed code through the failing test case to verify it produces the correct output.
- The fixed code must still handle ALL other test cases correctly.

OUTPUT: Return ONLY the fixed {lang_name} code. No explanations — just the corrected code ready to compile."""

    try:
        logger.info("🔧 [CODE SOLVER]: Analyzing failure and generating fix with gemini-2.5-flash...")
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        raw_response = _get_response_text(response)
        
        if not raw_response:
            logger.error("❌ [CODE SOLVER]: Empty response when trying to fix solution")
            return current_code  # Return original if fix generation fails
        
        code = _extract_code(raw_response, language)
        
        logger.info(f"🔧 [CODE SOLVER]: Generated fix ({len(code)} chars, {code.count(chr(10))+1} lines)")
        return code
        
    except Exception as e:
        logger.error(f"❌ [CODE SOLVER]: Failed to fix solution: {e}")
        return current_code  # Return original code if fix fails


async def solve_problem_retry(problem_statement: str, previous_code: str,
                               all_failure_details: str, language: str = "cpp") -> str:
    """
    Last-resort retry: solve the problem from scratch using a completely different approach.
    
    This is called when both the initial solve and the fix attempts have failed.
    It explicitly tells the AI to try a DIFFERENT algorithm than what was used before.
    
    Args:
        problem_statement: The original problem text.
        previous_code: The code that was tried (to avoid using the same approach).
        all_failure_details: All accumulated failure information.
        language: Programming language (default: "cpp").
    
    Returns:
        New code string using a different approach.
    """
    client = _get_client()
    
    lang_name = {
        "cpp": "C++", "c": "C", "python": "Python", "java": "Java"
    }.get(language, language)
    
    prompt = f"""You are a world-class competitive programmer. A previous solution to this problem FAILED.
You must solve it using a COMPLETELY DIFFERENT algorithmic approach.

=== PROBLEM ===
{problem_statement}
=== END PROBLEM ===

=== PREVIOUS FAILED APPROACH (DO NOT USE THIS SAME APPROACH) ===
{previous_code}
=== END FAILED CODE ===

=== WHY IT FAILED ===
{all_failure_details}
=== END FAILURE INFO ===

CRITICAL: The previous approach is WRONG. You must:
1. Identify why the previous approach fails
2. Choose a FUNDAMENTALLY DIFFERENT algorithm
3. Consider these alternative strategies:
   - If previous used greedy → try DP
   - If previous used DP → try different DP state definition or greedy
   - If previous used brute force → use efficient algorithm
   - If previous had edge case issues → handle them explicitly
4. Pay EXTREME attention to I/O format — match it EXACTLY
5. Handle ALL edge cases including the ones that caused the failure

For C++:
- #include <bits/stdc++.h> and using namespace std;
- Fast I/O: ios_base::sync_with_stdio(false); cin.tie(NULL);
- Use long long where needed
- Use '\\n' not endl

OUTPUT: Return ONLY the complete {lang_name} code. No explanations — just raw code."""

    try:
        logger.info("🔄 [CODE SOLVER]: Last resort — regenerating solution with different approach...")
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        
        raw_response = _get_response_text(response)
        
        if not raw_response:
            logger.error("❌ [CODE SOLVER]: Empty response on retry attempt")
            return previous_code
        
        code = _extract_code(raw_response, language)
        
        logger.info(f"🔄 [CODE SOLVER]: Generated alternative solution ({len(code)} chars, {code.count(chr(10))+1} lines)")
        return code
        
    except Exception as e:
        logger.error(f"❌ [CODE SOLVER]: Retry failed: {e}")
        return previous_code

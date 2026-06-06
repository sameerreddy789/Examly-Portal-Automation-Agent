# 🤖 Browser Automation Agent

A general-purpose, self-healing browser automation agent built on top of [browser-use](https://github.com/browser-use/browser-use). It is designed to navigate complex websites, solve captchas, mimic human interaction to bypass anti-bot detections, and dynamically request clarification from the user when stuck.

---

## 🚀 Key Features & Agent Skills

This browser agent is equipped with several custom capabilities (skills) integrated into the automation flow:

### 1. 📂 Persistent Session Storage
- Automatically launching Chromium with a persistent browser profile (`./agent_profile`).
- Saves cookies, session details, and local storage variables between consecutive runs. This avoids needing to log in repeatedly on target websites.

### 2. 🛡️ Anti-Bot & Automation Bypass
- **Automation Detection Shield**: Launches Chrome with `--disable-blink-features=AutomationControlled` arguments to bypass default bot detection.
- **Spoofed User-Agent**: Impersonates a real human browser with a modern User-Agent header string.
- **Human Cursor Emulation**: Uses `python-ghost-cursor` to generate realistic, curved Bezier mouse paths for clicking (`human_click`) and hovering (`human_hover`) rather than teleporting the cursor.

### 3. 🧩 AI Captcha Solver
- Exposes `solve_captcha_image` custom action.
- Directly screenshots the CAPTCHA element inside Playwright and utilizes the Gemini API to resolve alphanumeric characters without making extra, suspicious HTTP requests.

### 4. 🧠 Self-Healing Site Knowledge
- Automatically loads and applies persistent site fixes from `agent_memory.json`.
- The agent writes custom javascript workarounds (e.g., dismissing stubborn overlays, enabling disabled buttons, writing code directly to Monaco editors) using `save_agent_knowledge` to heal itself on subsequent runs.

### 5. 💬 Non-Blocking Console Clarifications
- Implements `request_user_input` custom action.
- If the agent faces a coding question with an unspecified language, or runs into any ambiguity, it pauses execution and prompts you in the terminal.
- Uses a background worker thread (`asyncio.to_thread`) to handle console inputs, keeping the main Playwright loop and WebSocket browser connection fully alive without timing out.

### 6. 🔀 Dual LLM Fallback Engine
- Employs a custom `FallbackChatGoogle` client.
- Uses the state-of-the-art `gemini-3.1-flash-lite` model as the primary driver.
- If Gemini 3.1 experiences a 503 high demand spike, it gracefully falls back to `gemini-1.5-flash` to ensure the task finishes successfully.

---

## 🛠️ Setup & Installation

Ensure you have Python 3.13+ and [uv](https://github.com/astral-sh/uv) installed.

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/sameerreddy789/Browser_Automation.git
   cd Browser_Automation
   ```

2. **Sync Dependencies**:
   Initialize the virtual environment and sync dependencies:
   ```bash
   uv sync
   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   EXAMLY_EMAIL=your_examly_email
   EXAMLY_PASSWORD=your_examly_password
   COURSE_NAME="Your Examly Course Name"
   TARGET_DATE="Day 13"
   ```

---

## 💻 Running the Agent

You can start the guided intake wizard by running:
```powershell
# For Windows PowerShell (to support Unicode characters like Rupee symbol)
$env:PYTHONUTF8="1"; uv run python main.py
```

### Command Line Arguments
You can also pass arguments directly to bypass the intake wizard prompts:
```bash
uv run python main.py \
  --url "https://hack2skill.com/" \
  --task "Find and list active online hackathons." \
  --headless
```

- `--url`: Target website URL.
- `--task`: Plain English task description.
- `--email`: Login email (optional).
- `--password`: Login password (optional).
- `--headless`: Run the browser in invisible headless mode (defaults to headful/visible).
- `--user-data-dir`: Custom path to save browser session files (defaults to `./agent_profile`).

---

## 📁 Repository Structure

- [main.py](file:///d:/Projects/Web%20Dev/Current/Browser%20agent/main.py): Core entrypoint containing the guided wizard, model setups, and custom agent actions.
- [pyproject.toml](file:///d:/Projects/Web%20Dev/Current/Browser%20agent/pyproject.toml) & [uv.lock](file:///d:/Projects/Web%20Dev/Current/Browser%20agent/uv.lock): Python dependencies and build parameters.
- [agent_memory.json](file:///d:/Projects/Web%20Dev/Current/Browser%20agent/agent_memory.json) *(Git ignored)*: Local knowledge store containing self-healed site selectors.
- [agent_profile/](file:///d:/Projects/Web%20Dev/Current/Browser%20agent/agent_profile/) *(Git ignored)*: Persistent Chrome user profile data containing login cookies.

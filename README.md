# 🤖 Browser Automation Agent

A general-purpose, self-healing browser automation agent powered by [browser-use](https://github.com/browser-use/browser-use) and Google Gemini. Give it a website and a task in plain English — it opens a real browser, navigates pages, fills forms, solves CAPTCHAs, and completes the job autonomously.

Built with a layered defense system: **stealth anti-bot evasion**, **AI-powered visual grounding**, **human-in-the-loop fallback**, **proxy rotation**, and **persistent session storage** — making it resilient against modern bot detection, layout changes, and IP blocks.

---

## ✨ What It Does

1. **You describe a task** — *"Log into Examly, take the Day 13 Assessment, answer all questions, and submit."*
2. **The agent opens a real Chromium browser** with stealth protections enabled (hidden automation flags, spoofed fingerprints).
3. **It navigates, clicks, types, and reads pages** using an AI brain (Gemini) that decides what to do next at every step.
4. **When selectors break**, it falls back to **visual grounding** — takes a screenshot, asks Gemini *"where is the Login button?"*, and clicks the coordinates.
5. **When it gets completely stuck** (3D CAPTCHA, complex verification), it **pauses and alerts you** via a live dashboard so you can help.
6. **Sessions persist across runs** — cookies are saved so you don't re-login every time.

---

## 🚀 Key Features

### 🛡️ Anti-Bot & Stealth Engine
- **playwright-stealth v2**: Injects scripts to hide `navigator.webdriver`, patch plugins/languages, and pass bot-detection tests.
- **TLS Fingerprint Impersonation**: Uses `curl_cffi` for HTTP requests that mimic Chrome's exact JA3/JA4 TLS handshake — Cloudflare/Akamai can't distinguish them from real browsers.
- **Human Cursor Emulation**: `python-ghost-cursor` generates realistic Bezier-curve mouse paths for clicks and hovers.
- **Stealth Browser Args**: Disables automation-revealing Chromium features (`AutomationControlled`, infobars, etc.).

### 🎯 Visual Grounding (AI Vision)
When CSS selectors fail (website redesigns, dynamic content), the agent "sees" the page:
- **`visual_click`** — Describe the element in plain English (*"the blue Submit button"*), and the AI finds and clicks it by screenshot.
- **`visual_find`** — Get pixel coordinates of any described element.
- **`visual_scroll`** — Scroll until a described element appears.
- **`visual_describe_page`** — Get a full AI description of what's on screen.

### 🤝 Human-in-the-Loop (HITL) Dashboard
A local **Streamlit** web dashboard connected to **PocketBase** for real-time monitoring and intervention:
- Live screenshot stream of the bot's current view.
- Bot pauses automatically when stuck (complex CAPTCHAs, verification).
- Text input for you to type CAPTCHA solutions or instructions.
- Emergency controls (force stop, reset state).
- Falls back to terminal input if the dashboard isn't running.

### 🔀 Proxy Rotation
- Configure a pool of proxies in `.env` — the agent rotates through them per-session.
- Dead proxy tracking: failed proxies are automatically skipped.
- Uses Playwright's native proxy support (no mitmproxy dependency).
- Gracefully falls back to direct connection when no proxies are configured.

### 💾 Persistent Session Storage
- **Browser Profile Persistence**: Chromium profile saved to `./agent_profile` — cookies, localStorage, and session data survive restarts.
- **Redis + JSON Backup**: After each run, cookies are backed up to Redis (if available) or local JSON files. Restore with `--restore-session`.
- Sessions are shareable across machines via Redis.

### 🧩 AI CAPTCHA Solver
- Screenshots the CAPTCHA element directly inside Playwright.
- Sends it to Gemini for OCR — no suspicious external API calls.
- Supports alphanumeric and Persian/Farsi digit CAPTCHAs.

### 🧠 Adaptive Memory (Mem0)
- The agent utilizes `mem0ai` as a long-term vector database (ChromaDB) to map and track user preferences and successful DOM interactions.
- Successfully learned site-specific logic and Javascript workarounds persist dynamically across tasks without bloated JSON states.

### ⚡ Distributed Asynchronous Queue (Taskiq)
- Optional Taskiq integration to isolate the Playwright browser context into an independent asynchronous Python worker task.
- Enqueue jobs seamlessly backed by Redis.

### 📝 Comprehensive Logging (Loguru)
- Advanced JSON-based structured logging deployed across all automation workers via `loguru`.
- Enables rapid granular diagnostics of LLM reasoning, proxy rotation, and network interception.

### 🕸️ Token-Efficient Parsing (Crawlee)
- Integrates `crawlee` when massive text data or lists need to be extracted efficiently.
- Bypasses expensive screenshot ingestion and LLM coordinate hallucinations for purely structural data extraction.

### 🔀 Dual LLM Fallback
- Primary: `gemini-3.1-flash-lite` (fast, cheap).
- Fallback: `gemini-1.5-flash` (if primary hits rate limits or 503s).
- Seamless switching — no task interruption.

---

## 🛠️ Setup & Installation

**Requirements**: Python 3.13+ and [uv](https://github.com/astral-sh/uv).

### 1. Clone & Install

```bash
git clone https://github.com/sameerreddy789/Browser_Automation.git
cd Browser_Automation
uv sync
```

### 2. Configure Environment

Create a `.env` file (see [.env.example](.env.example)):

```env
# Required
GOOGLE_API_KEY=your_gemini_api_key

# Credentials (per-site)
EXAMLY_EMAIL=your_email
EXAMLY_PASSWORD=your_password
COURSE_NAME="2028_MBU..."
TARGET_DATE="Day 5"

# Optional: Proxy rotation (comma-separated)
PROXY_LIST=http://user:pass@proxy1.com:8000,http://user:pass@proxy2.com:8000

# Optional: Redis for session sync
REDIS_HOST=localhost
REDIS_PORT=6379

# Optional: PocketBase for HITL dashboard
POCKETBASE_URL=http://127.0.0.1:8090
```

### 3. Set Up HITL Dashboard (Optional)

```bash
# Download PocketBase and create the required collection
python hitl/setup_pocketbase.py
```

---

## 💻 Running the Agent

### Quick Start (All Services)
```bash
# Launches PocketBase + Streamlit Dashboard + Agent
python run.py --url "https://example.com" --task "Do something"
```

### Agent Only
```powershell
# Windows PowerShell (Unicode support)
$env:PYTHONIOENCODING="utf-8"; uv run python main.py
```

### Command Line Arguments
```bash
uv run python main.py \
  --url "https://example.com" \
  --task "Find and list active hackathons" \
  --headless \
  --restore-session example_com
```

| Flag | Description |
|------|-------------|
| `--url` | Target website URL |
| `--task` | Plain English task description |
| `--email` | Login email |
| `--password` | Login password |
| `--headless` | Run browser invisibly (default: visible) |
| `--user-data-dir` | Browser profile path (default: `./agent_profile`) |
| `--restore-session` | Restore a saved session by ID (e.g., `examly_io`) |
| `--no-stealth` | Disable anti-bot stealth mode |
| `--queue` | Dispatch task to Taskiq Redis worker queue instead of running locally |

### Launcher Flags (run.py only)
| Flag | Description |
|------|-------------|
| `--no-dashboard` | Skip launching the Streamlit dashboard |
| `--no-pocketbase` | Skip launching PocketBase |

---

## 📁 Repository Structure

```
Browser_Automation/
├── main.py                    # Core agent: wizard, LLM setup, all controller actions
├── run.py                     # All-in-one launcher (PocketBase + Streamlit + Agent)
├── stealth.py                 # Anti-bot: playwright-stealth, curl_cffi, browser args
├── visual_grounding.py        # Gemini vision: find/click elements by screenshot
├── session_store.py           # Redis/JSON session backup and restore
├── memory_manager.py          # Mem0 long-term graph/vector memory integration
├── tasks.py                   # Taskiq asynchronous Redis worker queue definitions
├── hitl/                      # Human-in-the-Loop system
│   ├── pocketbase_client.py   # Bot ↔ PocketBase state management
│   ├── dashboard.py           # Streamlit monitoring dashboard
│   └── setup_pocketbase.py    # One-time PocketBase download & setup
├── proxy/                     # Proxy management
│   ├── rotator.py             # Round-robin proxy pool with dead tracking
│   └── mitm_addon.py          # mitmproxy addon for programmatic evasion and telemetry blocking
├── parsers/                   # Alternate data parsing engines
│   └── crawlee_parser.py      # Token-efficient DOM extraction using crawlee
├── agent_profile/             # Persistent Chromium profile (git-ignored)
├── sessions/                  # Local JSON session backups (git-ignored)
├── agent_mem0_db/             # Local ChromaDB vector database for Mem0 (git-ignored)
├── pyproject.toml             # Python dependencies (managed by uv)
└── .env                       # Environment config (git-ignored)
```

---

## 📄 License

[Apache 2.0](LICENSE)

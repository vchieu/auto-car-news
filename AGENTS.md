# AGENTS.md - Auto Car News Bot Guidance

## Project Overview
`auto-car-news` is an automated Python application that scrapes automotive news from RSS feeds (e.g., VnExpress, Tuổi Trẻ, Thanh Niên), synthesizes and analyzes the content using AI (Gemini or OpenAI-compatible proxy), and automatically posts curated market summaries to a Facebook Fanpage.

---

## Key Tech Stack & Libraries
- **Language**: Python 3.x
- **RSS Parsing**: `feedparser`
- **HTML Parsing**: `beautifulsoup4`
- **AI Providers**: `google-genai` (Gemini API) / `openai` (OpenAI or OpenAI-compatible proxies such as OpenRouter, vLLM)
- **Facebook Graph API**: `requests` (dynamic API version, default `v19.0`)
- **File Locking**: `filelock` (race condition prevention for `seen_urls.json`)
- **Retry Mechanism**: `tenacity` (exponential backoff retries for AI and Facebook API calls)
- **Scheduling**: `schedule` / Cronjob / Windows Task Scheduler

---

## Project Structure
```
auto-car-news/
├── config.json          # Main runtime configuration (ignored by git)
├── config.example.json  # Configuration template
├── seen_urls.json       # Persisted state tracking published articles (dict {"url": timestamp}, generated at runtime)
├── requirements.txt     # Python dependencies
├── main.py              # Main entry point & execution flow controller
├── config_loader.py     # Centralized configuration management (validation, defaults, API version helper)
├── scraper.py           # RSS fetching & clean-up module (with filelock-based seen_urls tracking)
├── analyzer.py          # AI analysis & post generation module (with tenacity retry, token limits)
├── fb_poster.py         # Facebook Graph API posting module (with tenacity retry, dynamic API version)
├── logs/                # Daily application logs
├── README.md            # Comprehensive documentation
└── AGENTS.md            # AI Agent project guidance & rules
```

---

## Environment Setup & Commands

### Environment Setup
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# One-off execution (for Cronjob / Task Scheduler / Manual trigger)
python main.py

# Continuous loop mode (Daemon mode)
python main.py --daemon
# or
python main.py -d

# Test individual modules
python scraper.py
python analyzer.py
```

---

## Core Architecture & Workflow Rules

### 1. Centralized Configuration Management (`config_loader.py`)
   - **Single source of truth** for all configuration loading across modules.
   - Exposes three public helpers:
     - [`load_config()`](config_loader.py:1): Reads `config.json` using absolute pathing (`BASE_DIR`), validates required sections (`rss_sources`, `facebook`, `settings`), and merges sensible fallback defaults for missing optional keys (e.g., `api_version`, `max_articles_per_source`, `ai_timeout`). If `config.json` is missing, initializes an empty dict and lets Env Vars supply the configuration (Docker/Kubernetes friendly).
     - [`get_facebook_api_version()`](config_loader.py:1): Returns the configured Facebook Graph API version string (e.g., `"v19.0"`) so `fb_poster.py` never hardcodes the version.
     - `ConfigurationError` (custom exception): Raised by `load_config()` for invalid/missing required configuration. `main.py` catches this and exits gracefully with non-zero code.
   - **Environment Variable Override**: `load_config()` checks `os.environ` for `GEMINI_API_KEY`, `OPENAI_API_KEY`, `FB_ACCESS_TOKEN`, `FB_PAGE_ID` and **overrides** the values from `config.json` when set. This enables secure cloud deployments on Docker, GitHub Actions, Render, Railway, etc. without hardcoding secrets in `config.json`.
   - All modules (`scraper.py`, `analyzer.py`, `fb_poster.py`, `main.py`) **MUST** import `load_config` from `config_loader` rather than re-implementing JSON loading.
   - Supports `ai_provider`: `"gemini"` or `"openai"`.
   - `load_config()` **NEVER calls `sys.exit()` directly**; it raises `ConfigurationError` instead. This makes the module testable and allows other modules to handle configuration errors.

### 2. Execution Flow
   - [`scraper.fetch_latest_news()`](scraper.py:1): Reads RSS feeds, filters out URLs present in `seen_urls.json`, and discards articles older than 48 hours.
   - [`analyzer.generate_analysis_post(articles)`](analyzer.py:1): Formats articles (truncates summaries to 300 chars, caps at 15 articles per call) and prompts the configured AI provider to write a Vietnamese Facebook summary post.
   - [`fb_poster.post_to_facebook(message)`](fb_poster.py:1): Publishes the content to Facebook Fanpage via the **dynamically resolved** Graph API version.
   - [`scraper.mark_urls_as_seen(articles)`](scraper.py:1): **Atomic updates** — URLs are marked as seen **ONLY AFTER** successful posting to Facebook to ensure retry safety on failure.

### 3. Race Condition Prevention (`seen_urls.json`)
   - `seen_urls.json` is stored as a **dict of `{url: timestamp}`** (Unix timestamp as float), not a flat list — this enables time-based cleanup.
   - All reads and writes are wrapped in a [`FileLock("seen_urls.json.lock")`](scraper.py:1) (from the `filelock` package) so multiple daemon instances or simultaneous Cronjob + daemon runs cannot corrupt the file.
   - **Atomic Read-Merge-Write**: The entire `save_seen_urls()` operation (read current data → merge new URLs → cleanup → write) is performed inside a **single** FileLock to prevent data loss when multiple processes run simultaneously.
   - On every write, an automatic **60-day cleanup** removes URLs whose timestamp is older than 60 days, keeping the JSON file bounded in size without arbitrary 1000-entry caps.
   - Cleanup logic includes `isinstance(timestamp, (int, float))` check to handle edge cases where file might contain invalid data types.
   - If file lock acquisition times out, a `RuntimeError` is raised (instead of silently returning `{}`) to prevent the bot from re-posting all old articles.

### 4. Retry Mechanism (`tenacity`)
   - Both [`analyzer.generate_analysis_post()`](analyzer.py:1) and [`fb_poster.post_to_facebook()`](fb_poster.py:1) are decorated with a [`@retry()`](analyzer.py:1) decorator from `tenacity`:
     - **3 attempts** total (initial + 2 retries).
     - **Exponential backoff** between attempts to gracefully handle transient network/AI provider failures.
     - **Hard timeout** on AI SDK clients (OpenAI `timeout=30.0`, Gemini `http_options={"timeout": 30.0}`) prevents indefinite socket blocking when tenacity's decorator cannot kick in due to upstream issues.
     - Logs each retry attempt via the module-level logger so transient failures are visible in `logs/app.log` (current) or `logs/app.log.YYYYMMDD` (rotated).
   - Retries are intended for **transient** failures only:
     - **Retry**: `ConnectionError`, `Timeout`, HTTP 5xx from Facebook server.
     - **No retry**: HTTP 4xx (invalid token, bad request), permanent API errors.
   - **Gemini Safety Block Handling**: If `response.text` raises `ValueError` (due to safety filter blocking), the error is caught and returns empty string, allowing graceful degradation instead of crash.

### 5. Logging & Diagnostics
   - Each module declares its own logger: `logger = logging.getLogger(__name__)`.
   - All `print()` calls have been replaced with structured `logger.info()` / `logger.warning()` / `logger.error()` / `logger.critical()` calls.
   - Logs are output to stdout and appended to rotating log files (`logs/app.log`).
   - **`TimedRotatingFileHandler`** is used for automatic daily log rotation at midnight, with 30-day retention. This ensures long-running daemons don't accumulate unbounded log files.
   - Levels used: `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

### 6. Token / Payload Limits
   - `analyzer.py` enforces:
     - **Summary truncation**: each article summary is truncated to **300 characters** before being sent to the AI to avoid token blow-up on long RSS descriptions.
     - **Article cap**: at most **15 articles** are sent per AI call to keep prompt size predictable.

---

## Code Style & Development Guidelines

- **Path Handling**: Always build paths relative to `BASE_DIR = os.path.dirname(os.path.abspath(__file__))` to guarantee reliability across Cron, Task Scheduler, and CLI contexts.
- **Configuration Loading**: Always use [`from config_loader import load_config, get_facebook_api_version`](config_loader.py:1). Do **not** re-implement JSON loading in any module.
- **Error Handling**: Surround API calls and network requests in try/except blocks. Never fail silently without logging the error details. Wrap AI / Facebook calls with `tenacity` retry decorators for transient failures.
- **Concurrency Safety**: Any code that reads or writes `seen_urls.json` **MUST** be guarded by `filelock.FileLock`. Do not bypass this lock even for "simple" reads.
- **UTF-8 Encoding**: Explicitly pass `encoding='utf-8'` when reading or writing files.
- **Language & Tone**: AI prompts and user-facing logs are in Vietnamese.
- **Configuration Fallbacks**: Handle missing optional config keys gracefully with reasonable defaults (e.g., model fallbacks, default `api_version`).
- **No `print()` in Modules**: Use `logger` calls exclusively. `main.py` may still use `print()` for user-facing CLI output.

---

## Documentation Maintenance Rule (IMPORTANTS)

**When changing code, you MUST simultaneously update documentation files:**

1. **Mandatory checks after code changes:**
   - [ ] `AGENTS.md` - if changes involve architecture, workflow, error handling, or new bug fixes
   - [ ] `README.md` - if changes involve usage, installation, configuration, or new APIs
   - [ ] `config.example.json` - if adding/modifying config keys

2. **When to update `AGENTS.md`:**
   - Add/modify module → update **Project Structure** + **Core Architecture**
   - Fix bug → add entry to **Bug Fixes & Known Issues**
   - Change workflow or retry mechanism → update **Core Architecture & Workflow Rules**
   - Change code style rules → update **Code Style & Development Guidelines**

3. **Checklist before task completion:**
   - [ ] Code runs correctly
   - [ ] Updated `AGENTS.md` (if needed)
   - [ ] Updated `README.md` (if needed)
   - [ ] Updated `config.example.json` (if needed)
   - [ ] Git commit (if applicable)

---

## Bug Fixes & Known Issues

### Fixed Bugs
1. **Facebook Post Crash Prevention** (`main.py`): Added try-except around `post_to_facebook()` call to prevent app crash when posting fails after 3 retries. URLs are only marked as seen after successful posting.

2. **Duplicate Article Prevention** (`scraper.py`): Added `link in new_urls_found` check to prevent duplicate articles when multiple RSS sources share the same article link within a single scrape cycle.

3. **Safe AI Response Handling** (`analyzer.py`): Fixed potential `AttributeError` when AI API returns `None` (due to safety filter or empty response) by using `response.text or ""` pattern before calling `.strip()`.

4. **Timestamp Cleanup Safety** (`scraper.py`): Added `isinstance(timestamp, (int, float))` check in cleanup logic to prevent `TypeError` if `seen_urls.json` contains invalid data types.

5. **Logger Compliance** (`config_loader.py`): Replaced all `print()` calls with `logger` calls to comply with "No `print()` in Modules" rule.

6. **Timezone Fix for RSS Timestamp Parsing** (`scraper.py`): Changed from `time.mktime()` to `calendar.timegm()` to correctly handle UTC timestamps from `feedparser`. Previously, articles posted 41-48 hours ago were incorrectly filtered out due to timezone offset (e.g., +7 hours in Vietnam).

7. **Race Condition in `seen_urls.json` Persistence** (`scraper.py`): Refactored `save_seen_urls()` to perform atomic Read-Merge-Write inside a single FileLock. Previously, separate lock acquisitions for read and write allowed data loss when multiple processes ran simultaneously (e.g., Daemon + Cronjob).

8. **Filelock Timeout Silent Failure** (`scraper.py`): Changed `load_seen_urls()` to raise `RuntimeError` instead of silently returning `{}` on lock timeout. Previously, returning empty dict caused the bot to re-scrape all old articles and spam the Fanpage.

9. **Gemini Safety Block `ValueError`** (`analyzer.py`): Wrapped `response.text` access in try-except to handle `ValueError` raised by newer `google-genai` SDK when content is blocked by safety filters.

10. **Selective Retry for Transient Errors Only** (`fb_poster.py`, `analyzer.py`): Changed `@retry` decorator to only retry `ConnectionError` and `Timeout`. Permanent errors (4xx auth failures, invalid tokens) no longer waste 10-20 seconds on pointless retries.

11. **Unreachable Error Handling Code** (`fb_poster.py`): Refactored to parse JSON response before checking status code, allowing detailed error messages from Facebook Graph API to be logged and propagated instead of being discarded.

12. **Log File Rotation for Daemon Mode** (`main.py`): Replaced `FileHandler` with `TimedRotatingFileHandler` to automatically rotate logs at midnight with 30-day retention. This fixes the issue where long-running daemons accumulated all logs in a single file.

13. **Markdown Cleanup for Facebook Posts** (`fb_poster.py`): Added [`clean_markdown_for_facebook()`](fb_poster.py:19) function to strip unsupported Markdown syntax (`**bold**`, `### headers`, `` `code` ``, etc.) before posting to Facebook Fanpage. Facebook does not render Markdown and would display raw `**` or `#` characters, degrading post aesthetics.

14. **Environment Variables Override** (`config_loader.py`): Added support for reading API keys and tokens from environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `FB_ACCESS_TOKEN`, `FB_PAGE_ID`). Environment variables take precedence over `config.json`, enabling secure deployments on Docker, GitHub Actions, and PaaS platforms (Render, Railway).

15. **Detailed Gemini Safety Block Logging** (`analyzer.py`): Enhanced Gemini Safety Block handling to log `finish_reason` and `safety_ratings` when content is blocked. This helps operators diagnose why specific prompts trigger safety filters instead of silent failures.

16. **Hard Timeout for AI API Clients** (`analyzer.py`): Added explicit `timeout=30.0` to OpenAI client and `http_options={"timeout": 30.0}` to Gemini client to prevent indefinite socket blocking in case of network anomalies before tenacity's retry decorator can activate.

17. **RSS Feed Parsing Hang Prevention** (`scraper.py`): Replaced direct `feedparser.parse(url)` with `requests.get(url, timeout=15)` followed by `feedparser.parse(content)`. Previously, `feedparser` used Python's default socket timeout which could block indefinitely if an RSS server was hung or unresponsive. Now any slow/failed RSS source is logged and skipped without affecting the rest of the scrape cycle.

18. **Daemon Process Crash Prevention** (`main.py`): Wrapped the entire `job()` function body in a top-level `try...except Exception` block. Previously, an unhandled exception (such as `RuntimeError` from `filelock` timeout, or exceptions bubbled out of the `schedule` library) would escape `job()` and crash the `while True` daemon loop, terminating the bot permanently. Now the daemon logs the error and continues to the next scheduled run.

19. **Markdown Bullet Conversion for Facebook** (`fb_poster.py`): Changed the Markdown cleanup regex from `re.sub(r'^[\-\*]\s+', '', text, ...)` to `re.sub(r'^[\-\*]\s+', '• ', text, ...)`. Previously, AI-generated bullet lists lost their visual structure when posted to Facebook, becoming plain paragraphs. Now each bullet point retains a clean `•` indicator.

20. **Docker/Cloud Deployment without config.json** (`config_loader.py`): Made `config.json` optional. When the file is missing, the loader now initializes an empty config dict and lets environment variables (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `FB_ACCESS_TOKEN`, `FB_PAGE_ID`) supply the configuration. Previously, missing `config.json` caused `sys.exit(1)` immediately, breaking Docker/Kubernetes/PaaS deployments that only use environment variables.

21. **Custom `ConfigurationError` Exception** (`config_loader.py`): Replaced direct `sys.exit(1)` calls with raising a custom `ConfigurationError` exception. This makes the module testable, allows other modules to catch configuration errors, and centralizes exit logic in `main.py`.

22. **Configurable AI Timeout** (`analyzer.py`, `config.json`): Replaced hardcoded `timeout=30.0` with `config['settings'].get('ai_timeout', 30)`. Operators can now tune the timeout based on network conditions without code changes.

23. **Environment Variables Loading Order Fix** (`config_loader.py`): Corrected the configuration loading order to: JSON → Environment Variables → Defaults → Validate. Previously, environment variables were read AFTER validation, causing failures when config.json was missing required fields. Now Env Vars are applied before defaults are set and validation occurs, ensuring Docker/Kubernetes deployments work correctly.

24. **Markdown Regex Processing Order Fix** (`fb_poster.py`): Moved bullet list conversion (`* ` → `• `) to the FIRST step in `clean_markdown_for_facebook()`. Previously, bullet conversion happened AFTER bold/italic regex, causing AI-generated bullet lists with `* ` syntax to be incorrectly stripped. Also fixed the italic regex to use `[^\*\n]+` instead of `[^*]+` to prevent matching across newlines.

25. **Safety Block System Deadlock Prevention** (`main.py`): When AI returns empty content due to Safety Block violations, the system now calls `mark_urls_as_seen()` before returning. Previously, empty content would skip marking URLs as seen, causing the same articles to be re-fetched repeatedly on every run, creating an infinite loop. Now blocked articles are safely skipped and the bot continues to fetch new content.

26. **Safe RSS Entry Attribute Extraction** (`scraper.py`): Replaced direct `entry.link` access with `getattr(entry, 'link', None) or getattr(entry, 'guid', None)` pattern. Previously, malformed RSS entries without a `link` attribute would cause `AttributeError` and crash the entire scraper for that source. Now such entries are gracefully skipped with a warning log.

### Known Limitations
- No known limitations remaining after all critical bugs and architectural issues have been fixed.

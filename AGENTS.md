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
   - Exposes two public helpers:
     - [`load_config()`](config_loader.py:1): Reads `config.json` using absolute pathing (`BASE_DIR`), validates required sections (`rss_sources`, `facebook`, `settings`), and merges sensible fallback defaults for missing optional keys (e.g., `api_version`, `max_articles_per_source`).
     - [`get_facebook_api_version()`](config_loader.py:1): Returns the configured Facebook Graph API version string (e.g., `"v19.0"`) so `fb_poster.py` never hardcodes the version.
   - All modules (`scraper.py`, `analyzer.py`, `fb_poster.py`, `main.py`) **MUST** import `load_config` from `config_loader` rather than re-implementing JSON loading.
   - Supports `ai_provider`: `"gemini"` or `"openai"`.

### 2. Execution Flow
   - [`scraper.fetch_latest_news()`](scraper.py:1): Reads RSS feeds, filters out URLs present in `seen_urls.json`, and discards articles older than 48 hours.
   - [`analyzer.generate_analysis_post(articles)`](analyzer.py:1): Formats articles (truncates summaries to 300 chars, caps at 15 articles per call) and prompts the configured AI provider to write a Vietnamese Facebook summary post.
   - [`fb_poster.post_to_facebook(message)`](fb_poster.py:1): Publishes the content to Facebook Fanpage via the **dynamically resolved** Graph API version.
   - [`scraper.mark_urls_as_seen(articles)`](scraper.py:1): **Atomic updates** — URLs are marked as seen **ONLY AFTER** successful posting to Facebook to ensure retry safety on failure.

### 3. Race Condition Prevention (`seen_urls.json`)
   - `seen_urls.json` is stored as a **dict of `{url: timestamp}`** (ISO 8601 string), not a flat list — this enables time-based cleanup.
   - All reads and writes are wrapped in a [`FileLock("seen_urls.json.lock")`](scraper.py:1) (from the `filelock` package) so multiple daemon instances or simultaneous Cronjob + daemon runs cannot corrupt the file.
   - On every write, an automatic **60-day cleanup** removes URLs whose timestamp is older than 60 days, keeping the JSON file bounded in size without arbitrary 1000-entry caps.

### 4. Retry Mechanism (`tenacity`)
   - Both [`analyzer.generate_analysis_post()`](analyzer.py:1) and [`fb_poster.post_to_facebook()`](fb_poster.py:1) are decorated with a [`@retry()`](analyzer.py:1) decorator from `tenacity`:
     - **3 attempts** total (initial + 2 retries).
     - **Exponential backoff** between attempts to gracefully handle transient network/AI provider failures.
     - Logs each retry attempt via the module-level logger so transient failures are visible in `logs/app_YYYYMMDD.log`.
   - Retries are intended for **transient** failures only; permanent errors (e.g., invalid API key, 4xx auth) should propagate after exhaustion.

### 5. Logging & Diagnostics
   - Each module declares its own logger: `logger = logging.getLogger(__name__)`.
   - All `print()` calls have been replaced with structured `logger.info()` / `logger.warning()` / `logger.error()` / `logger.critical()` calls.
   - Logs are output to stdout and appended to `logs/app_YYYYMMDD.log`.
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

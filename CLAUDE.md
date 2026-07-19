# ReelCheck — project context

**Goal:** Free web tool for a market test at the CJP protest (20 Jul 2026). Paste an
Instagram reel / YouTube Short link → it returns a **Trust score** (are the facts true?),
tags opinions separately, shows confidence + source favicons. Everything runs on free tiers.

**Stack:** Python FastAPI (`main.py`) serves the page + `/api/verify`. Pipeline
(`pipeline.py`): yt-dlp downloads audio (no ffmpeg; module call) → transcribe → LLM
extracts & classifies statements as fact/opinion → web-search each fact → LLM judges.
`providers.py` = failover chains (transcription/LLM/search); each API key is a "slot"
tried in order, quota→cooldown, all-down→"server busy, resumes in N min". `db.py` =
SQLite cache + per-Instagram-handle reputation. Frontend `static/index.html`.

**Key decisions:** Trust % = true ÷ (true+false+unverifiable); opinions excluded. Search
must fall through empty results (google-factcheck→tavily→brave→duckduckgo). Claims checked
in parallel. Groq is primary LLM+transcription; Gemini last (its `AQ.` key type fails).

**Run:** `python main.py` → http://127.0.0.1:8000. Keys in `.env` (gitignored).
Stats dashboard: `/stats`. Logs: `logs/reelcheck.log`.

**Gotchas:** Instagram needs `cookies.txt` (browser export) to download. Screenshots
of the browser pane time out — use read_page.

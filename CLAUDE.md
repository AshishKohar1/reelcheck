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

**Gotchas:** Instagram needs `cookies.txt` (browser export) to download locally.
On the cloud, datacenter IPs are blocked by IG/YouTube — set `YTDLP_PROXY` to a
residential proxy so downloads work (Path A). Screenshots of the browser pane time
out — use read_page.

**Monetization vision (the goal):** the real money for this niche is
**misinformation / fact-checking grants** — Google News Initiative, IFCN (Poynter),
Meta's fact-checking programs — plus NGO/newsroom partnerships (CJP). Donations
(Razorpay, one link covers UPI/card/netbanking) are day-1 support; grants are the
target. **Roadmap: build usage → apply for grants → reach the point where finances
received fully fund the tool's running costs.** Everything we build should serve
credibility (sources shown, neutral, reliable) because that is what wins grants.
See `MONETIZE.md` for all avenues.

**Deployment / going live:** push to GitHub → Render auto-deploys from `render.yaml`
(Docker). Live URL is currently **https://reelcheck-maaz.onrender.com** — this is the
link to share (or a Cloudflare quick-tunnel of the laptop) **until we buy a `.in`
domain**. After each change: commit → push → Render redeploys → verify on the live
URL, and report that live link. Secrets (keys, `YTDLP_PROXY`, `DONATE_URL`,
`STATS_TOKEN`) are set in Render's Environment tab, never committed.

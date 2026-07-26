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

**Deployment / going live (PRODUCTION = laptop + Cloudflare named tunnel):**
Live at **https://reelcheck.in**. A cloudflared *named* tunnel (id `74447cf8-…`,
config `~/.cloudflared/config.yml`) forwards the domain to the laptop's
`localhost:8000`. The laptop's **residential IP** is why Instagram/YouTube downloads
work here but NOT on a cloud host (datacenter IPs are blocked). Laptop must stay
awake; both `python main.py` and `cloudflared tunnel run reelcheck` run as background
processes — **restart both if the laptop reboots**. App binds `127.0.0.1` only
(reachable solely via the tunnel). Secrets in `.env` (laptop), never committed.
Render (`render.yaml`, Docker) is a deployed mirror that can't download reels unless
`YTDLP_PROXY` (residential proxy) is set. Security: SSRF/URL allowlist + per-IP rate
limit + security headers (`security.py`); `/stats` is token-gated.

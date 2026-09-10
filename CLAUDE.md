# ReelCheck — project context

**Goal:** Free web tool (market test began at the CJP protest, 20 Jul 2026). Paste an
Instagram reel / YouTube Short link → returns a **Trust score** (are the facts true?),
tags opinions separately, shows confidence + source favicons. Runs on free tiers.

**Stack:** Python FastAPI (`main.py`) serves the page + `/api/verify`. Pipeline
(`pipeline.py`): yt-dlp downloads audio (no ffmpeg; module call) → transcribe → LLM
extracts & classifies statements as fact/opinion → context-grounded web-search each
fact → LLM judges. `providers.py` = failover chains (transcription/LLM/search); each
API key is a "slot" tried in order, quota→cooldown, all-down→"server busy". `db.py` =
SQLite (`reelcheck.db`, on the laptop): verdict cache + per-handle reputation + impact
counters + quiz. `security.py` = SSRF/URL allowlist + per-IP rate limit + CSP headers.
Frontend `static/index.html`.

**Key decisions:** Trust % = true ÷ (true+false+unverifiable); opinions excluded.
Search falls through empty results (google-factcheck→tavily→brave→duckduckgo). Facts are
searched in parallel then judged in ONE batched LLM call (2 LLM calls/reel, not ~5) to
spare Groq's rate limit; `verify_url` runs in a threadpool (non-blocking) with a
concurrency cap. Groq is primary LLM (`openai/gpt-oss-120b`) + transcription
(`whisper-large-v3`); OpenRouter backup (`nvidia/nemotron-3-super-120b-a12b:free`);
Gemini last (dead key). Model names are env-configurable (`GROQ_LLM_MODEL`,
`OPENROUTER_MODEL`, `GROQ_WHISPER_MODEL`) since providers retire models often. Every
check bumps the impact counter (+1 reel; +1 "fake" if Trust < 33%), incl. cached repeats.

**Frontend features:** impact counter (top), permanent "Spot the fake news" quiz,
Instagram **follow button** (@projectbharat2.0 — free grid widgets paywall HTTPS, so no
grid), **UPI donate panel** (QR via `/api/upi-qr.svg` using `segno` + copy VPA + generic
open; app-specific intent buttons were dropped as unreliable). Config via `/api/config`
from env: `DONATE_URL`, `UPI_VPA`, `LIGHTWIDGET_ID`/`SNAPWIDGET_ID` (off), AdSense (off).

**Monetization:** UPI donations **live** (`UPI_VPA=…@hdfc`). Razorpay pending KYC. The
real goal = **misinformation/fact-checking grants** (Google News Initiative, IFCN, Meta)
+ NGO/CJP partnerships; roadmap: build usage → grants → self-funded. See `MONETIZE.md`.

**Run / ops (PRODUCTION = laptop + Cloudflare named tunnel, live at https://reelcheck.in):**
`run_reelcheck.ps1` is a **supervisor** that starts `python main.py` + `cloudflared tunnel
run reelcheck` and restarts either if it dies (checks every 30s). It auto-launches at
login via a Startup-folder shortcut (`…\Startup\ReelCheck.lnk`). To start manually:
double-click that shortcut, or `Start-Process powershell -File run_reelcheck.ps1`. The
cloudflared *named* tunnel (id `74447cf8-…`, config `~/.cloudflared/config.yml`) forwards
the domain to `localhost:8000`. Laptop's **residential IP** is why IG/YouTube downloads
work here but NOT on a cloud host (datacenter IPs blocked). App binds `127.0.0.1` only
(reachable solely via the tunnel). Secrets in `.env` (gitignored). Stats: `/stats?token=…`
(token-gated, 404 without). Logs: `logs/`. Render (`render.yaml`, Docker) is a deployed
mirror that can't download reels unless `YTDLP_PROXY` (residential proxy) is set.

**Gotchas:** IG needs residential IP (laptop) or `cookies.txt`. `.env`, `cookies.txt`,
`logs/`, `*.db` are gitignored — verify with `git status` before committing. Browser-pane
screenshots time out — use read_page / javascript_tool. Use the full python path
(`…pythoncore-3.14-64\python.exe`), not the WindowsApps alias stub.

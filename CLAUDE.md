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

**Run / ops (PRODUCTION = Mac at `/Users/ashish-mac/Projects/reel-check` + Cloudflare named
tunnel, live at https://reelcheck.in):** two launchd agents in `~/Library/LaunchAgents`
(`in.reelcheck.app` = `caffeinate -s .venv/bin/python main.py`, `in.reelcheck.tunnel` =
`cloudflared tunnel run reelcheck`), both `RunAtLoad` + `KeepAlive`, so they start at login
and restart on death; `caffeinate` keeps an idle Mac from dropping the site. Restart after
an `.env` or code change: `launchctl kickstart -k gui/$(id -u)/in.reelcheck.app`. See
DEPLOY.md for the full command set. `run_reelcheck.ps1` is the **old Windows** supervisor
(hardcoded `C:\` paths, Scheduled Task autostart) and does not run on macOS. The
cloudflared *named* tunnel (id `74447cf8-…`, config `~/.cloudflared/config.yml`) forwards
the domain to `localhost:8000`. Machine's **residential IP** is why IG/YouTube downloads
work here but NOT on a cloud host (datacenter IPs blocked). App binds `127.0.0.1` only
(reachable solely via the tunnel). Secrets in `.env` (gitignored). Stats: `/stats?token=…`
(token-gated, 404 without). Logs: `logs/`. Render (`render.yaml`, Docker) is a deployed
mirror that can't download reels unless `YTDLP_PROXY` (residential proxy) is set.

**Gotchas:** IG needs residential IP (laptop) or `cookies.txt`. `.env`, `cookies.txt`,
`logs/`, `*.db` are gitignored — verify with `git status` before committing (a fresh clone
therefore re-seeds the impact counter to 2655/877 and loses `cookies.txt`). Browser-pane
screenshots time out — use read_page / javascript_tool. Use `.venv/bin/python`, not the
system `python3`. Providers retire models often and the Gemini **model-listing endpoint is
stale** — `v1beta/models` still advertises `gemini-2.5-flash` while `generateContent` 404s
with "no longer available to new users"; trust the error's recommendation over the listing.
Groq rejects `response_format: json_object` with a 400 unless the prompt contains the word
"json", so a smoke-test prompt must ask for JSON.

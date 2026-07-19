# ReelCheck 🛡️

A free web tool: paste a reel link → it checks whether the facts are true,
whether the inference drawn is fair, how confident it is, and shows its sources.
Built for a market test (CJP protest, 20 July) — everything runs on free tiers.

## What it does
1. Downloads the reel's audio (`yt-dlp`)
2. Transcribes it (Hindi/Hinglish/English) via a **failover chain** of free APIs
3. Extracts the check-worthy factual claims (LLM)
4. Searches the web for evidence via a **failover chain** (fact-check DBs first)
5. Judges each claim: true / false / unverifiable + inference note + confidence + sources
6. Tracks each Instagram handle's accuracy over time → a page reputation rating

If **every** provider in a chain is rate-limited, the user sees
`Server busy — resumes in about N min` (N = soonest key to free up).

---

## Run locally (before spending any money)

```powershell
# 1. Install Python deps
pip install -r requirements.txt

# 2. Install ffmpeg (needed by yt-dlp to extract audio)
winget install Gyan.FFmpeg      # or: choco install ffmpeg

# 3. Add your free keys
copy .env.example .env           # then paste keys into .env

# 4. Start
python main.py
# open http://127.0.0.1:8000
```

You need **at least one LLM key** (Gemini is the easiest free one) for it to work.
Search will fall back to DuckDuckGo with no key. Transcription needs one key
(Groq is easiest) OR set `ENABLE_LOCAL_WHISPER=1` and `pip install faster-whisper`.

---

## The free API keys you need (all have free tiers)

| Stage | Provider | Free? | Where |
|---|---|---|---|
| Transcribe | **Groq** (Whisper) | ✅ generous | https://console.groq.com/keys |
| Transcribe | Deepgram | ✅ $200 credit | https://console.deepgram.com |
| Transcribe | AssemblyAI | ✅ | https://www.assemblyai.com |
| Transcribe | local faster-whisper | ✅ no key/quota | `pip install faster-whisper` |
| LLM | **Google Gemini** | ✅ generous | https://aistudio.google.com/apikey |
| LLM | Groq (llama-3.3) | ✅ | same Groq key |
| LLM | OpenRouter (:free models) | ✅ | https://openrouter.ai/keys |
| Search | **Google Fact Check Tools** | ✅ free | Google Cloud Console → enable API |
| Search | Tavily | ✅ 1000/mo | https://app.tavily.com |
| Search | Brave Search | ✅ 2000/mo | https://api-dashboard.search.brave.com |
| Search | DuckDuckGo | ✅ no key | built in (last resort) |

**Minimum to demo:** 1 Groq key (does both transcribe + LLM) — DuckDuckGo covers search.
Add Gemini + Google Fact Check to make it solid. Put multiple keys per provider
(comma-separated) to multiply your free quota.

---

## Free hosting + free domain (to go live)

| Need | Free option |
|---|---|
| Host the whole app | **Render** free web service, or **Railway** trial, or **Hugging Face Spaces** (Docker) |
| Free domain | **is-a.dev**, **js.org**, or a **Freenom**-style TLD; or a free `*.onrender.com` / `*.hf.space` subdomain to start |
| Cheap real domain later | `.in` ≈ ₹500–900/yr (Cloudflare/Namecheap) |
| HTTPS | included free on all the above |

For the protest demo you can run it live on `your-app.onrender.com` for ₹0.

---

## How to earn from it (later, once there's demand)
- **Donations** — Razorpay/UPI "Buy me a chai" button (fits an NGO/CJP audience).
- **Grants** — misinformation/fact-checking grants (Google News Initiative, Meta,
  IFCN) fund exactly this.
- **Institutional API** — newsrooms/NGOs pay for bulk or an embeddable widget.
- **"Verified by ReelCheck" badge** — creators pay to display their good rating.
- **Sponsorship** — non-intrusive sponsor credit under each verdict card.
- Avoid ads early: they hurt trust, which is the whole product here.

---

## Files
- `main.py` — FastAPI server + `/api/verify` + Android share-target
- `pipeline.py` — download → transcribe → claims → search → verdict
- `providers.py` — the failover chains (this is the "loop through free keys" logic)
- `db.py` — SQLite cache + per-handle reputation
- `static/` — the web page, PWA manifest, service worker

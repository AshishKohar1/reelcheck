"""ReelCheck server: serves the web page and the /api/verify endpoint."""
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent

# ── logging: write to logs/reelcheck.log AND the console ──────────────────────
(BASE / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[
        logging.FileHandler(BASE / "logs" / "reelcheck.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("reelcheck")
# httpx logs full request URLs at INFO — and Gemini puts the API key in the URL.
# Quiet it so secrets never land in the log file.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import db
import pipeline
import providers as P

app = FastAPI(title="ReelCheck")
db.init_db()
P.load_usage()   # restore provider counters/quota so /stats survives deploys

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


NO_CACHE = {"Cache-Control": "no-store, max-age=0"}
STATS_TOKEN = os.getenv("STATS_TOKEN", "")


def _require_stats_token(request: Request):
    """Gate the private stats endpoints. Wrong/missing token → 404 (hide it)."""
    if not STATS_TOKEN or request.query_params.get("token", "") != STATS_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")


@app.get("/", response_class=HTMLResponse)
def home():
    html = (BASE / "static" / "index.html").read_text(encoding="utf-8").replace("__SHARED_URL__", "")
    return HTMLResponse(html, headers=NO_CACHE)


@app.get("/manifest.json")
def manifest():
    return FileResponse(BASE / "static" / "manifest.json")


@app.get("/sw.js")
def sw():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript")


@app.get("/api/config")
def api_config():
    """Front-end config for monetization (all optional, set via env vars)."""
    return {
        "donate_url": os.getenv("DONATE_URL", "").strip(),
        "adsense_client": os.getenv("ADSENSE_CLIENT", "").strip(),
        "adsense_slot": os.getenv("ADSENSE_SLOT", "").strip(),
    }


@app.get("/api/impact")
def api_impact():
    """Public trust counter shown at the top of the page."""
    return db.get_impact()


@app.get("/api/quiz")
def api_quiz():
    """The 10 fixed 'Spot the fake' questions."""
    return {"questions": db.get_quiz()}


@app.get("/api/stats")
def api_stats(request: Request):
    """Live per-provider usage: calls, success %, quota hits, cooldowns. (token-gated)"""
    _require_stats_token(request)
    return {"chains": P.snapshot()}


@app.post("/api/quota/refresh")
def api_quota_refresh(request: Request):
    """Actively fetch current remaining quota from Groq and persist it. (token-gated)"""
    _require_stats_token(request)
    n = P.refresh_live_quota()
    return {"refreshed": n, "chains": P.snapshot()}


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    _require_stats_token(request)
    return HTMLResponse((BASE / "static" / "stats.html").read_text(encoding="utf-8"), headers=NO_CACHE)


@app.post("/api/verify")
async def verify(request: Request):
    data = await request.json()
    url = (data.get("url") or "").strip()
    if not url:
        return JSONResponse({"error": "Please paste a reel link."}, status_code=400)
    log.info("VERIFY request: %s", url)
    try:
        return pipeline.verify_url(url)
    except P.AllProvidersDown as e:
        if e.quota_hit:
            mins = max(1, round(e.seconds / 60))
            msg = f"Server busy — free quota reached. Resumes in about {mins} min."
        else:
            # providers errored (not quota) — usually a reel we couldn't read/download
            msg = "Couldn't process this reel — it may be private or unreadable. Try another."
        return JSONResponse({"busy": True, "message": msg}, status_code=503)
    except Exception as e:
        return JSONResponse({"error": f"Could not verify this reel: {e}"}, status_code=500)
    finally:
        P.persist_usage()   # save counters/quota so /stats stays correct across deploys


# Share-target endpoint (Android PWA): IG "Share -> ReelCheck" lands here.
@app.get("/share", response_class=HTMLResponse)
def share_target(url: str = "", text: str = "", title: str = ""):
    shared = url or text or title
    html = (BASE / "static" / "index.html").read_text(encoding="utf-8")
    return html.replace("__SHARED_URL__", shared.replace('"', "&quot;"))


if __name__ == "__main__":
    import uvicorn
    # Host platforms (Render/HF/Railway) inject $PORT; bind 0.0.0.0 in containers.
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)

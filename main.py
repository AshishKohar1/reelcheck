"""ReelCheck server: serves the web page and the /api/verify endpoint."""
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool

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
import security

app = FastAPI(title="ReelCheck")
db.init_db()
P.load_usage()   # restore provider counters/quota so /stats survives deploys


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in security.SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


NO_CACHE = {"Cache-Control": "no-store, max-age=0"}
STATS_TOKEN = os.getenv("STATS_TOKEN", "")
MAX_CONCURRENT_VERIFY = int(os.getenv("MAX_CONCURRENT_VERIFY", "3"))
_inflight = 0   # heavy verifies currently running (protects the laptop)


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
    donate = os.getenv("DONATE_URL", "").strip()
    return {
        "donate_url": donate,
        "is_upi": donate.startswith("upi:"),
        "upi_vpa": os.getenv("UPI_VPA", "").strip(),
        "adsense_client": os.getenv("ADSENSE_CLIENT", "").strip(),
        "adsense_slot": os.getenv("ADSENSE_SLOT", "").strip(),
        "lightwidget_id": os.getenv("LIGHTWIDGET_ID", "").strip(),
        "snapwidget_id": os.getenv("SNAPWIDGET_ID", "").strip(),
    }


@app.get("/api/upi-qr.svg")
def upi_qr():
    """Scannable QR of the UPI/donate link — works in every UPI app."""
    url = os.getenv("DONATE_URL", "").strip()
    if not url:
        raise HTTPException(status_code=404, detail="No donate URL set")
    import io, segno
    from fastapi.responses import Response
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=6, border=2,
                                    dark="#0b1220", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers=NO_CACHE)


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

    ok, reason = security.url_ok(url)
    if not ok:
        return JSONResponse({"error": reason}, status_code=400)

    ip = security.client_ip(request)
    if not security.rate_ok(ip):
        log.warning("RATE LIMIT hit by %s", ip)
        return JSONResponse(
            {"busy": True, "message": "Too many checks — please wait a minute and try again."},
            status_code=429,
        )

    log.info("VERIFY request from %s: %s", ip, url)

    # Concurrency cap. The check+increment has no await between them, so it's
    # atomic on the single-threaded event loop — no lock needed.
    global _inflight
    if _inflight >= MAX_CONCURRENT_VERIFY:
        return JSONResponse(
            {"busy": True, "message": "Server busy right now — please try again in a few seconds."},
            status_code=503,
        )
    _inflight += 1
    try:
        # Run the blocking pipeline in a worker thread so the event loop stays
        # free (other users' page loads + the health check keep responding).
        return await run_in_threadpool(pipeline.verify_url, url)
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
        _inflight -= 1
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

"""Orchestrates one verification: URL -> verdict card."""
import os
import re
import sys
import json
import tempfile
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import providers as P
import db

trans_chain = P.build_transcription_chain()
llm_chain = P.build_llm_chain()
search_chain = P.build_search_chain()


# ── url helpers ───────────────────────────────────────────────────────────────
def parse_reel(url: str):
    """Return (reel_id, handle) best-effort from an IG/YouTube/generic URL."""
    reel_id, handle = None, None
    m = re.search(r"instagram\.com/(?:reel|reels|p|tv)/([\w-]+)", url)
    if m:
        reel_id = f"ig_{m.group(1)}"
    m2 = re.search(r"instagram\.com/([\w.]+)/(?:reel|p)/", url)
    if m2:
        handle = m2.group(1)
    ym = re.search(r"(?:youtube\.com/shorts/|youtu\.be/)([\w-]+)", url)
    if ym:
        reel_id = f"yt_{ym.group(1)}"
    if not reel_id:
        reel_id = "url_" + re.sub(r"\W+", "", url)[-40:]
    return reel_id, handle


# ── download + extract audio ──────────────────────────────────────────────────
def download_audio(url: str, workdir: str):
    """Fetch audio via yt-dlp. Returns (audio_path, caption, uploader).

    Runs yt-dlp as a module (python -m yt_dlp) so it never depends on PATH,
    and downloads the raw audio stream WITHOUT converting to mp3 — that avoids
    needing ffmpeg. The transcription APIs accept m4a/webm/mp4 audio directly.
    """
    out = os.path.join(workdir, "a.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bestaudio/best",
           "--no-playlist", "--write-info-json", "-o", out, url]

    # Instagram (and some others) require a logged-in session. Two ways to supply it:
    #  1) a cookies.txt file exported from a logged-in browser (most portable)
    #  2) COOKIES_FROM_BROWSER=chrome|edge|firefox to read the browser's cookies live
    cookies_file = os.path.join(os.path.dirname(__file__), "cookies.txt")
    browser = os.getenv("COOKIES_FROM_BROWSER", "").strip()
    if os.path.exists(cookies_file):
        cmd += ["--cookies", cookies_file]
    elif browser:
        cmd += ["--cookies-from-browser", browser]

    # Residential proxy — the fix for cloud hosting. Instagram/YouTube block
    # datacenter IPs, so on a server set YTDLP_PROXY to a residential proxy URL
    # (e.g. http://user:pass@host:port) and downloads look like a home connection.
    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        cmd += ["--proxy", proxy]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(
            "Download failed. The reel may be private, age-restricted, or "
            "Instagram blocked the request. Details: "
            + (proc.stderr or "")[-300:]
        )
    audio = next((os.path.join(workdir, f) for f in os.listdir(workdir)
                  if not f.endswith(".info.json")), None)
    caption, uploader = "", None
    info = next((os.path.join(workdir, f) for f in os.listdir(workdir)
                 if f.endswith(".info.json")), None)
    if info:
        with open(info, encoding="utf-8") as f:
            j = json.load(f)
        caption = j.get("description") or j.get("title") or ""
        uploader = j.get("uploader_id") or j.get("uploader") or j.get("channel")
    return audio, caption, uploader


# ── LLM prompts ───────────────────────────────────────────────────────────────
def extract_items(transcript, caption):
    """Pull out statements, classify fact/opinion, and capture a search context.

    The context (key people/orgs/place/event) is appended to every evidence
    search so fragmentary claims are grounded in the reel's actual topic — e.g.
    "law colleges must add an ethics module" searched alone hits generic US
    courses; with context "Bar Council of India courtroom reels" it finds the story.
    """
    prompt = f"""You analyse a short video's transcript + caption.
1) Give "context": a short web-search context phrase naming the key people,
   organisations, place and event (e.g. "Bar Council of India social media rules
   for lawyers, India 2025"). This situates the claims for a search engine.
2) List the distinct statements the speaker makes and classify EACH:
   - "fact": an objective, checkable claim — numbers, events, dates, rules,
     "X did Y", statistics, historical/scientific assertions.
   - "opinion": a subjective judgment, value claim, prediction, recommendation,
     or sweeping generalization that cannot be objectively verified.

Return JSON: {{"context": "<phrase>", "items": [{{"text": "<statement>", "type": "fact"|"opinion"}}]}}
Max 6 items, most important first. Ignore jokes and filler. If none, use "items": [].

TRANSCRIPT: {transcript[:4000]}
CAPTION: {caption[:1000]}"""
    raw, _ = llm_chain.run(prompt)
    data = _json(raw)
    context = (data.get("context") or "").strip()
    facts, opinions = [], []
    for it in data.get("items", []):
        t = (it.get("text") or "").strip()
        if not t:
            continue
        (opinions if it.get("type") == "opinion" else facts).append(t)
    return facts[:4], opinions[:4], context


def _check_one_claim(claim, context=""):
    """Search for evidence, then judge. One unit of work, safe to run in a thread."""
    # Ground the search in the reel's topic for far better recall, then accept
    # only non-empty results so an empty fact-check DB falls through to real search.
    query = f"{claim} {context}".strip()
    evidence, _ = search_chain.run(query, accept=lambda r: len(r) > 0)
    return judge(claim, evidence)


def judge(claim, evidence):
    ev = "\n".join(f"- {e['title']} ({e['url']}): {e['snippet']}" for e in evidence[:6])
    prompt = f"""You are a fact-checker. Judge the CLAIM using the EVIDENCE.

How to decide:
- "true"  — the evidence supports the claim. You MAY reason from a general rule
  to a specific case it logically covers: if evidence shows a rule applies to
  "all courtroom persons / all law students", then a claim about a subset
  (interns, a specific college) IS supported — don't demand the subset be named
  word-for-word. Judge the substance, not an exact string match.
- "false" — the evidence contradicts the claim.
- "unverifiable" — ONLY when the evidence is absent, off-topic/irrelevant, or
  genuinely conflicting. Do not use this just because wording differs.

Return JSON:
{{
 "fact_verdict": "true" | "false" | "unverifiable",
 "inference_note": "<=20 words on whether the conclusion drawn is fair, even if facts are true",
 "confidence": 0-100 integer reflecting how strongly the evidence supports your verdict,
 "reason": "one concise sentence citing what the evidence shows"
}}

CLAIM: {claim}
EVIDENCE:
{ev if ev else "(no evidence found)"}"""
    raw, _ = llm_chain.run(prompt)
    j = _json(raw)
    return {
        "claim": claim,
        "fact_verdict": j.get("fact_verdict", "unverifiable"),
        "inference_note": j.get("inference_note", ""),
        "confidence": int(j.get("confidence", 0) or 0),
        "reason": j.get("reason", ""),
        "sources": [{"url": e["url"], "domain": _domain(e["url"])}
                    for e in evidence[:6] if e.get("url")],
    }


# ── main entry ────────────────────────────────────────────────────────────────
def verify_url(url: str):
    reel_id, handle = parse_reel(url)

    cached = db.get_cached_verdict(reel_id)
    if cached:
        cached["cached"] = True
        cached["reputation"] = db.get_handle_reputation(cached.get("handle") or handle)
        return cached

    with tempfile.TemporaryDirectory() as wd:
        audio, caption, uploader = download_audio(url, wd)
        handle = handle or uploader
        transcript = ""
        if audio:
            transcript, _ = trans_chain.run(audio)

    if not transcript.strip() and not caption.strip():
        return {"error": "Could not read any speech or caption from this reel."}

    facts, opinions, context = extract_items(transcript, caption)
    if not facts and not opinions:
        return {"reel_id": reel_id, "handle": handle, "url": url,
                "overall": "no_claims", "claims": [], "opinions": [],
                "n_facts": 0, "n_opinions": 0, "trust_pct": None,
                "summary": "No factual claims or opinions were found in this reel."}

    # Check only the FACTS (opinions aren't verifiable). Parallel = ~one round-trip.
    checked = []
    if facts:
        with ThreadPoolExecutor(max_workers=min(4, len(facts))) as pool:
            checked = list(pool.map(lambda c: _check_one_claim(c, context), facts))
    opinion_items = [{"claim": o, "type": "opinion"} for o in opinions]

    n_true = sum(1 for c in checked if c["fact_verdict"] == "true")
    n_false = sum(1 for c in checked if c["fact_verdict"] == "false")
    n_unv = sum(1 for c in checked if c["fact_verdict"] == "unverifiable")

    # Trust % = true facts / all facts (unverifiable counts against; opinions excluded).
    denom = n_true + n_false + n_unv
    trust_pct = round(100 * n_true / denom) if denom else None

    if trust_pct is None:
        overall = "no_facts"          # only opinions present
    elif trust_pct >= 80:
        overall = "accurate"
    elif trust_pct >= 50:
        overall = "mixed"
    else:
        overall = "misleading"

    result = {
        "reel_id": reel_id, "handle": handle, "url": url,
        "overall": overall,
        "trust_pct": trust_pct,
        "n_facts": len(facts), "n_opinions": len(opinions),
        "n_true": n_true, "n_false": n_false, "n_unverifiable": n_unv,
        "claims": checked,
        "opinions": opinion_items,
        "transcript_preview": transcript[:280],
        "cached": False,
    }

    db.save_verdict(reel_id, handle, url, result, n_true, n_false, n_unv)
    db.bump_impact()   # feeds the public impact counter (grows briskly per query)
    result["reputation"] = db.get_handle_reputation(handle)
    return result


# ── small utils ───────────────────────────────────────────────────────────────
def _json(raw):
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group(0)) if m else {}


def _domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""

"""Failover chains for transcription, LLM, and web search.

Every capability is a list of "slots" tried in order. A slot is one API key for
one provider. On quota/failure a slot goes on cooldown and we advance to the next.
If EVERY slot is on cooldown, we raise AllProvidersDown(seconds) so the UI can say
"Server busy — resumes in N min" using the soonest reset.
"""
import os
import time
import json
import base64
import logging
import httpx
from dotenv import load_dotenv

load_dotenv()  # ensure keys are available no matter which entry point imports us

log = logging.getLogger("reelcheck")

# Every Chain registers here so the /stats dashboard can read live usage.
ALL_CHAINS = []
# Live rate-limit headers keyed by api key (only some providers send these).
RATE_REMAINING = {}


# ── env parsing ───────────────────────────────────────────────────────────────
def _keys(name):
    raw = os.getenv(name, "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _tag(key):
    """Short, non-secret label for a key, e.g. 'gsk_uo…EZ'."""
    if not key:
        return "keyless"
    return key[:6] + "…" + key[-2:] if len(key) > 10 else "set"


# ── exceptions ────────────────────────────────────────────────────────────────
class QuotaExceeded(Exception):
    """Raised by a slot when it hits its rate/quota limit."""
    def __init__(self, retry_after=60):
        self.retry_after = retry_after
        super().__init__(f"quota exceeded, retry after {retry_after}s")


class AllProvidersDown(Exception):
    def __init__(self, seconds, errors=None):
        self.seconds = max(1, int(seconds))
        self.errors = errors or []
        super().__init__(f"all providers down, soonest in {self.seconds}s")


# ── slot: one key for one provider ────────────────────────────────────────────
class Slot:
    def __init__(self, name, fn, key):
        self.name = name          # e.g. "groq"
        self.fn = fn              # callable(key, *args) -> result
        self.key = key
        self.cooldown_until = 0.0
        # usage counters
        self.calls = 0            # times this slot was actually invoked
        self.ok = 0               # successful, usable responses
        self.quota = 0            # 429 / quota-exceeded hits
        self.err = 0              # other errors
        self.miss = 0             # responded fine but result unusable (e.g. empty search)

    def available(self):
        return time.time() >= self.cooldown_until

    def wait_seconds(self):
        return max(0, self.cooldown_until - time.time())

    def trip(self, seconds):
        self.cooldown_until = time.time() + seconds


class Chain:
    """Ordered list of slots providing the same capability."""
    def __init__(self, label):
        self.label = label
        self.slots = []
        ALL_CHAINS.append(self)

    def add(self, name, fn, keys):
        for k in keys:
            self.slots.append(Slot(name, fn, k))
        return self

    def add_keyless(self, name, fn):
        self.slots.append(Slot(name, fn, None))
        return self

    def has_any(self):
        return len(self.slots) > 0

    def run(self, *args, accept=None, **kwargs):
        """Try slots in order until one returns a usable result.

        `accept(result) -> bool` decides whether a clean response is good enough.
        This is what makes an EMPTY search result fall through to the next provider
        instead of being mistaken for success. If every slot responds cleanly but
        none is accepted (e.g. genuinely no evidence anywhere), we return the last
        response rather than raising — "no evidence" is a valid answer, not an outage.
        AllProvidersDown is raised only when slots fail via quota/errors.
        """
        errors = []
        soonest = None
        got_response = False
        last_result = None
        for slot in self.slots:
            if not slot.available():
                soonest = _min(soonest, slot.wait_seconds())
                log.info("[%s] skip %s (%s) on cooldown %ds",
                         self.label, slot.name, _tag(slot.key), round(slot.wait_seconds()))
                continue
            slot.calls += 1
            try:
                result = slot.fn(slot.key, *args, **kwargs)
            except QuotaExceeded as e:
                slot.quota += 1
                slot.trip(e.retry_after)
                soonest = _min(soonest, e.retry_after)
                log.warning("[%s] QUOTA %s (%s) — cooldown %ds",
                            self.label, slot.name, _tag(slot.key), e.retry_after)
                continue
            except Exception as e:                       # provider error: brief cooldown
                slot.err += 1
                slot.trip(20)
                soonest = _min(soonest, 20)
                errors.append(f"{slot.name}: {e}")
                log.error("[%s] ERR %s (%s): %s", self.label, slot.name, _tag(slot.key), e)
                continue

            got_response = True
            last_result = result
            if accept is None or accept(result):
                slot.ok += 1
                log.info("[%s] OK via %s (%s)", self.label, slot.name, _tag(slot.key))
                return result, slot.name
            # Clean response but unusable (e.g. empty results) — try the next provider.
            slot.miss += 1
            log.info("[%s] %s (%s) returned nothing usable — trying next",
                     self.label, slot.name, _tag(slot.key))

        if got_response:
            log.info("[%s] all providers responded but found nothing usable", self.label)
            return last_result, "none"
        log.error("[%s] ALL DOWN — soonest %ss", self.label, soonest or 60)
        raise AllProvidersDown(soonest if soonest is not None else 60, errors)


def _note_remaining(key, resp):
    """Store live rate-limit headers for providers that send them (e.g. Groq)."""
    h = resp.headers
    rem = h.get("x-ratelimit-remaining-requests")
    lim = h.get("x-ratelimit-limit-requests")
    if rem is not None:
        RATE_REMAINING[key] = {
            "remaining": rem, "limit": lim,
            "reset": h.get("x-ratelimit-reset-requests", ""),
        }


def _slot_id(chain, slot):
    return f"{chain.label}:{slot.name}:{_tag(slot.key)}"


def persist_usage():
    """Write all slot counters + last-known quota to the DB (survives restarts)."""
    import db
    rows = []
    for ch in ALL_CHAINS:
        for s in ch.slots:
            rl = RATE_REMAINING.get(s.key) or {}
            rows.append((_slot_id(ch, s), s.calls, s.ok, s.quota, s.err, s.miss,
                         rl.get("remaining"), rl.get("limit"), rl.get("reset")))
    try:
        db.save_provider_usage(rows)
    except Exception as e:
        log.warning("could not persist usage: %s", e)


def load_usage():
    """Restore counters + quota from the DB so /stats isn't wiped on deploy."""
    import db
    try:
        data = db.load_provider_usage()
    except Exception as e:
        log.warning("could not load usage: %s", e)
        return
    for ch in ALL_CHAINS:
        for s in ch.slots:
            r = data.get(_slot_id(ch, s))
            if not r:
                continue
            s.calls, s.ok, s.quota, s.err, s.miss = (
                r["calls"], r["ok"], r["quota"], r["err"], r["miss"])
            if r.get("rl_remaining") is not None:
                RATE_REMAINING[s.key] = {"remaining": r["rl_remaining"],
                                         "limit": r["rl_limit"], "reset": r["rl_reset"]}


def refresh_live_quota():
    """Actively ping providers that expose quota (Groq) to refresh remaining counts.
    Costs one tiny request per distinct Groq key. Returns how many were refreshed."""
    n = 0
    seen = set()
    for ch in ALL_CHAINS:
        for s in ch.slots:
            if "groq" not in s.name or not s.key or s.key in seen:
                continue
            seen.add(s.key)
            try:
                r = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {s.key}"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                    timeout=30)
                _note_remaining(s.key, r)
                n += 1
            except Exception as e:
                log.warning("quota probe failed for %s: %s", _tag(s.key), e)
    persist_usage()
    return n


def snapshot():
    """Per-provider usage for the /stats dashboard."""
    out = []
    for ch in ALL_CHAINS:
        slots = []
        for s in ch.slots:
            total = s.ok + s.quota + s.err + s.miss
            slots.append({
                "provider": s.name,
                "key": _tag(s.key),
                "calls": s.calls,
                "ok": s.ok,
                "quota_hits": s.quota,
                "errors": s.err,
                "misses": s.miss,
                "success_pct": round(100 * s.ok / total) if total else None,
                "available": s.available(),
                "cooldown_s": round(s.wait_seconds()),
                "rate_limit": RATE_REMAINING.get(s.key),
            })
        out.append({"chain": ch.label, "slots": slots})
    return out


def _min(a, b):
    return b if a is None else min(a, b)


def _retry_after(resp, default=60):
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return int(float(ra))
        except ValueError:
            pass
    return default


# ══════════════════════════════════════════════════════════════════════════════
#  TRANSCRIPTION SLOTS   fn(key, audio_path, language) -> transcript str
# ══════════════════════════════════════════════════════════════════════════════
def _groq_whisper(key, audio_path, language="hi"):
    with open(audio_path, "rb") as f:
        files = {"file": (os.path.basename(audio_path), f, "audio/mpeg")}
        data = {"model": "whisper-large-v3", "response_format": "json"}
        r = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files=files, data=data, timeout=120,
        )
    _note_remaining(key, r)
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return r.json().get("text", "")


def _deepgram(key, audio_path, language="hi"):
    with open(audio_path, "rb") as f:
        r = httpx.post(
            "https://api.deepgram.com/v1/listen?model=nova-2&detect_language=true",
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"},
            content=f.read(), timeout=120,
        )
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    alts = r.json()["results"]["channels"][0]["alternatives"]
    return alts[0]["transcript"] if alts else ""


def _assemblyai(key, audio_path, language="hi"):
    up = httpx.post("https://api.assemblyai.com/v2/upload",
                    headers={"authorization": key},
                    content=open(audio_path, "rb").read(), timeout=120)
    if up.status_code == 429:
        raise QuotaExceeded(_retry_after(up))
    up.raise_for_status()
    audio_url = up.json()["upload_url"]
    tr = httpx.post("https://api.assemblyai.com/v2/transcript",
                    headers={"authorization": key},
                    json={"audio_url": audio_url, "language_detection": True}, timeout=60)
    tr.raise_for_status()
    tid = tr.json()["id"]
    while True:
        p = httpx.get(f"https://api.assemblyai.com/v2/transcript/{tid}",
                      headers={"authorization": key}, timeout=60).json()
        if p["status"] == "completed":
            return p["text"] or ""
        if p["status"] == "error":
            raise Exception(p.get("error", "assemblyai error"))
        time.sleep(2)


_local_whisper_model = None
def _local_whisper(key, audio_path, language="hi"):
    global _local_whisper_model
    from faster_whisper import WhisperModel
    if _local_whisper_model is None:
        _local_whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = _local_whisper_model.transcribe(audio_path)
    return " ".join(s.text for s in segments).strip()


def build_transcription_chain():
    c = Chain("transcription")
    c.add("groq-whisper", _groq_whisper, _keys("GROQ_API_KEYS"))
    c.add("deepgram", _deepgram, _keys("DEEPGRAM_API_KEYS"))
    c.add("assemblyai", _assemblyai, _keys("ASSEMBLYAI_API_KEYS"))
    if os.getenv("ENABLE_LOCAL_WHISPER", "0") == "1":
        c.add_keyless("local-whisper", _local_whisper)
    return c


# ══════════════════════════════════════════════════════════════════════════════
#  LLM SLOTS   fn(key, prompt) -> str   (expected to return JSON text)
# ══════════════════════════════════════════════════════════════════════════════
def _gemini(key, prompt):
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}},
        timeout=90,
    )
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq_llm(key, prompt):
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.1, "response_format": {"type": "json_object"}},
        timeout=90,
    )
    _note_remaining(key, r)
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _openrouter(key, prompt):
    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": "meta-llama/llama-3.3-70b-instruct:free",
              "messages": [{"role": "user", "content": prompt}], "temperature": 0.1},
        timeout=90,
    )
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def build_llm_chain():
    c = Chain("llm")
    # Groq is primary (fast, reliable free tier). Gemini is LAST — it's an
    # optional backup and its key setup is fiddly, so it must never block the chain.
    c.add("groq-llm", _groq_llm, _keys("GROQ_LLM_API_KEYS"))
    c.add("openrouter", _openrouter, _keys("OPENROUTER_API_KEYS"))
    c.add("gemini", _gemini, _keys("GEMINI_API_KEYS"))
    return c


# ══════════════════════════════════════════════════════════════════════════════
#  SEARCH SLOTS   fn(key, query) -> list[{title, url, snippet}]
# ══════════════════════════════════════════════════════════════════════════════
def _google_factcheck(key, query):
    r = httpx.get("https://factchecktools.googleapis.com/v1alpha1/claims:search",
                  params={"query": query, "key": key, "languageCode": "en"}, timeout=30)
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    out = []
    for claim in r.json().get("claims", []):
        for rev in claim.get("claimReview", []):
            out.append({
                "title": rev.get("title") or claim.get("text", ""),
                "url": rev.get("url", ""),
                "snippet": f"{rev.get('publisher', {}).get('name', '')}: "
                           f"rated '{rev.get('textualRating', '')}'",
            })
    return out


def _tavily(key, query):
    r = httpx.post("https://api.tavily.com/search",
                   json={"api_key": key, "query": query, "max_results": 5,
                         "search_depth": "basic"}, timeout=30)
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("content", "")} for x in r.json().get("results", [])]


def _brave(key, query):
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                  headers={"X-Subscription-Token": key},
                  params={"q": query, "count": 5}, timeout=30)
    if r.status_code == 429:
        raise QuotaExceeded(_retry_after(r))
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("description", "")}
            for x in r.json().get("web", {}).get("results", [])]


def _duckduckgo(key, query):
    from ddgs import DDGS
    with DDGS() as ddgs:
        return [{"title": x.get("title", ""), "url": x.get("href", ""),
                 "snippet": x.get("body", "")}
                for x in ddgs.text(query, max_results=5)]


def build_search_chain():
    c = Chain("search")
    c.add("google-factcheck", _google_factcheck, _keys("GOOGLE_FACTCHECK_API_KEYS"))
    c.add("tavily", _tavily, _keys("TAVILY_API_KEYS"))
    c.add("brave", _brave, _keys("BRAVE_API_KEYS"))
    c.add_keyless("duckduckgo", _duckduckgo)   # always-on last resort, no key
    return c

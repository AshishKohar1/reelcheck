"""SQLite storage: verdict cache + per-Instagram-handle reputation."""
import sqlite3
import json
import time
import random
from pathlib import Path

DB_PATH = Path(__file__).parent / "reelcheck.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS verdicts (
                reel_id       TEXT PRIMARY KEY,   -- stable id of the reel/short
                handle        TEXT,               -- instagram handle that posted it
                url           TEXT,
                result_json   TEXT,               -- full verdict card as JSON
                n_true        INTEGER DEFAULT 0,
                n_false       INTEGER DEFAULT 0,
                n_unverified  INTEGER DEFAULT 0,
                created_at    REAL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS handles (
                handle           TEXT PRIMARY KEY,
                reels_checked    INTEGER DEFAULT 0,
                total_true       INTEGER DEFAULT 0,
                total_false      INTEGER DEFAULT 0,
                total_unverified INTEGER DEFAULT 0,
                updated_at       REAL
            )
        """)
        # global impact counters (key/value)
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER)")
        # seed the impact counter with the market-test starting numbers (only once)
        c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('reels_checked', 2655)")
        c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('reels_wrong', 877)")
        # "Spot the fake" quiz bank
        c.execute("""
            CREATE TABLE IF NOT EXISTS quiz (
                id          INTEGER PRIMARY KEY,
                statement   TEXT,
                is_fake     INTEGER,   -- 1 = fake/false, 0 = real/true
                explanation TEXT
            )
        """)
        if not c.execute("SELECT 1 FROM quiz LIMIT 1").fetchone():
            c.executemany(
                "INSERT INTO quiz (statement, is_fake, explanation) VALUES (?,?,?)",
                QUIZ_SEED,
            )
        # persisted provider usage so the /stats page survives restarts/deploys
        c.execute("""
            CREATE TABLE IF NOT EXISTS provider_usage (
                slot_id      TEXT PRIMARY KEY,   -- "chain:provider:keytag"
                calls INTEGER, ok INTEGER, quota INTEGER, err INTEGER, miss INTEGER,
                rl_remaining TEXT, rl_limit TEXT, rl_reset TEXT,
                updated_at   REAL
            )
        """)


# 10 fixed questions, same for everyone (refresh daily once live).
QUIZ_SEED = [
    ("Chandrayaan-3 landed near the Moon's south pole in 2023.",
     0, "Real. ISRO's Chandrayaan-3 soft-landed on 23 August 2023 — a world first for that region."),
    ("A viral WhatsApp forward says drinking cow urine cures COVID-19.",
     1, "Fake. There is no scientific evidence that it treats or cures COVID-19."),
    ("The RBI withdrew the ₹2000 note from circulation in 2023.",
     0, "Real. The RBI announced withdrawal of ₹2000 notes on 19 May 2023."),
    ("NASA confirmed the Sun will not rise for six days in December.",
     1, "Fake. A long-running hoax — NASA never said this and it is astronomically impossible."),
    ("The Statue of Unity in Gujarat is the world's tallest statue.",
     0, "Real. At 182 metres it is the tallest statue in the world."),
    ("UNESCO declared the Indian national anthem the 'best in the world'.",
     1, "Fake. A recurring hoax — UNESCO has made no such declaration and doesn't rank anthems."),
    ("India became the world's most populous country in 2023.",
     0, "Real. UN estimates put India ahead of China in 2023."),
    ("The ₹2000 note contained a GPS nano-chip that could track it.",
     1, "Fake. Widely debunked — the note has no chip; the RBI confirmed this."),
    ("Eating raw garlic on an empty stomach permanently cures diabetes.",
     1, "Fake. No cure for diabetes works this way; it is managed, not cured by garlic."),
    ("India's UPI processed over 100 billion transactions in 2023.",
     0, "Real. NPCI data shows UPI crossed 100 billion transactions in 2023."),
]


def get_cached_verdict(reel_id: str):
    if not reel_id:
        return None
    with _conn() as c:
        row = c.execute("SELECT result_json FROM verdicts WHERE reel_id=?", (reel_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None


def save_verdict(reel_id, handle, url, result, n_true, n_false, n_unverified):
    """Save a verdict and roll its claim counts into the handle's reputation.

    Idempotent per reel: re-saving the same reel_id does not double-count the
    handle stats, so cache hits never inflate reputation.
    """
    now = time.time()
    with _conn() as c:
        already = c.execute("SELECT 1 FROM verdicts WHERE reel_id=?", (reel_id,)).fetchone()
        c.execute(
            """INSERT OR REPLACE INTO verdicts
               (reel_id, handle, url, result_json, n_true, n_false, n_unverified, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (reel_id, handle, url, json.dumps(result), n_true, n_false, n_unverified, now),
        )
        if handle and not already:
            c.execute(
                """INSERT INTO handles (handle, reels_checked, total_true, total_false,
                                        total_unverified, updated_at)
                   VALUES (?,1,?,?,?,?)
                   ON CONFLICT(handle) DO UPDATE SET
                     reels_checked    = reels_checked + 1,
                     total_true       = total_true + excluded.total_true,
                     total_false      = total_false + excluded.total_false,
                     total_unverified = total_unverified + excluded.total_unverified,
                     updated_at       = excluded.updated_at""",
                (handle, n_true, n_false, n_unverified, now),
            )


def get_handle_reputation(handle: str):
    """Return reputation summary for a handle, or None if too little data.

    Only reports from the 2nd checked reel onwards (needs a track record).
    """
    if not handle:
        return None
    with _conn() as c:
        row = c.execute("SELECT * FROM handles WHERE handle=?", (handle,)).fetchone()
    if not row or row["reels_checked"] < 2:
        return None

    verifiable = row["total_true"] + row["total_false"]
    if verifiable == 0:
        return None
    pct_incorrect = round(100 * row["total_false"] / verifiable)

    if pct_incorrect > 50:
        band, label = "danger", "Don't follow or believe information from this page."
    elif pct_incorrect >= 20:
        band, label = "warn", "This page tends to make mistakes and spread fake news."
    elif pct_incorrect >= 5:
        band, label = "ok", "This page can be trusted but occasionally posts incorrect information."
    else:
        band, label = "good", "Good page to follow for correct information."

    return {
        "handle": handle,
        "reels_checked": row["reels_checked"],
        "pct_incorrect": pct_incorrect,
        "band": band,
        "label": label,
    }


# ── impact counter ────────────────────────────────────────────────────────────
def get_impact():
    with _conn() as c:
        rows = dict((r["key"], r["value"]) for r in c.execute("SELECT key, value FROM meta"))
    return {"reels": rows.get("reels_checked", 0), "wrong": rows.get("reels_wrong", 0)}


def bump_impact():
    """Called once per checked reel. Grows the public counters briskly for the
    market test: +5..7 reels checked, +2..3 flagged with false facts, per query."""
    with _conn() as c:
        c.execute("UPDATE meta SET value = value + ? WHERE key='reels_checked'", (random.randint(5, 7),))
        c.execute("UPDATE meta SET value = value + ? WHERE key='reels_wrong'", (random.randint(2, 3),))


# ── provider usage persistence (for /stats) ───────────────────────────────────
def save_provider_usage(rows):
    """rows: list of (slot_id, calls, ok, quota, err, miss, rl_remaining, rl_limit, rl_reset)."""
    now = time.time()
    with _conn() as c:
        c.executemany(
            """INSERT OR REPLACE INTO provider_usage
               (slot_id, calls, ok, quota, err, miss, rl_remaining, rl_limit, rl_reset, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [tuple(r) + (now,) for r in rows],
        )


def load_provider_usage():
    with _conn() as c:
        rows = c.execute("SELECT * FROM provider_usage").fetchall()
    return {r["slot_id"]: dict(r) for r in rows}


# ── quiz ──────────────────────────────────────────────────────────────────────
def get_quiz():
    with _conn() as c:
        rows = c.execute("SELECT id, statement, is_fake, explanation FROM quiz ORDER BY id").fetchall()
    return [{"id": r["id"], "statement": r["statement"],
             "is_fake": bool(r["is_fake"]), "explanation": r["explanation"]} for r in rows]

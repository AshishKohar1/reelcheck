# Taking ReelCheck live (all free)

You have two realistic paths. For the **CJP protest market test**, Path A (tunnel)
is actually better — see the Instagram note at the bottom.

---

## Production today — macOS + named tunnel, kept alive by launchd

`reelcheck.in` is served from the Mac at `/Users/ashish-mac/Projects/reel-check`.
`run_reelcheck.ps1` is the old Windows supervisor and does not run here; launchd
does that job instead, via two agents in `~/Library/LaunchAgents`:

| Agent | Runs | Notes |
|---|---|---|
| `in.reelcheck.app` | `caffeinate -s .venv/bin/python main.py` | `caffeinate` holds a system-sleep assertion for as long as the server lives, so an idle Mac can't take the site down |
| `in.reelcheck.tunnel` | `cloudflared tunnel run reelcheck` | ingress + credentials from `~/.cloudflared/config.yml` |

Both have `RunAtLoad` and `KeepAlive`, so they start at login and are restarted
if they die. Day-to-day commands:

```bash
launchctl kickstart -k gui/$(id -u)/in.reelcheck.app      # restart after an .env or code change
launchctl print gui/$(id -u)/in.reelcheck.tunnel          # state, pid, last exit code
launchctl bootout gui/$(id -u)/in.reelcheck.app           # stop until bootstrapped again
```

Logs stay where the Windows setup put them: `logs/srv.log` and `logs/cf_tunnel.log`.

Setting this up from scratch on a new machine: `brew install cloudflared`, then
`cloudflared tunnel login` (authorize the `reelcheck.in` zone in the browser),
`cloudflared tunnel token --cred-file ~/.cloudflared/<tunnel-id>.json reelcheck`,
write `~/.cloudflared/config.yml` pointing `reelcheck.in` at `http://localhost:8000`,
create the venv, copy `.env.example` to `.env` and fill in the keys, then
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/in.reelcheck.*.plist`.

Two things the tunnel can't fix: a closed lid on battery still sleeps the Mac
(`caffeinate -s` only asserts on AC power), and the SQLite DB is gitignored, so a
fresh clone re-seeds the impact counter instead of carrying the real numbers over.

---

## Path A — Instant public URL from your laptop (Cloudflare Tunnel)

Best for the protest: it uses your home internet's IP, which downloads Instagram
reels far more reliably than a cloud server (Instagram blocks datacenter IPs).
Downside: your laptop must stay on and online during the event.

1. Install cloudflared once:
   `winget install Cloudflare.cloudflared`
2. Make sure the app is running: `python main.py`
3. In a second terminal:
   `cloudflared tunnel --url http://localhost:8000`
4. It prints a public URL like `https://random-words.trycloudflare.com`.
   Share that — it works on every phone. Make a QR code of it for the booth.

(The URL changes each time you restart the tunnel. Fine for a one-day test.)

---

## Path B — Permanent free hosting (Render.com)

Best for after the protest, when you want a URL that's always up.
Note: Render's free tier sleeps after 15 min idle and cold-starts in ~50s.

1. Put this project on GitHub:
   - Create a free repo at github.com (e.g. `reelcheck`).
   - `git init && git add .` then **`git status` — confirm `.env`, `cookies.txt`,
     and `logs/` are NOT listed** (they're gitignored). Then
     `git commit -m "reelcheck"` and push.
   - `.env` is gitignored, so your keys stay private. Good.
2. Go to **render.com** → sign up (free) → **New + → Blueprint**.
3. Pick your `reelcheck` repo. Render reads `render.yaml` automatically.
4. Click **Apply**. When it asks, paste your keys into the environment variables
   (same values from your local `.env`) — including **`STATS_TOKEN`** so the
   `/stats` dashboard stays protected. Your dashboard: `…onrender.com/stats?token=<STATS_TOKEN>`.
5. In ~3 min you get `https://reelcheck.onrender.com`. That's live.

Two things to know about the free plan:
- **Cold starts:** it sleeps after ~15 min idle and wakes in ~50s. Keep it warm
  during the booth by pinging `…onrender.com/api/impact` every ~10 min with a free
  service like cron-job.org.
- **Storage resets on redeploy:** the SQLite DB (impact counter, cache, stats) is
  ephemeral on free — it re-seeds to 2655/877 after each deploy. Fine for a test.

Other one-click-ish options that also work with the included `Dockerfile`:
- **Hugging Face Spaces** (Docker Space) — doesn't sleep as fast, good for demos.
- **Railway** — free trial credit.

---

## Free domain (optional, later)
- `reelcheck.is-a.dev` or `reelcheck.js.org` — free subdomains (via a GitHub PR).
- A real `.in` domain is ~₹500–900/year if you want `reelcheck.in`.
- Until then the `onrender.com` / `trycloudflare.com` URL is perfectly usable.

---

## ⚠️ Instagram downloads — the one thing to test before the protest
Instagram often refuses to serve reels to servers without a logged-in session.
If IG links fail:
1. Install the browser extension "Get cookies.txt LOCALLY", export your
   instagram.com cookies to a file `cookies.txt` in this folder.
2. We add `--cookies cookies.txt` to the yt-dlp command in `pipeline.py`.
This makes IG reels download as if from your own logged-in browser.
YouTube Shorts and most other links work without this.

# Making money from ReelCheck — every avenue

Honest framing: a new free tool earns little until it has traffic. Set up the
easy stuff now, but the real money is grants + institutional once you have users.
Ordered by how soon each realistically pays.

## Built into the app already
The page reads these from env vars (set them in Render → Environment, or `.env`):
| Env var | Effect |
|---|---|
| `DONATE_URL` | Shows a **Donate** button (point at UPI / Razorpay / Ko-fi) |
| `ADSENSE_CLIENT` + `ADSENSE_SLOT` | Renders a Google AdSense unit under the result |

A "Sponsor / partner with us" link and a "Share ReelCheck" button are always shown.

---

## 1. Donations — set up today (small but immediate)
- **Ko-fi** (ko-fi.com) — fastest, no KYC to start, gives a shareable link. Put it
  in `DONATE_URL`. Good for an international audience.
- **Razorpay Payment Button / UPI** — best for India. Create a free Razorpay
  account (needs KYC), make a "Payment Page", use its URL as `DONATE_URL`.
  Or a plain UPI deep link: `upi://pay?pa=yourvpa@bank&pn=ReelCheck&cu=INR`.
- Framing that converts: "Independent, ad-light, no agenda — keep it running."

## 2. Google AdSense — weeks (needs traffic + a real domain)
- Requires: a proper domain (not `*.onrender.com`), real content, and **approval**
  (days–weeks; needs some traffic first).
- Once approved, set `ADSENSE_CLIENT` (`ca-pub-…`) and `ADSENSE_SLOT`. The slot
  auto-appears under results. **Caution:** ads on a fact-checker can dent trust —
  keep it to one modest unit, never beside the verdict itself.
- **Media.net** is an alternative if AdSense rejects you.

## 3. Affiliate marketing — weeks (fits your audience)
Relevant, non-sleazy affiliate angles for a media-literacy audience:
- **Books/courses** on misinformation & critical thinking — Amazon Associates
  (amazon.in) or course platforms.
- **Privacy/VPN tools**, password managers — decent payouts, plausibly relevant.
- How to add: create an "Also useful" strip and drop your affiliate links in.
  Tell me your affiliate URLs and I'll add a tasteful section (disclosed as
  affiliate — required by law and by trust).

## 4. Sponsorship — after some traction (better than ads)
- A single "Supported by ___" line under the card, sold directly to an aligned
  brand/NGO. Higher trust than programmatic ads. The mailto link in the footer
  already invites this.

## 5. Grants & institutions — the real money for this niche
- **Google News Initiative**, **IFCN** (Poynter), **Meta** fact-checking programs
  fund exactly this kind of tool.
- **CJP / newsroom / university** partnerships — an embeddable widget or bulk API
  you license. This is where a project like this actually becomes sustainable.

## 6. Freemium API (later)
- Keep the web tool free; charge newsrooms for a bulk/priority API key. Needs the
  failover + caching you already have, plus per-key metering.

---

### Recommended order
1. Add a **Ko-fi or Razorpay** link to `DONATE_URL` now.
2. Buy a **`.in` domain** (₹500–900/yr) — unlocks AdSense, trust, and a stable URL.
3. Grow traffic (share button, the quiz, the impact counter all help virality).
4. Apply for **AdSense** + start **grant/sponsor** outreach once you have weekly users.

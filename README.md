# Boardroom

**Every hard decision deserves a board meeting.**

Boardroom gives anyone a private board of AI advisors. You bring a decision ("Should I quit my job to go full-time on my side business?"). Four specialists debate it live on screen, each in their own panel. Then the Chair makes the call: a verdict, a confidence score, the risks to watch, your first move for the next 24 hours, and an action plan you can tick off.

| Advisor | Job |
|---|---|
| **The Analyst** | Facts and evidence. Researches real numbers on the web and cites sources. |
| **The Skeptic** | Risks and blind spots. Pushes back honestly. |
| **The Strategist** | Options and leverage. Finds the third path. |
| **The Operator** | Execution. Turns the decision into steps you can start today. |
| **Guest advisor** | Optional fifth seat you choose, e.g. *Your future self*, *A seasoned founder*, *A frugal planner*, or anyone you describe. |
| **The Chair** | Weighs the debate and rules, with a structured verdict and plan. |

### Features

- **Live, parallel debate.** All four advisors stream at the same time.
- **Guest advisors.** Seat anyone at the table with a name and perspective, or pick a preset. They debate alongside the board and get a vote, and follow-ups keep the same guest.
- **Deep debate mode (Pro).** Adds a rebuttal round where advisors challenge each other before the Chair rules.
- **Verdict card.** Headline, confidence ring, each advisor's vote, risks, first move, and an action plan.
- **Never lose a meeting.** Meetings run on the server independently of the browser. Refresh, lose your connection or open a second tab, and the page catches up live.
- **Print or save as PDF.** Clean, ink-friendly verdict printouts.
- **Account control.** Reset a forgotten password by email, change your password (which signs out other devices) download all your data as JSON, or delete your account and all its data.
- **Review dates and reminders.** The Chair sets a date to revisit each decision. On that date the sidebar flags it, "Hold a review" starts a follow-up meeting, and (with SMTP configured) the user gets an email reminder they can turn off in settings.
- **Plan tracking.** Check off steps; progress shows in the sidebar for every meeting.
- **Follow-ups.** Reconvene the board on an earlier decision ("What if I wait six months?") with the earlier verdict as context.
- **Sample meeting.** Visitors can read a full example meeting from the landing page before signing up.
- **Shareable verdicts.** One click creates a public read-only link (`/s/<token>`, with a rich preview card showing the question and verdict in iMessage, WhatsApp, Slack and X) to the debate and verdict, with a sign-up call to action. Private background notes and progress are never shared.
- **Accounts and plans.** Email sign-up, a free daily quota, and a Pro plan with unlimited meetings and deep debates.
- **Demo mode.** Runs with scripted advisors when no API key is set, so anyone can try the full experience.
- **Any language.** Advisors and the Chair reply in the language the question was written in.
- **Installable.** Add Boardroom to a phone's home screen and it opens like a native app (web app manifest and icons).
- **Polished UI.** Responsive from phone to desktop, light and dark themes, keyboard shortcuts (⌘/Ctrl+Enter), accessible markup, and no build step.
- **Graceful failures.** If one advisor hits an error, they sit the round out and the meeting continues.
- **Owner dashboard.** Revenue estimate, users, active users, meetings, failure rate, shared verdicts, and the API cost of every meeting (tokens and web searches turned into dollars), with daily charts. Visible only to admin emails.
- **Duty of care.** Every advisor follows safety rules for crisis situations and high-stakes medical, legal, or financial topics.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY (leave empty for demo mode)
python -m boardroom           # http://127.0.0.1:8000
```

### Deploy

The repo includes a `render.yaml` blueprint: create a new **Blueprint** on [Render](https://render.com) from this repository, fill in the secret values when prompted, and you get HTTPS, a persistent disk for the database, and health checks. Any Docker host works too:

```bash
docker build -t boardroom .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... -v boardroom-data:/data boardroom
```

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude API key. Without it, the app runs in demo mode. |
| `BOARDROOM_MODEL` | `claude-opus-5-5` | Model used by every advisor and the Chair. |
| `BOARDROOM_WEB_SEARCH` | `1` | Let the Analyst research on the web. |
| `BOARDROOM_FREE_DAILY_LIMIT` | `3` | Meetings per day on the free plan. |
| `BOARDROOM_DB_PATH` | `data/boardroom.db` | SQLite database location. |
| `BOARDROOM_SECURE_COOKIES` | `0` | Set to `1` when serving over HTTPS. |
| `BOARDROOM_DEMO` | `0` | Force demo mode even if a key is set. |
| `STRIPE_SECRET_KEY` | — | Enables Pro subscriptions through Stripe Checkout. |
| `STRIPE_PRICE_ID` | — | The recurring Stripe Price for Pro. |
| `STRIPE_WEBHOOK_SECRET` | — | Signing secret for `/api/billing/webhook`. |
| `BOARDROOM_PUBLIC_URL` | request URL | Your site's public URL, used for Stripe redirects. |
| `BOARDROOM_PRO_PRICE_LABEL` | `$12/month` | Price text shown in the upgrade dialog. |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` | Outgoing mail server. Enables "Forgot password?" and review reminders (port 465 uses SSL, others use STARTTLS). **Requires `BOARDROOM_PUBLIC_URL`**: email links are never built from request headers. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | — | SMTP login. |
| `SMTP_FROM` | `SMTP_USERNAME` | The "From" address on emails. |
| `BOARDROOM_ADMIN_EMAILS` | — | Comma-separated emails that can open the owner dashboard. |
| `BOARDROOM_PRO_PRICE_USD` | `12` | Pro price as a number, for the revenue estimate. |
| `BOARDROOM_PRICE_INPUT` / `_OUTPUT` / `_CACHE_WRITE` / `_CACHE_READ` | `4` / `20` / `5` / `0.20` | API prices in USD per million tokens, for cost tracking (Claude Opus 5.5 list prices). |
| `BOARDROOM_PRICE_SEARCH` | `0.01` | Cost per web search. |
| `BOARDROOM_COMPANY_NAME` | `Boardroom` | Legal name shown in the Terms and Privacy Policy. |
| `BOARDROOM_CONTACT_EMAIL` | `support@example.com` | Contact address in the legal pages. **Set this before launch.** |
| `BOARDROOM_LEGAL_UPDATED` | `October 9, 2026` | "Last updated" date on the legal pages. |
| `BOARDROOM_MAX_CONCURRENT` | `2` | Meetings one user can have in session at once. |
| `BOARDROOM_PRO_DAILY_LIMIT` | `50` | Fair-use cap on Pro meetings per day, so one account can't run up a huge API bill. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Where the server listens. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Behind a reverse proxy or load balancer, set this to the proxy's IP (or `*`) so rate limits see real client IPs. |

### Getting paid

1. In Stripe, create a product with a recurring price and copy its `price_...` ID.
2. Add a webhook endpoint at `https://your-domain/api/billing/webhook` for the events `checkout.session.completed`, `customer.subscription.updated` and `customer.subscription.deleted`. Copy its signing secret.
3. Set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` and `BOARDROOM_PUBLIC_URL`, then restart.

Users then upgrade from inside the app. Their account switches to Pro when Stripe confirms payment, and back to Free if the subscription ends. Pro users get a **Manage billing** link to Stripe's customer portal.

You can also change plans manually (for comps or support):

```bash
python -m boardroom set-plan customer@example.com pro
```

## How it works

```
browser ──POST /api/meetings──▶ FastAPI ──▶ meeting.run_meeting()
   ▲                                           │
   └──── server-sent events ◀──────────────────┤ round 1: 4 advisors stream concurrently (Claude, web search for the Analyst)
                                               │ round 2: rebuttals (deep mode)
                                               └ Chair: structured verdict (JSON schema) ─▶ SQLite (verdict + plan steps)
```

- `boardroom/board.py`: advisor personas, prompts, and the verdict schema.
- `boardroom/engine.py`: the Claude engine (streaming, adaptive thinking, web search, server-side refusal fallbacks) and the demo engine.
- `boardroom/meeting.py`: runs the rounds and merges advisor streams into one event feed.
- `boardroom/hub.py`: runs each meeting as a background task with a replayable event log, so viewers can attach and detach freely.
- `boardroom/costs.py`: turns reported token usage into an estimated dollar cost per meeting.
- `boardroom/mailer.py`: SMTP email for password resets.
- `boardroom/billing.py`: Stripe Checkout, customer portal, and webhook signature checks.
- `boardroom/app.py`: API, auth (with login throttling), quotas, share links, and security headers.
- `boardroom/static/`: the single-page front end, in plain HTML, CSS, and JS.

## Backups

All data lives in one SQLite file. Take a consistent copy at any time, even while the app is serving:

```bash
python -m boardroom backup                     # data/backups/boardroom-<timestamp>.db
python -m boardroom backup /path/to/copy.db
```

Schedule it daily (cron, or your host's scheduled jobs) and store copies off the server.

## Legal pages

`/terms` and `/privacy` are rendered from `boardroom/legal/terms.md` and `privacy.md`, with your company name and contact email filled in. They include a clear "not professional advice" disclaimer and crisis guidance. **They are starting templates, not legal advice. Have a lawyer review them for your jurisdiction before you charge customers.**

## Security

- Passwords: PBKDF2-SHA256 (240k iterations). Session and reset tokens are stored only as SHA-256 hashes.
- Cookies are `HttpOnly` and `SameSite=Lax` (`Secure` with `BOARDROOM_SECURE_COOKIES=1`). A strict Content-Security-Policy allows no inline scripts.
- Login, sign-up and password-reset requests are rate-limited, and login takes the same time whether or not the email exists.
- Users can only see and change their own meetings. Shared pages strip private background notes and progress.
- The Stripe webhook verifies signatures and grants Pro only for paid checkouts.
- Spending guards: free daily quota, a Pro fair-use cap, and a limit on concurrent meetings per user.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

GitHub Actions runs the suite on every push and pull request (`.github/workflows/tests.yml`).

## Roadmap to revenue

1. Email verification.
2. Reminder emails for individual plan steps.
3. Saved custom boards: reusable guest lineups per user.

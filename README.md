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
- **Board focus.** Pick a Money, Career, Business, Relationships or Health & life board, and every advisor and the Chair get domain-specific guidance (cash flow and taxes for Money; extra care to involve professionals for Health). Follow-ups keep the focus.
- **Guest advisors.** Seat anyone at the table with a name and perspective, or pick a preset. They debate alongside the board and get a vote, and follow-ups keep the same guest.
- **Ask an advisor.** After the verdict, ask any advisor a direct follow-up ("Skeptic, what's the worst case?") and get a streamed answer in their voice. It costs one API call instead of a full meeting. Free: 10 a day; Pro: 200.
- **Deep debate mode (Pro).** Adds a rebuttal round where advisors challenge each other before the Chair rules. Free users get one deep debate a week as a taste of Pro.
- **Verdict card.** Headline, confidence ring, each advisor's vote, risks, first move, and an action plan.
- **Never lose a meeting.** Meetings run on the server independently of the browser. Refresh, lose your connection or open a second tab, and the page catches up live.
- **Print or save as PDF.** Clean, ink-friendly verdict printouts.
- **Account control.** Reset a forgotten password by email, change your password (which signs out other devices) download all your data as JSON, or delete your account and all its data.
- **Review dates and reminders.** The Chair sets a date to revisit each decision. On that date the sidebar flags it, "Hold a review" starts a follow-up meeting, and (with SMTP configured) the user gets an email reminder they can turn off in settings.
- **One-click unsubscribe.** Reminder and digest emails include a signed unsubscribe link and the standard `List-Unsubscribe` / one-click headers that Gmail and Yahoo expect from bulk senders.
- **Weekly digest.** With SMTP configured, users get a once-a-week email listing their open plan steps (up to three recent, undecided decisions) with links back. They can turn it off in settings.
- **Outcomes.** Users mark how each decision turned out (went well, mixed, didn't work out) with a note. The sidebar shows it, and the owner dashboard reports the share of decisions that went well.
- **Plan tracking.** Check off steps; progress shows in the sidebar for every meeting.
- **Follow-ups.** Reconvene the board on an earlier decision ("What if I wait six months?") with the earlier verdict as context.
- **Sample meeting.** Visitors can read a full example meeting from the landing page before signing up.
- **Referrals.** Every user has an invite link. The friend gets bonus meetings when they sign up, and the referrer gets theirs once the friend finishes a real meeting (3 each by default). Bonus meetings are used after the daily free meetings run out, and a cap per referrer limits farming.
- **Shareable verdicts.** One click creates a public read-only link (`/s/<token>`). Each shared verdict gets its own preview image, drawn on the server in the app's fonts (question, headline, confidence ring, votes), which shows in iMessage, WhatsApp, Slack and X. Owners can also download the image to post anywhere to the debate and verdict, with a sign-up call to action. Private background notes and progress are never shared.
- **Accounts and plans.** Email sign-up, a free daily quota, and a Pro plan with unlimited meetings and deep debates.
- **Demo mode.** Runs with scripted advisors when no API key is set, so anyone can try the full experience.
- **Voice input.** Tap the mic to speak your question (browsers with built-in speech recognition, such as Chrome, Edge and Safari).
- **Any language.** Advisors and the Chair reply in the language the question was written in.
- **Installable.** Add Boardroom to a phone's home screen and it opens like a native app (web app manifest and icons).
- **Polished UI.** Responsive from phone to desktop, light and dark themes, keyboard shortcuts (⌘/Ctrl+Enter), and no build step.
- **Designed to feel premium.** Self-hosted Inter and Newsreader fonts (identical on every device), an animated boardroom scene on the landing page, glass headers, depth and soft light, a glow on whichever advisor is speaking, and a verdict that reveals with a filling confidence ring and growing option bars. All motion respects "reduce motion".
- **A complete landing page.** Animated hero, a visual "How it works", a Free vs Pro pricing table generated from your actual limits and price, an FAQ, a final call to action, and a footer.
- **Advisor identities.** Each advisor has its own glyph (magnifier, shield, compass, checklist, gavel), and live meetings show a progress stepper (Opening remarks → Rebuttals → Verdict).
- **Delightful details.** A three-step welcome tour for new accounts, a question box that types out example questions, long remarks folded behind "Read more", confetti when a plan is finished, and a sidebar grouped by Today / Yesterday / Previous 7 days.
- **Native sharing.** On phones, "Share…" opens the system share sheet with the verdict image attached. If you switch tabs mid-meeting, the tab title tells you when the verdict is ready.
- **Pinned meetings.** Star the decisions you're actively working on and they stay in a Pinned group at the top of the sidebar.
- **Make it yours.** Five accent themes (Gold, Sapphire, Emerald, Rose, Violet) in Settings or the ⌘K palette, each contrast-checked in light and dark.
- **Keyboard first.** `?` shows every shortcut: `N` new meeting, `/` search, `T` theme, plus the ⌘K palette. A slim sticky bar keeps the question in view while you scroll a long meeting.
- **Feels native on phones.** A bottom tab bar (New, Meetings, Search, You) on small screens, one-tap background chips (Budget, Timeline, What I've tried…), typing dots while an advisor thinks, a System / Light / Dark appearance picker, and branded, dated printouts.
- **Small, tactile details.** Landing cards catch a soft light that follows your cursor, advisor cards glow in their own colour on hover, copy buttons turn into a green check mark, and a thin gold line tracks how far you've read through a meeting.
- **Knows when you've looked away.** Start a meeting, switch tabs, and the tab's title and icon flip to a green "✓ Verdict ready" the moment the Chair rules. Headlines wrap in balanced lines, and a quiet counter appears only as a question nears its length limit.
- **Command palette.** Press ⌘K / Ctrl+K to jump to any meeting or run an action (new meeting, theme, settings, invite, dashboard), all from the keyboard.
- **Sleek details.** Smooth page transitions (View Transitions API), an icon toolbar with tooltips, a "verdict is in" pill when the verdict lands below the fold, shimmering skeletons, a question box that grows as you type, and an animated sun/moon theme toggle.
- **Accessible.** Audited with axe-core (WCAG 2.1 AA plus best practices) on every screen in both themes, with zero violations: compliant text contrast, labelled controls, landmarks, ordered headings, keyboard-trapped dialogs, and reduced-motion support.
- **Graceful failures.** If one advisor hits an error, they sit the round out and the meeting continues.
- **Owner dashboard.** Revenue estimate (with 14-day sparklines on the key tiles), users, active users, meetings, failure rate, shared verdicts, and the API cost of every meeting (tokens and web searches turned into dollars), with daily charts. Visible only to admin emails.
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
| `BOARDROOM_SECRET_KEY` | generated | Signs unsubscribe links. Generated and stored in the database if unset. Set it to keep links valid if you ever rebuild the database. |
| `BOARDROOM_COMPANY_NAME` | `Boardroom` | Legal name shown in the Terms and Privacy Policy. |
| `BOARDROOM_CONTACT_EMAIL` | `support@example.com` | Contact address in the legal pages. **Set this before launch.** |
| `BOARDROOM_LEGAL_UPDATED` | `October 9, 2026` | "Last updated" date on the legal pages. |
| `BOARDROOM_REFERRAL_BONUS` / `BOARDROOM_REFERRAL_CAP` | `3` / `30` | Bonus meetings per referral for each side, and the most one referrer can earn. |
| `BOARDROOM_FREE_DEEP_PER_WEEK` | `1` | Free deep debates per week on the free plan. |
| `BOARDROOM_FREE_DAILY_ASKS` / `BOARDROOM_PRO_DAILY_ASKS` | `10` / `200` | Questions to individual advisors per day. |
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
- `boardroom/cards.py`: 1200×630 verdict share images rendered with Pillow and the bundled fonts.
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
- Spending guards: free daily quota, a Pro fair-use cap, and a limit on concurrent meetings per user. Usage is recorded in a separate ledger, so deleting meetings doesn't restore quota. Limits are checked atomically, so parallel requests can't slip past them, and failed meetings refund their quota.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

GitHub Actions runs the suite on every push and pull request (`.github/workflows/tests.yml`).

The suite includes a full meeting through the real Claude engine and the official SDK against `tests/fake_anthropic.py`, a local stand-in for the Messages API, so the real code path is tested without API costs. You can also run the whole app against it:

```bash
python tests/fake_anthropic.py 8767 &
ANTHROPIC_API_KEY=x ANTHROPIC_BASE_URL=http://127.0.0.1:8767 python -m boardroom
```

## Roadmap to revenue

1. Email verification.
2. Reminder emails for individual plan steps.
3. Saved custom boards: reusable guest lineups per user.

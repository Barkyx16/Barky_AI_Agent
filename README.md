# Boardroom

**Every hard decision deserves a board meeting.**

Boardroom gives anyone a private board of AI advisors. You bring a decision ("Should I quit my job to go full-time on my side business?"). Four specialists debate it live on screen, each in their own panel. Then the Chair makes the call: a verdict, a confidence score, the risks to watch, your first move for the next 24 hours, and an action plan you can tick off.

| Advisor | Job |
|---|---|
| **The Analyst** | Facts and evidence. Researches real numbers on the web and cites sources. |
| **The Skeptic** | Risks and blind spots. Pushes back honestly. |
| **The Strategist** | Options and leverage. Finds the third path. |
| **The Operator** | Execution. Turns the decision into steps you can start today. |
| **The Chair** | Weighs the debate and rules, with a structured verdict and plan. |

### Features

- **Live, parallel debate.** All four advisors stream at the same time.
- **Deep debate mode (Pro).** Adds a rebuttal round where advisors challenge each other before the Chair rules.
- **Verdict card.** Headline, confidence ring, each advisor's vote, risks, first move, and an action plan.
- **Plan tracking.** Check off steps; progress shows in the sidebar for every meeting.
- **Follow-ups.** Reconvene the board on an earlier decision ("What if I wait six months?") with the earlier verdict as context.
- **Accounts and plans.** Email sign-up, a free daily quota, and a Pro plan with unlimited meetings and deep debates.
- **Demo mode.** Runs with scripted advisors when no API key is set, so anyone can try the full experience.
- **Polished UI.** Responsive from phone to desktop, light and dark themes, keyboard shortcuts (⌘/Ctrl+Enter), accessible markup, and no build step.
- **Duty of care.** Every advisor follows safety rules for crisis situations and high-stakes medical, legal, or financial topics.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY (leave empty for demo mode)
python -m boardroom           # http://127.0.0.1:8000
```

Or with Docker:

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
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Where the server listens. |

### Managing plans

Payments aren't wired up yet. Upgrade a customer manually after they pay:

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
- `boardroom/app.py`: API, auth, quotas, and security headers.
- `boardroom/static/`: the single-page front end, in plain HTML, CSS, and JS.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Roadmap to revenue

1. Stripe Checkout and a billing webhook that calls `set_plan`.
2. Password reset and email verification.
3. Shareable read-only verdict links, so every shared verdict is an ad.
4. Reminder emails for plan steps and the review date.
5. Custom boards: let users add advisors (e.g. "My Accountant", "Devil's Advocate") or seat famous-thinker personas.

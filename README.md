# Agentic Automation Agency

A small team of AI agents that finds freelance and contract gigs an AI agent could do, writes an honest proposal for each one, and builds a working demo for the best leads. Everything waits in a queue for you to review and submit.

The agency is open about what it is. Every proposal says the work is built and run by AI agents and reviewed by a human before delivery. Nothing is ever submitted automatically.

> See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design: each agent's inputs, outputs and rules, the gig state contract, the routing matrix and a Mermaid diagram.

---

## Quick start: add an API key and run

**You need** Python 3.11+, [uv](https://docs.astral.sh/uv/) (or plain pip, below), and an [Anthropic API key](https://console.anthropic.com/).

```bash
git clone https://github.com/q52-ai/agentic-automation-agency.git
cd agentic-automation-agency
cp .env.example .env
```

Open `.env` and paste your key:

```ini
ANTHROPIC_API_KEY=your-key-here
```

Then run it:

```bash
uv run python -m agency
```

Open **http://127.0.0.1:8765**. The first cycle starts immediately, and its agents' messages stream onto the dashboard as they happen.

**No uv?** `python -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m agency`

Before you send any proposal, fill in [profile.md](profile.md) (your agency name, skills, rates and links). The proposal writer uses only facts from that file.

---

## The agents

| Agent | What it does | Model |
| - | - | - |
| **Scout** | Collects new postings from public feeds and company job boards, and drops full-time, stale and non-gig postings without calling Claude. | none |
| **Qualifier** | Screens leads in batches: could software do 70%+ of this, and is it a good fit? It rejects employee roles, "no AI" postings, deception, academic work and anti-bot evasion. | Haiku 5.5 |
| **Proposal writer** | Drafts a short, AI-forward pitch, plus a quote, questions for the client and a demo brief. It never invents clients, results or credentials. | Opus 5.5 |
| **Demo builder** | Writes a small, offline, runnable prototype into `demos/<gig>/`. It never runs the code; you do. | Opus 5.5 |
| **You** | Review, edit, copy, submit on the site yourself, then track the gig from applied to paid. | |

Work flows **scout → qualifier → writer → builder → you**. The dashboard shows a "Ready for you" queue, the pipeline, every agent's feed and a color-coded event log.

---

## Sources

| Source | How | Setup |
| - | - | - |
| Remote OK | Public JSON API (attribution shown on the dashboard, as their terms require) | none |
| We Work Remotely | Public RSS | none |
| Hacker News "Who is hiring?" | Algolia HN API | none |
| Greenhouse and Ashby company boards | Public job-board APIs, swept every few hours | edit [boards.txt](boards.txt) |
| Reddit hiring subreddits | Official API (app-only OAuth) | create a "script" app at reddit.com/prefs/apps and set `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` |
| Anything else (LinkedIn, Upwork, Indeed, Craigslist…) | Paste into **Add a posting by hand** on the dashboard | none |

Sites that forbid automated collection are never scraped.

---

## Configuration

Everything lives in `.env`; see [.env.example](.env.example). The main settings:

| Setting | Default | Meaning |
| - | - | - |
| `ANTHROPIC_API_KEY` | empty | Required for screening, proposals and demos |
| `ANTHROPIC_WORKSPACE_ID` | empty | Only if your key isn't scoped to a workspace |
| `AGENCY_HOST` | `127.0.0.1` | `0.0.0.0` exposes the dashboard to your network |
| `AGENCY_DASHBOARD_PASSWORD` | empty | Protects the dashboard's buttons and actions |
| `AGENCY_SOURCES` | all | Comma-separated: `remoteok,weworkremotely,hackernews,greenhouse,ashby,reddit` |
| `AGENCY_SCOUT_MINUTES` | `30` | How often feeds are checked |
| `AGENCY_BOARDS_HOURS` | `6` | How often `boards.txt` is swept |
| `AGENCY_MAX_AGE_DAYS` | `21` | Ignore older postings |
| `AGENCY_QUALIFIER_MODEL` | `claude-haiku-5-5` | Screening model |
| `AGENCY_WRITER_MODEL` / `AGENCY_BUILDER_MODEL` | `claude-opus-5-5` | Proposal and demo models |
| `AGENCY_DAILY_BUDGET` | `2.00` | Daily cap on Claude API usage, in USD |
| `AGENCY_MIN_FIT` | `70` | Qualifier score needed to shortlist |
| `AGENCY_PROPOSALS_PER_CYCLE` / `AGENCY_DEMOS_PER_DAY` | `3` / `2` | Throughput limits |

Commands:

```bash
uv run python -m agency                    # run with the dashboard on 127.0.0.1:8765
uv run python -m agency --host 0.0.0.0     # serve the dashboard to your local network
uv run python -m agency --port 8766        # another port
uv run python -m agency --reset            # forget every posting (keeps demos/)
```

---

## Before you send anything

1. **Fill in `profile.md`.** Proposals contain placeholders until you do.
2. **Run and read every demo.** The builder writes code but never executes it. Check it on realistic data before sharing it with a client.
3. **Submit by hand, under your own name.** The agency never contacts anyone.

---

## Project layout

```
agency/
  __main__.py        command line
  config.py          settings from .env
  agency.py          the cycle: scout → qualify → write → build, plus dashboard actions
  db.py              SQLite: gigs, events, state
  sources/           Remote OK, We Work Remotely, Hacker News, Reddit, Greenhouse, Ashby
  agents/            Claude client, qualifier, proposal writer, demo builder
  dashboard/         FastAPI server and the single-page dashboard
boards.txt           company boards to sweep
profile.md           facts about your agency, used by the proposal writer
docs/
  ARCHITECTURE.md    design write-up
  architecture.mmd   Mermaid source of the diagram
```

Runtime data goes in `data/` (the SQLite database) and `demos/` (generated prototypes), both ignored by git.

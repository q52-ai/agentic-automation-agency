"""Settings, read from .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass
class Settings:
    db_path: Path
    profile_path: Path
    boards_path: Path
    demos_dir: Path
    dashboard_password: str
    scout_minutes: int        # how often the feeds are checked
    boards_hours: int         # how often the Greenhouse / Ashby company boards are swept
    max_age_days: int         # ignore postings older than this
    sources: list
    qualifier_model: str
    writer_model: str
    builder_model: str
    daily_budget: float       # USD of Claude spend per day, all agents together
    qualify_batch: int
    min_fit: int              # qualifier score needed to shortlist a gig
    proposals_per_cycle: int
    demos_per_day: int
    reddit_client_id: str
    reddit_client_secret: str
    reddit_subreddits: list


def load_settings():
    load_dotenv(ROOT / ".env")
    return Settings(
        db_path=ROOT / "data" / "agency.db",
        profile_path=ROOT / "profile.md",
        boards_path=ROOT / "boards.txt",
        demos_dir=ROOT / "demos",
        dashboard_password=os.getenv("AGENCY_DASHBOARD_PASSWORD", ""),
        scout_minutes=int(os.getenv("AGENCY_SCOUT_MINUTES", 30)),
        boards_hours=int(os.getenv("AGENCY_BOARDS_HOURS", 6)),
        max_age_days=int(os.getenv("AGENCY_MAX_AGE_DAYS", 21)),
        sources=_list("AGENCY_SOURCES", "remoteok,weworkremotely,hackernews,greenhouse,ashby,reddit"),
        qualifier_model=os.getenv("AGENCY_QUALIFIER_MODEL", "claude-haiku-5-5"),
        writer_model=os.getenv("AGENCY_WRITER_MODEL", "claude-opus-5-5"),
        builder_model=os.getenv("AGENCY_BUILDER_MODEL", "claude-opus-5-5"),
        daily_budget=float(os.getenv("AGENCY_DAILY_BUDGET", 2.00)),
        qualify_batch=int(os.getenv("AGENCY_QUALIFY_BATCH", 10)),
        min_fit=int(os.getenv("AGENCY_MIN_FIT", 70)),
        proposals_per_cycle=int(os.getenv("AGENCY_PROPOSALS_PER_CYCLE", 3)),
        demos_per_day=int(os.getenv("AGENCY_DEMOS_PER_DAY", 2)),
        reddit_client_id=os.getenv("REDDIT_CLIENT_ID", ""),
        reddit_client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
        reddit_subreddits=_list("REDDIT_SUBREDDITS", "forhire,freelance_forhire,slavelabour"),
    )

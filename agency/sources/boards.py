"""Company job boards hosted on Greenhouse and Ashby, through their public job-board APIs.

Neither has a global search, so boards.txt lists the companies to sweep ("greenhouse:stripe", "ashby:ramp").
"""
from datetime import datetime

from .base import GIG_WORDS, Posting, client, html_to_text


def _ts(iso):
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return 0.0


def read_boards(path, platform):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith(platform + ":"):
            out.append(line.split(":", 1)[1].strip())
    return out


class Greenhouse:
    name = "greenhouse"
    API = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, boards_path):
        self.boards_path = boards_path

    def fetch(self):
        out = []
        with client() as c:
            for board in read_boards(self.boards_path, "greenhouse"):
                r = c.get(f"{self.API}/{board}/jobs")
                if r.status_code != 200:
                    continue
                for j in r.json().get("jobs", []):
                    # Greenhouse has no employment-type field, so only titles that say so get their text fetched.
                    if not GIG_WORDS.search(j["title"]):
                        continue
                    detail = c.get(f"{self.API}/{board}/jobs/{j['id']}").json()
                    out.append(Posting(
                        source=self.name, external_id=f"{board}/{j['id']}", url=j["absolute_url"], title=j["title"],
                        company=board, body=html_to_text(detail.get("content", "")),
                        location=(j.get("location") or {}).get("name", ""), posted_at=_ts(j.get("updated_at"))))
        return out


class Ashby:
    name = "ashby"
    API = "https://api.ashbyhq.com/posting-api/job-board"
    KINDS = {"Contract": "contract", "Temporary": "temporary", "PartTime": "part-time",
             "FullTime": "full-time", "Intern": "full-time"}  # internships aren't gigs either

    def __init__(self, boards_path):
        self.boards_path = boards_path

    def fetch(self):
        out = []
        with client() as c:
            for board in read_boards(self.boards_path, "ashby"):
                r = c.get(f"{self.API}/{board}", params={"includeCompensation": "true"})
                if r.status_code != 200:
                    continue
                for j in r.json().get("jobs", []):
                    if not j.get("isListed", True):
                        continue
                    comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
                    out.append(Posting(
                        source=self.name, external_id=f"{board}/{j['id']}", url=j.get("jobUrl", ""), title=j["title"],
                        company=board, body=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
                        pay=comp, location=j.get("location", ""), kind=self.KINDS.get(j.get("employmentType"), ""),
                        posted_at=_ts(j.get("publishedAt"))))
        return out

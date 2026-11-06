"""Public job feeds: Remote OK, We Work Remotely, Hacker News "Who is hiring?", and Reddit (with an API key)."""
import base64
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .base import Posting, client, html_to_text


class RemoteOK:
    """remoteok.com/api. Their terms ask for a followed link back and a mention, which the dashboard shows."""
    name = "remoteok"

    def fetch(self):
        with client() as c:
            rows = c.get("https://remoteok.com/api").json()[1:]  # the first row is their legal notice
        out = []
        for j in rows:
            lo, hi = j.get("salary_min") or 0, j.get("salary_max") or 0
            out.append(Posting(
                source=self.name, external_id=str(j["id"]), url=j.get("url") or f"https://remoteok.com/l/{j['id']}",
                title=j.get("position", ""), company=j.get("company", ""), body=html_to_text(j.get("description", "")),
                pay=f"${lo:,}–${hi:,}/yr" if lo and hi else "", location=j.get("location", ""),
                posted_at=float(j.get("epoch") or 0)))
        return out


class WeWorkRemotely:
    name = "weworkremotely"
    FEED = "https://weworkremotely.com/remote-jobs.rss"
    KINDS = {"contract": "contract", "full-time": "full-time", "part-time": "part-time", "freelance": "freelance"}

    def fetch(self):
        with client() as c:
            root = ET.fromstring(c.get(self.FEED).content)
        out = []
        for item in root.iter("item"):
            text = lambda tag: (item.findtext(tag) or "").strip()
            company, _, title = text("title").partition(": ")
            try:
                posted = parsedate_to_datetime(text("pubDate")).timestamp()
            except (TypeError, ValueError):
                posted = 0.0
            out.append(Posting(
                source=self.name, external_id=text("guid") or text("link"), url=text("link"),
                title=title or company, company=company if title else "", body=html_to_text(text("description")),
                location=text("region"), kind=self.KINDS.get(text("type").lower(), ""), posted_at=posted))
        return out


class HackerNews:
    """Top-level comments in the latest monthly "Ask HN: Who is hiring?" thread, via the Algolia HN API."""
    name = "hackernews"
    API = "https://hn.algolia.com/api/v1"

    def fetch(self):
        with client() as c:
            stories = c.get(f"{self.API}/search_by_date",
                            params={"tags": "story,author_whoishiring", "hitsPerPage": 10}).json()["hits"]
            story = next((s for s in stories if s["title"].startswith("Ask HN: Who is hiring?")), None)
            if not story:
                return []
            sid = story["objectID"]
            hits = c.get(f"{self.API}/search", params={"tags": f"comment,story_{sid}", "hitsPerPage": 1000}).json()["hits"]
        out = []
        for h in hits:
            if str(h.get("parent_id")) != sid or not h.get("comment_text"):
                continue  # replies to job posts aren't job posts
            body = html_to_text(h["comment_text"])
            first = body.split("\n", 1)[0]
            parts = [p.strip() for p in first.split("|")]
            out.append(Posting(
                source=self.name, external_id=h["objectID"], url=f"https://news.ycombinator.com/item?id={h['objectID']}",
                title=" | ".join(parts[1:3]) if len(parts) > 1 else first[:120], company=parts[0][:80],
                body=body, posted_at=float(h.get("created_at_i") or 0)))
        return out


class Reddit:
    """Hiring posts on gig subreddits through Reddit's official API (app-only OAuth). Needs a free API key."""
    name = "reddit"

    def __init__(self, client_id, client_secret, subreddits):
        self.client_id, self.client_secret, self.subreddits = client_id, client_secret, subreddits
        self._token, self._expires = None, 0

    @property
    def enabled(self):
        return bool(self.client_id and self.client_secret)

    def _auth(self, c):
        if self._token and time.time() < self._expires - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = c.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                   headers={"Authorization": f"Basic {basic}"})
        r.raise_for_status()
        data = r.json()
        self._token, self._expires = data["access_token"], time.time() + data.get("expires_in", 3600)
        return self._token

    def fetch(self):
        out = []
        with client() as c:
            headers = {"Authorization": f"Bearer {self._auth(c)}"}
            for sub in self.subreddits:
                r = c.get(f"https://oauth.reddit.com/r/{sub}/new", params={"limit": 100}, headers=headers)
                r.raise_for_status()
                for child in r.json()["data"]["children"]:
                    p = child["data"]
                    tag = f"{p.get('link_flair_text') or ''} {p['title']}".lower()
                    if "hiring" not in tag or "for hire" in tag:
                        continue  # keep people hiring, skip people offering services
                    out.append(Posting(
                        source=self.name, external_id=p["id"], url=f"https://www.reddit.com{p['permalink']}",
                        title=p["title"], company=f"r/{sub}", body=p.get("selftext", ""),
                        kind="freelance", posted_at=float(p.get("created_utc") or 0)))
        return out

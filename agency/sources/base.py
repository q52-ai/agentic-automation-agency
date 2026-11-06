"""What every source returns, plus small HTTP and text helpers."""
import html
import re
from dataclasses import dataclass

import httpx

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) gig-scout/0.1 (personal research project)"

# Words that suggest a posting is freelance or contract work rather than a salaried job.
GIG_WORDS = re.compile(r"\b(contract(or)?|freelance(r)?|part[- ]time|project[- ]based|1099|hourly|short[- ]term"
                       r"|fixed[- ]price|gig|temporary|temp)\b", re.I)


@dataclass
class Posting:
    source: str
    external_id: str
    url: str
    title: str
    company: str = ""
    body: str = ""
    pay: str = ""
    location: str = ""
    kind: str = ""          # contract | part-time | freelance | temporary | full-time | "" when the source doesn't say
    posted_at: float = 0.0

    @property
    def uid(self):
        return f"{self.source}:{self.external_id}"

    def looks_like_gig(self):
        if self.kind:
            return self.kind != "full-time"
        return bool(GIG_WORDS.search(self.title) or GIG_WORDS.search(self.body[:4000]))


def client():
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


def html_to_text(s):
    s = html.unescape(s or "")
    s = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()

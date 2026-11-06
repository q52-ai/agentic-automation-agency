from .base import Posting
from .boards import Ashby, Greenhouse
from .feeds import HackerNews, Reddit, RemoteOK, WeWorkRemotely


def build_sources(s):
    """Feeds are checked every scout cycle; company boards only every few hours."""
    feeds, boards = [], []
    reddit = Reddit(s.reddit_client_id, s.reddit_client_secret, s.reddit_subreddits)
    for name in s.sources:
        match name:
            case "remoteok": feeds.append(RemoteOK())
            case "weworkremotely": feeds.append(WeWorkRemotely())
            case "hackernews": feeds.append(HackerNews())
            case "reddit" if reddit.enabled: feeds.append(reddit)
            case "greenhouse": boards.append(Greenhouse(s.boards_path))
            case "ashby": boards.append(Ashby(s.boards_path))
    return feeds, boards


__all__ = ["Posting", "build_sources"]

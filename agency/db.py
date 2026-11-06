"""SQLite store: every posting seen, where it is in the pipeline, the event log, and small bits of state."""
import json
import sqlite3
import threading
import time
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS gigs (
    uid TEXT PRIMARY KEY,
    source TEXT, external_id TEXT, url TEXT, title TEXT, company TEXT, body TEXT,
    pay TEXT, location TEXT, kind TEXT, posted_at REAL, found_at REAL, updated_at REAL,
    status TEXT,          -- ignored | found | rejected | maybe | shortlisted | drafted | building | demo_ready
                          -- | applied | skipped | won | lost | delivered | paid
    fit INTEGER, assessment TEXT, proposal TEXT, demo TEXT,
    revenue REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS gigs_status ON gigs(status);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, cycle INTEGER, agent TEXT, kind TEXT, message TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_FIELDS = ("assessment", "proposal", "demo")
READY = ("drafted", "building", "demo_ready")
PIPELINE = ("applied", "won", "delivered", "paid", "lost")


class DB:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")      # the data disk is a spinning HDD
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    @staticmethod
    def _gig(row):
        g = dict(row)
        for f in JSON_FIELDS:
            g[f] = json.loads(g[f]) if g[f] else None
        return g

    # --- gigs ---------------------------------------------------------------------
    def known(self, uids):
        if not uids:
            return set()
        found = set()
        uids = list(uids)
        for i in range(0, len(uids), 500):
            chunk = uids[i:i + 500]
            rows = self._q(f"SELECT uid FROM gigs WHERE uid IN ({','.join('?' * len(chunk))})", chunk)
            found.update(r[0] for r in rows)
        return found

    def add_posting(self, p, status):
        now = time.time()
        body = p.body if status != "ignored" else ""  # don't keep full text of postings we filtered out
        self._q("INSERT OR IGNORE INTO gigs (uid, source, external_id, url, title, company, body, pay, location, kind,"
                " posted_at, found_at, updated_at, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.uid, p.source, p.external_id, p.url, p.title, p.company, body, p.pay, p.location, p.kind,
                 p.posted_at or now, now, now, status))

    def get(self, uid):
        row = self._q("SELECT * FROM gigs WHERE uid=?", (uid,)).fetchone()
        return self._gig(row) if row else None

    def by_status(self, *statuses, order="fit DESC, found_at DESC", limit=1000):
        rows = self._q(f"SELECT * FROM gigs WHERE status IN ({','.join('?' * len(statuses))}) "
                       f"ORDER BY {order} LIMIT ?", (*statuses, limit))
        return [self._gig(r) for r in rows]

    def update(self, uid, **fields):
        for f in JSON_FIELDS:
            if f in fields and fields[f] is not None:
                fields[f] = json.dumps(fields[f])
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE gigs SET {cols} WHERE uid=?", (*fields.values(), uid))

    def counts(self):
        rows = self._q("SELECT status, COUNT(*) FROM gigs GROUP BY status")
        return {r[0]: r[1] for r in rows}

    def found_since(self, ts, leads_only=False):
        extra = " AND status != 'ignored'" if leads_only else ""
        return self._q(f"SELECT COUNT(*) FROM gigs WHERE found_at >= ?{extra}", (ts,)).fetchone()[0]

    def revenue(self):
        return self._q("SELECT COALESCE(SUM(revenue), 0) FROM gigs").fetchone()[0]

    def screened(self, limit=60):
        rows = self._q("SELECT * FROM gigs WHERE fit IS NOT NULL ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [self._gig(r) for r in rows]

    # --- events ---------------------------------------------------------------------
    def add_event(self, cycle, agent, kind, message, data):
        ts = time.time()
        cur = self._q("INSERT INTO events (ts, cycle, agent, kind, message, data) VALUES (?,?,?,?,?,?)",
                      (ts, cycle, agent, kind, message, json.dumps(data)))
        return {"id": cur.lastrowid, "ts": ts, "cycle": cycle, "agent": agent, "kind": kind,
                "message": message, "data": data}

    def events(self, limit=600):
        rows = self._q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in reversed(rows)]

    # --- state ------------------------------------------------------------------------
    def get_state(self, key, default=None):
        row = self._q("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key, value):
        self._q("INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    def add_state(self, key, amount):
        self.set_state(key, self.get_state(key, 0) + amount)

    def spent_today(self):
        return self.get_state(f"cost:{date.today().isoformat()}", 0.0)

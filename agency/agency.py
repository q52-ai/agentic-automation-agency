"""The agency: scout -> qualifier -> proposal writer -> demo builder, then the owner reviews and applies."""
import asyncio
import hashlib
import threading
import time
from datetime import date, datetime

from .agents import builder, qualifier, writer
from .agents.llm import Claude, has_credentials
from .db import DB, PIPELINE, READY
from .events import EventBus
from .sources import Posting, build_sources

# Keep this much of the day's budget free before starting each kind of Claude call.
RESERVE = {"qualify": 0.02, "write": 0.15, "build": 0.80}
# What the owner can do to a gig from the dashboard, and the status it moves to.
ACTIONS = {"applied": "applied", "skipped": "skipped", "won": "won", "lost": "lost",
           "delivered": "delivered", "paid": "paid", "pursue": "shortlisted"}


class Agency:
    def __init__(self, settings):
        self.s = settings
        self.db = DB(settings.db_path)
        self.bus = EventBus(self.db)
        self.emit = self.bus.emit
        self.feeds, self.boards = build_sources(settings)
        self.claude = Claude(settings, self.db, self.emit) if has_credentials() else None
        self.status = "running"
        self.busy = False
        self.bus.cycle = self.db.get_state("cycle", 0)
        self._wake = None
        self._cycle_lock = threading.Lock()

    # --- scouting -----------------------------------------------------------------------
    def _scout(self):
        sources = list(self.feeds)
        if time.time() - self.db.get_state("boards_swept", 0) >= self.s.boards_hours * 3600:
            sources += self.boards
        status = self.db.get_state("sources", {})
        cutoff = time.time() - self.s.max_age_days * 86400
        total_new = 0
        for src in sources:
            started = time.time()
            try:
                postings = src.fetch()
            except Exception as e:  # one broken source shouldn't stop the others
                status[src.name] = {**status.get(src.name, {}), "ok": False, "error": str(e)[:200], "ts": started}
                self.emit("scout", "error", f"{src.name}: {e}")
                continue
            known = self.db.known(p.uid for p in postings)
            new = [p for p in postings if p.uid not in known]
            leads = 0
            for p in new:
                is_lead = p.looks_like_gig() and (not p.posted_at or p.posted_at >= cutoff)
                self.db.add_posting(p, "found" if is_lead else "ignored")
                leads += is_lead
            total_new += leads
            status[src.name] = {"ok": True, "error": "", "ts": started, "postings": len(postings), "new": len(new),
                                "leads": leads, "seconds": round(time.time() - started, 1)}
            self.emit("scout", "scan", f"{src.name}: {len(postings)} postings, {len(new)} new, "
                      f"{leads} look like freelance or contract work", source=src.name, leads=leads)
        if any(src in sources for src in self.boards):
            self.db.set_state("boards_swept", time.time())
        self.db.set_state("sources", status)
        return total_new

    # --- Claude agents --------------------------------------------------------------------
    def _qualify(self):
        pending = self.db.by_status("found", order="found_at DESC", limit=300)
        while pending and self.claude.remaining() > RESERVE["qualify"]:
            batch, pending = pending[:self.s.qualify_batch], pending[self.s.qualify_batch:]
            self.emit("qualifier", "thinking", f"Screening {len(batch)} postings: "
                      + "; ".join(g["title"][:50] for g in batch))
            results, cost = qualifier.qualify(self.claude, self.s, batch)
            tally = {"shortlisted": 0, "maybe": 0, "rejected": 0}
            for g in batch:
                a = results.get(g["uid"])
                if not a:
                    continue
                if a["verdict"] == "pursue" and a["fit"] >= self.s.min_fit:
                    status = "shortlisted"
                elif a["verdict"] in ("pursue", "maybe"):
                    status = "maybe"
                else:
                    status = "rejected"
                tally[status] += 1
                self.db.update(g["uid"], status=status, fit=a["fit"], assessment=a)
                kind = {"shortlisted": "shortlist", "maybe": "maybe", "rejected": "reject"}[status]
                who = f" ({g['company'][:30]})" if g["company"] else ""
                self.emit("qualifier", kind, f"{g['title'][:70]}{who} · fit {a['fit']} · {a['reason']}",
                          uid=g["uid"], fit=a["fit"])
            self.emit("qualifier", "summary", f"Screened {len(batch)}: {tally['shortlisted']} shortlisted, "
                      f"{tally['maybe']} maybe, {tally['rejected']} rejected · ${cost:.4f}", cost_usd=round(cost, 4))
            if not results:
                break  # an API error or refusal; try again next cycle

    def _profile(self):
        try:
            return self.s.profile_path.read_text()
        except OSError:
            return "(No agency profile yet. Write generically and leave [YOUR NAME] placeholders.)"

    def _write(self):
        for g in self.db.by_status("shortlisted", limit=self.s.proposals_per_cycle):
            if self.claude.remaining() < RESERVE["write"]:
                self._budget_note()
                return
            self.emit("writer", "thinking", f"Drafting a proposal for {g['title'][:70]} (fit {g['fit']})")
            data, cost = writer.write(self.claude, self.s, g, self._profile())
            if not data:
                continue
            self.db.update(g["uid"], status="drafted", proposal=data)
            demo = "demo planned" if data["demo_worth_building"] else "no demo needed"
            self.emit("writer", "draft", f"Proposal ready: {g['title'][:70]} · quote {data['price_quote'][:80]} · {demo}"
                      f" · ${cost:.3f}", uid=g["uid"], cost_usd=round(cost, 4))

    def _build(self):
        queue = self.db.get_state("build_queue", [])
        today = date.today().isoformat()
        built_today = self.db.get_state(f"demos:{today}", 0)
        candidates = [self.db.get(uid) for uid in queue]
        if built_today < self.s.demos_per_day:
            candidates += [g for g in self.db.by_status("drafted")
                           if g["proposal"].get("demo_worth_building") and not g["demo"]]
        for g in candidates:
            if not g or g["status"] not in ("drafted", "shortlisted", "maybe"):
                if g and g["uid"] in queue:  # skipped or applied since it was queued
                    queue.remove(g["uid"])
                    self.db.set_state("build_queue", queue)
                continue
            if self.claude.remaining() < RESERVE["build"]:
                self._budget_note()
                return
            if not g["proposal"]:
                continue  # needs a proposal (and its demo brief) first; the writer picks it up
            self.db.set_state("build_queue", [u for u in queue if u != g["uid"]])
            self.db.update(g["uid"], status="building")
            self.emit("builder", "thinking", f"Building a demo for {g['title'][:70]}: {g['proposal']['demo_brief'][:160]}")
            demo, cost = builder.build(self.claude, self.s, g)
            if not demo:
                self.db.update(g["uid"], status="drafted", demo={"failed": True})
                continue
            self.db.update(g["uid"], status="demo_ready", demo=demo)
            self.db.add_state(f"demos:{today}", 1)
            note = f" (skipped unsafe or oversized files: {', '.join(demo['skipped'])})" if demo["skipped"] else ""
            self.emit("builder", "demo", f"Demo ready for {g['title'][:60]}: {len(demo['files'])} files in "
                      f"{demo['dir']}{note} · ${cost:.3f}", uid=g["uid"], cost_usd=round(cost, 4))
            return  # one demo per cycle keeps any single cycle short

    def _budget_note(self):
        today = date.today().isoformat()
        if self.db.get_state("budget_noted") != today:
            self.db.set_state("budget_noted", today)
            self.emit("agency", "info", f"Claude budget nearly used for today (${self.db.spent_today():.2f} of "
                      f"${self.s.daily_budget:.2f}); proposals and demos resume tomorrow.")

    # --- the cycle -------------------------------------------------------------------------
    def run_cycle(self):
        with self._cycle_lock:
            self.busy = True
            try:
                self.bus.cycle += 1
                self.db.set_state("cycle", self.bus.cycle)
                self.emit("agency", "cycle", f"Cycle {self.bus.cycle} started")
                new = self._scout()
                if self.claude:
                    self._qualify()
                    self._write()
                    self._build()
                elif new:
                    self.emit("agency", "info", "Add ANTHROPIC_API_KEY to .env to screen these leads and write proposals.")
                c = self.db.counts()
                self.emit("agency", "cycle", f"Cycle {self.bus.cycle} done: {new} new leads · "
                          f"{sum(c.get(s, 0) for s in READY)} proposals waiting for you · "
                          f"Claude today ${self.db.spent_today():.2f} of ${self.s.daily_budget:.2f}")
            except Exception as e:
                self.emit("agency", "error", f"Cycle failed: {e!r}")
            finally:
                self.busy = False

    async def run(self):
        self._wake = asyncio.Event()
        self.emit("agency", "info", f"Agency online · scouting {', '.join(x.name for x in self.feeds + self.boards)} · "
                  f"Claude {'on' if self.claude else 'off (no API key)'}")
        while True:
            if self.status == "running":
                await asyncio.to_thread(self.run_cycle)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.s.scout_minutes * 60)
            except TimeoutError:
                pass

    # --- dashboard controls -------------------------------------------------------------------
    def control(self, action):
        if action == "pause":
            self.status = "paused"
            self.emit("you", "control", "Paused from the dashboard")
        elif action == "resume":
            self.status = "running"
            self.emit("you", "control", "Resumed from the dashboard")
            self._wake.set()
        elif action == "step":
            self.emit("you", "control", "Asked for a cycle now")
            if self.status == "paused":
                threading.Thread(target=self.run_cycle, daemon=True).start()
            else:
                self._wake.set()
        else:
            raise ValueError(action)

    def gig_action(self, uid, action, revenue=None, message=None):
        g = self.db.get(uid)
        if not g:
            raise KeyError(uid)
        title = g["title"][:70]
        if action == "save":
            proposal = {**(g["proposal"] or {}), "message": message or ""}
            self.db.update(uid, proposal=proposal)
            self.emit("you", "edit", f"Edited the proposal for {title}", uid=uid)
        elif action == "build":
            queue = self.db.get_state("build_queue", [])
            if uid not in queue:
                self.db.set_state("build_queue", queue + [uid])
            if not g["proposal"]:
                self.db.update(uid, status="shortlisted")  # the writer drafts it first, then the builder runs
            self.emit("you", "queue", f"Asked for a demo of {title}", uid=uid)
            self._wake.set()
        elif action in ACTIONS:
            fields = {"status": ACTIONS[action]}
            if action == "paid":
                fields["revenue"] = float(revenue or 0)
            self.db.update(uid, **fields)
            extra = f" · ${float(revenue or 0):,.2f}" if action == "paid" else ""
            self.emit("you", action, f"Marked {action}: {title}{extra}", uid=uid)
            if action == "pursue":
                self._wake.set()
        else:
            raise ValueError(action)

    def add_manual(self, url, title, text):
        key = hashlib.sha1((url or text).encode()).hexdigest()[:12]
        p = Posting(source="manual", external_id=key, url=url, title=title or url or text[:80], body=text,
                    kind="freelance")
        if self.db.known([p.uid]):
            return p.uid, False
        self.db.add_posting(p, "found")
        self.emit("you", "add", f"Added a posting by hand: {p.title[:80]}", uid=p.uid)
        self._wake.set()
        return p.uid, True

    # --- dashboard snapshot ----------------------------------------------------------------------
    def state(self):
        c = self.db.counts()
        midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
        return {
            "status": self.status, "busy": self.busy, "cycle": self.bus.cycle,
            "controls_locked": bool(self.s.dashboard_password),
            "claude_on": bool(self.claude),
            "models": {"qualifier": self.s.qualifier_model, "writer": self.s.writer_model, "builder": self.s.builder_model},
            "spend_today": self.db.spent_today(), "spend_total": self.db.get_state("cost:total", 0.0),
            "spend_by_agent": {a: self.db.get_state(f"cost:{a}", 0.0) for a in ("qualifier", "writer", "builder")},
            "budget": self.s.daily_budget,
            "demos_today": self.db.get_state(f"demos:{date.today().isoformat()}", 0),
            "demos_per_day": self.s.demos_per_day,
            "min_fit": self.s.min_fit, "scout_minutes": self.s.scout_minutes,
            "counts": c, "found_today": self.db.found_since(midnight),
            "leads_today": self.db.found_since(midnight, leads_only=True), "revenue": self.db.revenue(),
            "sources": self.db.get_state("sources", {}),
            "ready": self.db.by_status(*READY),
            "pipeline": self.db.by_status(*PIPELINE, order="updated_at DESC", limit=200),
            "screened": self.db.screened(80),
            "build_queue": self.db.get_state("build_queue", []),
            "events": self.db.events(600),
        }

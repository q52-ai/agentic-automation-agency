"""Event bus: every agent message is written to the database and pushed live to dashboard viewers."""
import asyncio
import threading


def _put(queue, event):
    if not queue.full():
        queue.put_nowait(event)


class EventBus:
    def __init__(self, db):
        self.db = db
        self.cycle = 0
        self._subs = set()
        self._lock = threading.Lock()

    def emit(self, agent, kind, message, **data):
        event = self.db.add_event(self.cycle, agent, kind, message, data)
        print(f"[{self.cycle:>4}] {agent:<10} {kind:<10} {message}", flush=True)
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            loop.call_soon_threadsafe(_put, queue, event)
        return event

    def subscribe(self):
        token = (asyncio.get_running_loop(), asyncio.Queue(maxsize=1000))
        with self._lock:
            self._subs.add(token)
        return token

    def unsubscribe(self, token):
        with self._lock:
            self._subs.discard(token)

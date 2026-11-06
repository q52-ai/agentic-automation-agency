"""Web dashboard: the UI, a state snapshot, a live event stream, controls and gig actions."""
import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..agency import Agency

STATIC = Path(__file__).parent / "static"


class GigAction(BaseModel):
    action: str
    revenue: float | None = None
    message: str | None = None


class ManualPosting(BaseModel):
    url: str = ""
    title: str = ""
    text: str


def create_app(settings):
    agency = Agency(settings)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(agency.run())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan)

    def check_password(x_agency_password: str | None = Header(default=None)):
        password = settings.dashboard_password
        if password and not secrets.compare_digest((x_agency_password or "").encode(), password.encode()):
            raise HTTPException(401, "wrong or missing dashboard password")

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    async def state():
        return await asyncio.to_thread(agency.state)

    @app.get("/api/stream")
    async def stream():
        token = agency.bus.subscribe()
        queue = token[1]

        async def events():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {json.dumps(event)}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                agency.bus.unsubscribe(token)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/control/{action}", dependencies=[Depends(check_password)])
    async def control(action: str):
        try:
            agency.control(action)
        except ValueError:
            raise HTTPException(400, f"unknown action {action}")
        return {"status": agency.status}

    @app.post("/api/gig/{uid:path}", dependencies=[Depends(check_password)])
    async def gig(uid: str, body: GigAction):
        try:
            await asyncio.to_thread(agency.gig_action, uid, body.action, body.revenue, body.message)
        except KeyError:
            raise HTTPException(404, "no such gig")
        except ValueError:
            raise HTTPException(400, f"unknown action {body.action}")
        return {"ok": True}

    @app.post("/api/postings", dependencies=[Depends(check_password)])
    async def add_posting(body: ManualPosting):
        if not body.text.strip():
            raise HTTPException(400, "paste the posting text")
        uid, added = await asyncio.to_thread(agency.add_manual, body.url.strip(), body.title.strip(), body.text.strip())
        return {"uid": uid, "added": added}

    return app

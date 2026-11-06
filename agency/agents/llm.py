"""One shared Claude client for every agent: structured JSON replies, refusal handling, cost tracking, daily budget."""
import json
import os
from datetime import date

import anthropic

# USD per million tokens: (input, output, cache read, cache write).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
# Server-side fallback on a safety refusal; Haiku has none.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


def has_credentials():
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


class Claude:
    def __init__(self, settings, db, emit):
        self.s, self.db, self.emit = settings, db, emit
        # Keys that aren't scoped to a workspace must name one on every request.
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
        self.client = anthropic.Anthropic(**({"default_headers": {"anthropic-workspace-id": workspace}} if workspace else {}))

    def remaining(self):
        return self.s.daily_budget - self.db.spent_today()

    def _cost(self, model, usage):
        pin, pout, pread, pwrite = PRICES.get(model, PRICES["claude-opus-5-5"])
        return (usage.input_tokens * pin + usage.output_tokens * pout
                + (getattr(usage, "cache_read_input_tokens", 0) or 0) * pread
                + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * pwrite) / 1e6

    def ask(self, agent, model, system, prompt, schema, max_tokens=16000, effort="medium", stream=False):
        """Returns (parsed JSON or None, cost in USD). Every call's cost is charged to today's budget."""
        kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": prompt}],
                      output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}})
        if model in FALLBACK_MODELS:
            # If a safety classifier declines the request, let the API retry it on a fallback model.
            kwargs |= dict(extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                           extra_body={"fallbacks": "default"})
        try:
            if stream:  # long outputs (the demo builder) stream to stay clear of HTTP timeouts
                with self.client.messages.stream(**kwargs) as s:
                    resp = s.get_final_message()
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.APIError as e:
            self.emit(agent, "error", f"Claude API error: {e}")
            return None, 0.0

        cost = self._cost(model, resp.usage)
        self.db.add_state(f"cost:{date.today().isoformat()}", cost)
        self.db.add_state(f"cost:{agent}", cost)
        self.db.add_state("cost:total", cost)
        if resp.stop_reason == "refusal":
            self.emit(agent, "error", "Claude declined this request; skipping it.", cost_usd=round(cost, 4))
            return None, cost
        if resp.stop_reason == "max_tokens":
            self.emit(agent, "error", "Claude ran out of room before finishing; skipping it.", cost_usd=round(cost, 4))
            return None, cost
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            return json.loads(text), cost
        except json.JSONDecodeError:
            self.emit(agent, "error", "Claude's reply wasn't valid JSON; skipping it.", cost_usd=round(cost, 4))
            return None, cost

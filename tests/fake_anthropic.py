"""A tiny stand-in for the Anthropic Messages API, for exercising the real Claude engine.

Serves POST /v1/messages over HTTP: streaming requests get server-sent events, and a
request with a JSON output format gets a valid Boardroom verdict back. Every request
body is recorded so tests can check what the engine sent.

Run standalone:  python tests/fake_anthropic.py 8767
Then:            ANTHROPIC_API_KEY=x ANTHROPIC_BASE_URL=http://127.0.0.1:8767 python -m boardroom
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERDICT = {
    "headline": "Take the sabbatical, with a return date.",
    "verdict": "The board backs a fixed-length break with a plan for coming back.",
    "confidence": 74,
    "votes": [
        {"advisor": "analyst", "position": "for", "reason": "The savings cover it."},
        {"advisor": "skeptic", "position": "mixed", "reason": "Only with a return date."},
        {"advisor": "strategist", "position": "for", "reason": "Negotiate unpaid leave first."},
        {"advisor": "operator", "position": "for", "reason": "Six months fits the plan."},
    ],
    "risks": ["Drifting past the return date.", "Losing touch with your network."],
    "first_move": "Ask your manager about unpaid leave this week.",
    "steps": [
        {"title": "Talk to your manager", "detail": "Ask about unpaid leave.", "when": "This week"},
        {"title": "Set a budget", "detail": "Six months of costs, written down.", "when": "This month"},
        {"title": "Pick a return date", "detail": "Put it in the calendar.", "when": "Before leaving"},
    ],
    "review": "Halfway through, check the budget and your energy.",
    "review_in_days": 90,
    "options": [
        {"name": "Six-month sabbatical", "score": 80, "summary": "Rest with a clear way back."},
        {"name": "Quit outright", "score": 35, "summary": "Freedom, but no safety net."},
    ],
}

REMARK = "Here is my take: plan it carefully, and **set a firm return date** before you go."


class Handler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Handler.requests.append({"path": self.path, "beta": self.headers.get("anthropic-beta"), "body": body})
        wants_verdict = bool((body.get("output_config") or {}).get("format"))
        text = json.dumps(VERDICT) if wants_verdict else REMARK
        message = {
            "id": "msg_fake", "type": "message", "role": "assistant", "model": body["model"],
            "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 300},
        }
        if not body.get("stream"):
            out = json.dumps({**message, "content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def event(kind: str, data: dict) -> None:
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())

        event("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}})
        event("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        for i in range(0, len(text), 24):
            event("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[i:i + 24]}})
        event("content_block_stop", {"type": "content_block_stop", "index": 0})
        event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 300}})
        event("message_stop", {"type": "message_stop"})


def start(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start the fake API on a background thread; returns the server and its base URL."""
    Handler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


if __name__ == "__main__":
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8767)
    print(f"Fake Anthropic API on {url}")
    threading.Event().wait()

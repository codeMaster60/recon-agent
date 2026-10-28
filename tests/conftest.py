"""Shared fixtures: a sample month on disk, and a local fake LLM server.

The fake server speaks the real OpenAI-compatible HTTP protocol, so the actual network client in
recon/llm.py is exercised end to end, without an API key or internet access.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "data", ROOT / "eval"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import generate  # noqa: E402

from recon.parse import inr  # noqa: E402

HINDI_MAPPING = {
    "date": "लेनदेन तिथि",
    "description": "विवरण",
    "ref": "संदर्भ संख्या",
    "debit": "नामे",
    "credit": "जमा",
    "balance": "शेष",
}
LLM_ENV = ("RECON_LLM_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "RECON_LLM_BASE_URL", "RECON_LLM_MODEL")


@pytest.fixture(scope="session")
def month(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples")
    data = generate.build(seed=11)
    generate.write(data, out)
    return out, {(t["type"], t["key"]) for t in data["truth"]}


@pytest.fixture(autouse=True)
def no_llm_env(monkeypatch):
    """Every test starts with no LLM configured, whatever the developer's shell has."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    def do_POST(self):
        server = self.server
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        server.requests.append({"headers": dict(self.headers), "body": body})
        if server.mode == "http_error":
            self.send_response(500)
            self.end_headers()
            return
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        if server.mode == "not_json":
            payload = b"<html>gateway error</html>"
        elif server.mode == "bad_shape":
            payload = json.dumps({"error": "nope"}).encode()
        else:
            if "map spreadsheet columns" in system:
                headers = json.loads(user.split("Column headers (exact strings):\n", 1)[1].split("\n\n", 1)[0])
                content = json.dumps(HINDI_MAPPING if "विवरण" in headers else {}, ensure_ascii=False)
            else:
                facts = json.loads(user)
                content = f"Rs {inr(facts['stats']['at_risk_high'])} needs action now."
            payload = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def llm_server(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.mode = "ok"
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    monkeypatch.setenv("RECON_LLM_API_KEY", "test-key")
    monkeypatch.setenv("RECON_LLM_BASE_URL", server.base_url)
    monkeypatch.setenv("RECON_LLM_MODEL", "fake-model")
    yield server
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------- small hand-built frames


def make_report(rows):
    """Canonical settlement-report frame from a few dicts (credit/debit derived like Razorpay's)."""
    import pandas as pd
    from datetime import date

    base = {
        "fee": 0.0,
        "tax": 0.0,
        "on_hold": False,
        "settled": True,
        "order_receipt": "",
        "method": "upi",
        "created_at": date(2026, 9, 1),
        "settlement_id": "",
        "settlement_utr": "",
        "settled_at": None,
    }
    frame = pd.DataFrame([{**base, **r} for r in rows])
    frame["credit"] = frame.apply(
        lambda r: r["amount"] - r["fee"] - r["tax"] if r["type"] == "payment" else 0.0, axis=1
    )
    frame["debit"] = frame.apply(lambda r: r["amount"] if r["type"] == "refund" else 0.0, axis=1)
    return frame


def make_bank(rows):
    import pandas as pd

    return pd.DataFrame([{"ref": "", "balance": None, **r} for r in rows]).assign(row=lambda f: range(len(f)))

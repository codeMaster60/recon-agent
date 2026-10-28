"""Planted-bug check: inject one realistic bug at a time into a copy of the repo and confirm the
test suite fails. A test suite can reach 100% coverage and still miss bugs; this is the check for that.

    python tests/mutation_check.py            # takes a few minutes
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
WORK = Path(tempfile.mkdtemp()) / "repo"

MUTANTS = [
    ("recon/engine.py", "gst_rate: float = 0.18", "gst_rate: float = 0.19", "GST rate wrong"),
    (
        "recon/engine.py",
        'kind = "short_credit" if diff < 0 else "excess_credit"',
        'kind = "short_credit" if diff > 0 else "excess_credit"',
        "short/excess swapped",
    ),
    ("recon/engine.py", "carry = min(value, 0.0)", "carry = 0.0", "refund carry-forward dropped"),
    (
        "recon/engine.py",
        "return -1 <= (bank_date - settled_at).days <= cfg.max_lag_days",
        "return -1 <= (bank_date - settled_at).days <= 0",
        "posting lag ignored",
    ),
    (
        "recon/engine.py",
        'if not p["settled"] and not p["on_hold"] and due:',
        'if not p["settled"] and due:',
        "on-hold payments flagged",
    ),
    (
        "recon/engine.py",
        "elif len(pays) > 1 and collected - back > amount + cfg.money_tolerance:",
        "elif len(pays) > 1 and collected > amount + cfg.money_tolerance:",
        "refunds ignored in duplicate check",
    ),
    ("recon/engine.py", "if len(utr) >= 8:", "if len(utr) >= 80:", "UTR matching disabled"),
    ("recon/engine.py", "if gap <= cfg.max_pair_gap and in_lag(", "if gap <= 0 and in_lag(", "pass-3 pairing disabled"),
    ("recon/ingest.py", "if flipped > straight + 0.2:", "if False:", "swapped-column repair removed"),
    (
        "recon/ingest.py",
        "abs(c or 0.0) - abs(d or 0.0)",
        "abs(c or 0.0) + abs(d or 0.0)",
        "debits added instead of subtracted",
    ),
    ("recon/ingest.py", "RULES_FAST_PATH = 0.95", "RULES_FAST_PATH = 0.0", "auto mode never asks the LLM"),
    (
        "recon/ingest.py",
        '"cancel", "fail", "void", "refund", "reject"',
        '"cancel", "fail", "void", "reject"',
        "refunded orders seen as paid",
    ),
    (
        "recon/parse.py",
        'DATE_FORMATS = [\n    "%d/%m/%y",',
        'DATE_FORMATS = [\n    "%m/%d/%y",\n    "%m/%d/%Y",\n    "%d/%m/%y",',
        "dates read month-first",
    ),
    (
        "recon/parse.py",
        "sum(c.isdigit() for c in t) >= 6",
        "sum(c.isdigit() for c in t) >= 0",
        "run-together words taken as UTRs",
    ),
    (
        "recon/report.py",
        "invented = {n for n in _numbers(text) - allowed if n >= 10}",
        "invented = set()",
        "hallucinated numbers allowed",
    ),
    (
        "recon/report.py",
        '<p class="rc-summary">{escape(summary)}</p>',
        '<p class="rc-summary">{summary}</p>',
        "HTML not escaped",
    ),
    ("recon/llm.py", 'f"Bearer {self.api_key}"', '"Bearer x"', "API key not sent"),
    ("app.py", "if vote or comment:", "if vote and comment:", "feedback not recorded"),
    (
        "recon/look.py",
        "kinds.setdefault(e.type, []).append(e)",
        "kinds.setdefault(e.key, []).append(e)",
        "issues not grouped by kind",
    ),
    ("app.py", "        if client is None:", "        if client is not None:", "wrong message when AI is off"),
]


def main():
    caught = 0
    for i, (path, old, new, label) in enumerate(MUTANTS, 1):
        shutil.rmtree(WORK, ignore_errors=True)
        shutil.copytree(SRC, WORK, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".coverage"))
        target = WORK / path
        text = target.read_text()
        assert text.count(old) == 1, (path, old)
        target.write_text(text.replace(old, new))
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
            cwd=WORK,
            capture_output=True,
            text=True,
            timeout=600,
        )
        killed = r.returncode != 0
        caught += killed
        failing = next((ln.split(" ")[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")), "-")
        print(f"{i:2}. {'CAUGHT' if killed else 'MISSED'}  {label:40} {failing}", flush=True)
    print(f"\n{caught}/{len(MUTANTS)} planted bugs caught")
    shutil.rmtree(WORK.parent, ignore_errors=True)
    sys.exit(0 if caught == len(MUTANTS) else 1)


if __name__ == "__main__":
    main()

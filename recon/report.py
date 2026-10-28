"""Turn a reconciliation Result into something a shop owner reads: a short summary + HTML/CSV.

The LLM may rewrite the summary in plainer words, but it is not allowed to introduce numbers:
every figure in its reply must already exist in the facts we gave it, or we fall back to the
template. Money is the one place a hallucinated digit is not acceptable.
"""

from __future__ import annotations

import html
import json
import re

from .engine import Result
from .llm import LLMClient, LLMError
from .parse import inr

SEVERITY_LABEL = {"high": "Act now", "medium": "Check", "low": "FYI"}


def template_summary(result: Result) -> str:
    s = result.stats
    if not result.exceptions:
        return (f"All clear. {s['settlements_matched']} payouts matched the bank exactly "
                f"(Rs {inr(s['received_payouts'])}). No fee, GST or order problems found.")
    high = [e for e in result.exceptions if e.severity == "high"]
    lines = [
        f"{len(result.exceptions)} issues found, Rs {inr(s['at_risk_high'])} needs action now "
        f"({len(high)} high-priority).",
        f"Payouts: {s['settlements_matched']} of {s['settlements_in_period']} matched the bank exactly; "
        f"expected Rs {inr(s['expected_payouts'])}, received Rs {inr(s['received_payouts'])}.",
    ]
    for e in result.exceptions[:3]:
        lines.append(f"- {e.title}: Rs {inr(e.amount_at_risk)}. {e.action}")
    return "\n".join(lines)


def _numbers(text: str) -> set[float]:
    found = set()
    for token in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            found.add(round(float(token.replace(",", "")), 2))
        except ValueError:
            pass
    return found


def _allowed_numbers(facts: dict) -> set[float]:
    allowed: set[float] = set()

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.update({round(float(value), 2), float(round(value))})
        elif isinstance(value, str):
            allowed.update(_numbers(value))

    walk(facts)
    return allowed


def llm_summary(result: Result, client: LLMClient) -> tuple[str, bool]:
    """Return (summary, used_llm). Falls back to the template on any error or invented number."""
    facts = {
        "stats": {k: v for k, v in result.stats.items() if k != "by_type"},
        "issues_by_type": result.stats["by_type"],
        "top_issues": [
            {"title": e.title, "severity": e.severity, "amount": e.amount_at_risk, "detail": e.detail, "action": e.action}
            for e in result.exceptions[:6]
        ],
        "notes": result.notes,
    }
    system = ("You write a reconciliation summary for the owner of a small Indian business. Plain English, "
              "no jargon, max 6 short lines. Lead with the money that needs action. Use ONLY numbers that "
              "appear in the facts JSON; never compute new totals. Write rupees as 'Rs'.")
    try:
        text = client.chat(system, json.dumps(facts, default=str), json_mode=False).strip()
    except LLMError:
        return template_summary(result), False
    allowed = _allowed_numbers(facts)
    invented = {n for n in _numbers(text) - allowed if n >= 10}  # ignore list numbering and "3 issues"
    if invented or not text:
        return template_summary(result), False
    return text, True


def to_html(result: Result, summary: str, mapping_notes: list[str] | None = None, title: str = "Reconciliation report") -> str:
    s = result.stats
    rows = "\n".join(
        f"<tr class='{e.severity}'><td><span class='pill {e.severity}'>{SEVERITY_LABEL[e.severity]}</span></td>"
        f"<td>{html.escape(e.title)}</td><td class='num'>Rs {inr(e.amount_at_risk)}</td>"
        f"<td>{html.escape(e.detail)}<div class='action'>{html.escape(e.action)}</div></td></tr>"
        for e in result.exceptions
    ) or "<tr><td colspan='4'>No issues found.</td></tr>"
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in result.notes + (mapping_notes or []))
    tiles = [
        ("Needs action", f"Rs {inr(s['at_risk_high'])}"),
        ("Payouts matched", f"{s['settlements_matched']} / {s['settlements_in_period']}"),
        ("Expected vs received", f"Rs {inr(s['expected_payouts'])} / Rs {inr(s['received_payouts'])}"),
        ("Fees + GST paid", f"Rs {inr(s['fees'] + s['gst'])}"),
    ]
    tiles_html = "".join(f"<div class='tile'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in tiles)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a64;--line:#e5e2da;--high:#b42318;--med:#b54708;--low:#475467;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#171715;--fg:#ecebe6;--muted:#a3a29b;--line:#32312d;--card:#201f1d;--high:#f97066;--med:#fdb022;--low:#98a2b3}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:32px 16px}}
h1{{font-size:24px;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 24px}}
.summary{{white-space:pre-line;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:20px}}
.tiles{{margin:0 -6px 24px;font-size:0}}
.tile{{display:inline-block;vertical-align:top;box-sizing:border-box;width:calc(25% - 12px);margin:6px;font-size:15px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
@media (max-width:720px){{.tile{{width:calc(50% - 12px)}}}} .k{{color:var(--muted);font-size:13px}} .v{{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}}
.wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}} th{{font-size:13px;color:var(--muted);font-weight:500}}
.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} .action{{color:var(--muted);font-size:13px;margin-top:4px}}
.pill{{font-size:12px;font-weight:600;padding:2px 8px;border-radius:99px;border:1px solid currentColor;white-space:nowrap}}
.pill.high{{color:var(--high)}} .pill.medium{{color:var(--med)}} .pill.low{{color:var(--low)}}
ul{{color:var(--muted);font-size:13px}}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">Statement {s['statement_from']} to {s['statement_to']} · {s['payments']} payments · Rs {inr(s['gross_collected'])} collected</p>
<div class="summary">{html.escape(summary)}</div>
<div class="tiles">{tiles_html}</div>
<div class="wrap"><table><thead><tr><th>Priority</th><th>Issue</th><th class="num">Amount</th><th>Details and next step</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<ul>{notes}</ul>
</main></body></html>"""

"""Turn a reconciliation Result into something a shop owner reads: a short summary and an HTML report.

The LLM may rewrite the summary in plainer words, but it is not allowed to introduce numbers:
every figure in its reply must already exist in the facts we gave it, or we fall back to the
template. Money is the one place a made-up digit is not acceptable.
"""

from __future__ import annotations

import json
import re
from datetime import date
from html import escape

from .engine import Result
from .llm import LLMClient, LLMError
from .look import CSS, SEVERITY_LABEL, issues_html, mark_svg, tiles_html
from .parse import inr

__all__ = ["SEVERITY_LABEL", "llm_summary", "template_summary", "to_html"]

# How each high-priority problem reads in a sentence: (one, many)
PHRASES = {
    "missing_payout": ("a payout that never arrived", "payouts that never arrived"),
    "short_credit": ("a payout that came in short", "payouts that came in short"),
    "unsettled_payment": ("a payment that still isn't settled", "payments that still aren't settled"),
    "duplicate_payment": ("a customer charged twice", "customers charged twice"),
    "order_without_payment": ("an order marked paid with no payment", "orders marked paid with no payment"),
    "paid_on_cancelled_order": ("a cancelled order nobody refunded", "cancelled orders nobody refunded"),
}


def template_summary(result: Result) -> str:
    s = result.stats
    payouts = s["settlements_in_period"]
    if not result.exceptions:
        if payouts:
            which = "The one payout" if payouts == 1 else f"All {payouts} payouts"
            return (
                f"Everything lines up. {which} in this statement reached your bank to the paisa, "
                "and the fees and GST look right."
            )
        return "Nothing looks wrong. Add the bank statement for the same dates if you want the payouts checked too."

    parts = []
    if payouts:
        parts.append(f"{s['settlements_matched']} of {payouts} payouts reached your bank exactly as expected.")
    high = [e for e in result.exceptions if e.severity == "high"]
    if high:
        totals: dict[str, list[float]] = {}
        for e in high:
            totals.setdefault(e.type, []).append(e.amount_at_risk)
        top, amounts = max(totals.items(), key=lambda kv: sum(kv[1]))
        one, many = PHRASES.get(top, ("problem", "problems"))
        what = one if len(amounts) == 1 else f"{len(amounts)} {many}"
        if len(totals) == 1:
            parts.append(f"₹{inr(s['at_risk_high'])} needs a look now: {what}.")
        else:
            lead = "most of it from" if sum(amounts) >= s["at_risk_high"] / 2 else "including"
            parts.append(f"₹{inr(s['at_risk_high'])} needs a look now, {lead} {what} (₹{inr(sum(amounts))}).")
    rest = len(result.exceptions) - len(high)
    if rest:
        parts.append(f"{'There is 1 smaller thing' if rest == 1 else f'There are {rest} smaller things'} below.")
    return " ".join(parts)


def _numbers(text: str) -> set[float]:
    return {round(float(t.replace(",", "")), 2) for t in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


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
            {
                "title": e.title,
                "severity": e.severity,
                "amount": e.amount_at_risk,
                "detail": e.detail,
                "action": e.action,
            }
            for e in result.exceptions[:6]
        ],
        "notes": result.notes,
    }
    system = (
        "You write a short reconciliation summary for the owner of a small Indian business. Plain, friendly "
        "English, three or four sentences, no headings or bullet points. Lead with the money that needs action. "
        "Use ONLY numbers that appear in the facts JSON; never add up or compute new totals. Write rupees as ₹."
    )
    try:
        text = client.chat(system, json.dumps(facts, default=str), json_mode=False).strip()
    except LLMError:
        return template_summary(result), False
    allowed = _allowed_numbers(facts)
    invented = {n for n in _numbers(text) - allowed if n >= 10}  # ignore list numbering and "3 issues"
    if invented or not text:
        return template_summary(result), False
    return text, True


def to_html(result: Result, summary: str, mapping_notes: list[str] | None = None, title: str = "Payout check") -> str:
    """A standalone report in the same look as the app. Fonts load from Google if online, else system fonts."""
    s = result.stats
    if s["statement_from"]:
        start, end = date.fromisoformat(s["statement_from"]), date.fromisoformat(s["statement_to"])
        period = f"{start.day} {start:%b} to {end.day} {end:%b} {end.year}"
    else:
        period = "no bank statement uploaded"
    notes = "".join(f'<p class="rc-fine">{escape(n)}</p>' for n in result.notes + (mapping_notes or []))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#fff;color:#15181E;font:16px/1.6 "IBM Plex Sans",system-ui,-apple-system,sans-serif}}
main{{max-width:780px;margin:0 auto;padding:36px 20px 24px}}
{CSS}
</style></head><body><main>
<div class="rc-nav"><span class="rc-brand">{mark_svg()}Recon Agent</span><span class="rc-fine">{escape(period)}</span></div>
<div class="rc-h1">{escape(title)}</div>
<p class="rc-sub">{s["payments"]} payments, ₹{inr(s["gross_collected"])} collected, ₹{inr(s["refunds"])} refunded.</p>
{tiles_html(s)}
<p class="rc-summary">{escape(summary)}</p>
{issues_html(result.exceptions)}
<div style="margin-top:28px">{notes}</div>
<div class="rc-foot"><span>Made with Recon Agent from your own exports.</span><span>Nothing was stored.</span></div>
</main></body></html>"""

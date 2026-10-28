"""The look shared by the web app and the downloadable report: white, IBM Plex, one deep green.

Plain HTML strings, so the same pieces render inside Streamlit and in a standalone file.
"""

from __future__ import annotations

from html import escape

from .parse import inr

GREEN = "#0D5C42"
SEVERITY_LABEL = {"high": "Act now", "medium": "Worth a check", "low": "Good to know"}

FIELD_LABELS = {
    "date": "Date",
    "value_date": "Value date",
    "description": "Narration",
    "ref": "Reference / UTR",
    "debit": "Money out",
    "credit": "Money in",
    "amount": "Amount",
    "drcr": "Credit or debit",
    "balance": "Balance",
    "order_ref": "Order ID",
    "status": "Status",
    "created_at": "Date",
    "customer": "Customer",
    "entity_id": "Payment or refund ID",
    "type": "Type",
    "fee": "Fee",
    "tax": "GST on fee",
    "on_hold": "On hold",
    "settled": "Settled",
    "settled_at": "Settled on",
    "settlement_id": "Settlement ID",
    "settlement_utr": "Payout UTR",
    "order_receipt": "Your order ID",
    "method": "Method",
}

CSS = """
:root{--ink:#15181E;--muted:#5F6672;--faint:#8B919C;--line:#E3E6EA;--surface:#F6F7F8;--green:#0D5C42;
  --green-soft:#EAF4EF;--red:#B42318;--red-soft:#FEF1EF;--amber:#B54708;--amber-soft:#FEF5E8;--slate:#475467;
  --slate-soft:#F2F4F7}
[data-testid="stMainBlockContainer"]{padding-top:2rem !important;padding-bottom:3rem !important;max-width:780px}
[data-testid="stHeader"]{background:transparent}
.rc-nav{display:flex;align-items:center;justify-content:space-between;padding:4px 0 44px}
.rc-brand{display:flex;align-items:center;gap:10px;font-weight:600;font-size:16px;color:var(--ink)}
.rc-nav a{color:var(--muted) !important;text-decoration:none;font-size:14px;margin-left:22px}
.rc-nav a:hover{color:var(--ink) !important}
.rc-h1{font-size:clamp(34px,6vw,46px);line-height:1.08;font-weight:600;letter-spacing:-.025em;color:var(--ink);
  margin:0 0 22px;max-width:15em}
.rc-lede{font-size:17px !important;line-height:1.65 !important;color:#2B3038;max-width:34em;margin:0 0 14px !important}
.rc-fine{font-size:13.5px !important;line-height:1.6 !important;color:var(--faint);margin:6px 0 !important}
.rc-h2{font-size:21px;font-weight:600;letter-spacing:-.01em;color:var(--ink);margin:52px 0 4px}
.rc-sub{font-size:14.5px !important;color:var(--muted);margin:0 0 16px !important;line-height:1.55 !important}
.rc-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:8px 0 22px}
@media (max-width:640px){.rc-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.rc-stat{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:#fff}
.rc-stat .k{font-size:13px;color:var(--muted)}
.rc-stat .v{font-size:21px;font-weight:600;letter-spacing:-.015em;margin-top:4px;color:var(--ink);
  font-variant-numeric:tabular-nums;white-space:nowrap}
@media (max-width:640px){.rc-stat .v{font-size:19px}}
.rc-stat.alert{background:var(--red-soft);border-color:#F6D3CE}
.rc-stat.alert .v{color:var(--red)}
.rc-summary{font-size:16.5px !important;line-height:1.7 !important;color:var(--ink);max-width:36em;margin:0 0 8px !important}
.rc-group{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;color:var(--ink);margin:30px 0 10px}
.rc-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.rc-dot.high{background:var(--red)}.rc-dot.medium{background:var(--amber)}.rc-dot.low{background:var(--slate)}
.rc-count{font-size:12px;font-weight:500;color:var(--muted);background:var(--surface);border:1px solid var(--line);
  border-radius:99px;padding:1px 8px}
.rc-card{border:1px solid var(--line);border-radius:12px;background:#fff;margin:0 0 10px;overflow:hidden}
.rc-card .head{display:flex;justify-content:space-between;align-items:baseline;gap:16px;padding:14px 16px 6px}
.rc-card .t{font-weight:600;font-size:15.5px;color:var(--ink)}
.rc-card .n{font-weight:400;font-size:13px;color:var(--muted);margin-left:6px;white-space:nowrap}
.rc-amt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:14px;font-weight:500;white-space:nowrap;color:var(--ink)}
.rc-card .d{padding:0 16px 12px;font-size:14.5px;line-height:1.6;color:#3A404A;overflow-wrap:anywhere}
.rc-rows{list-style:none;margin:2px 0 6px !important;padding:0 16px !important}
.rc-rows li{margin:0 !important}
.rc-rows li{display:flex;justify-content:space-between;gap:18px;padding:9px 0;border-top:1px solid var(--line);
  font-size:14.5px;line-height:1.55;color:#3A404A;overflow-wrap:anywhere}
.rc-rows li:first-child{border-top:none}
.rc-rows .rc-amt{font-size:13px;font-weight:400;color:var(--muted)}
.rc-next{background:var(--surface);border-top:1px solid var(--line);padding:10px 16px;font-size:13.5px;line-height:1.55;
  color:#3A404A}
.rc-next b{font-weight:600;color:var(--ink)}
.rc-alert{border:1px solid #F6D3CE;background:var(--red-soft);border-radius:12px;padding:16px 18px;margin:8px 0 14px}
.rc-alert .t{font-weight:600;font-size:16px;color:var(--red);margin-bottom:6px}
.rc-alert p{font-size:14.5px !important;line-height:1.65 !important;margin:0 0 8px !important;color:#3A404A}
.rc-file{display:grid;grid-template-columns:22px 1fr;gap:2px 10px;padding:12px 0;border-top:1px solid var(--line)}
.rc-file:first-of-type{border-top:none}
.rc-file .t{font-weight:600;font-size:15px}
.rc-file p{grid-column:2;font-size:14px !important;line-height:1.6 !important;margin:2px 0 !important;color:#3A404A}
.rc-file details{grid-column:2;margin-top:4px;font-size:13.5px;color:var(--muted)}
.rc-file summary{cursor:pointer;font-size:13px;color:var(--green)}
.rc-map{border-collapse:collapse;margin:8px 0 2px;font-size:13.5px}
.rc-map td{padding:3px 18px 3px 0;color:#3A404A}
.rc-map td:first-child{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12.5px;color:var(--ink)}
.rc-tick{width:18px;height:18px;border-radius:50%;background:var(--green-soft);display:flex;align-items:center;
  justify-content:center;margin-top:2px}
.rc-how{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:6px 0 8px}
@media (max-width:640px){.rc-how{grid-template-columns:1fr}}
.rc-how > div{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fff}
.rc-how .t{font-weight:600;font-size:15px;margin-bottom:6px;color:var(--ink)}
.rc-how p{font-size:14px !important;line-height:1.6 !important;margin:0 !important;color:#3A404A}
.rc-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;border-top:1px solid var(--line);
  margin-top:56px;padding:18px 0 6px;font-size:13.5px;color:var(--faint)}
.rc-foot a{color:var(--muted) !important;text-decoration:none;margin-left:18px}
.rc-foot a:hover{color:var(--ink) !important}
"""


def mark_svg(size: int = 26) -> str:
    """The logo: two equal bars on deep green. Both sides match."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 32 32" aria-hidden="true">'
        f'<rect width="32" height="32" rx="7.5" fill="{GREEN}"/>'
        '<rect x="7.4" y="10.2" width="17.2" height="4.3" rx="2.15" fill="#fff"/>'
        '<rect x="7.4" y="17.5" width="17.2" height="4.3" rx="2.15" fill="#fff"/></svg>'
    )


TICK = (
    '<span class="rc-tick"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">'
    f'<path d="M2 5.2 4.1 7.3 8 2.9" fill="none" stroke="{GREEN}" stroke-width="1.6" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg></span>'
)


def heading(title: str, sub: str = "") -> str:
    anchor = "-".join(title.lower().split())
    return f'<div class="rc-h2" id="{escape(anchor)}">{escape(title)}</div>' + (
        f'<p class="rc-sub">{escape(sub)}</p>' if sub else ""
    )


def tiles_html(stats: dict) -> str:
    def stat(label, value, alert=False):
        return f'<div class="rc-stat{" alert" if alert else ""}"><div class="k">{label}</div><div class="v">{value}</div></div>'

    matched = (
        f"{stats['settlements_matched']} of {stats['settlements_in_period']}" if stats["settlements_in_period"] else "–"
    )
    return (
        '<div class="rc-stats">'
        + stat("Needs a look now", f"₹{inr(stats['at_risk_high'])}", alert=stats["at_risk_high"] > 0)
        + stat("Payouts matched", matched)
        + stat("Reached your bank", f"₹{inr(stats['received_payouts'])}")
        + stat("Fees and GST", f"₹{inr(stats['fees'] + stats['gst'])}")
        + "</div>"
    )


def issues_html(exceptions) -> str:
    """Issues grouped by priority, then by kind: one card per kind, one next step per card."""
    if not exceptions:
        return '<p class="rc-summary">Nothing to fix.</p>'
    out = []
    for severity in ("high", "medium", "low"):
        group = [e for e in exceptions if e.severity == severity]
        if not group:
            continue
        out.append(
            f'<div class="rc-group"><span class="rc-dot {severity}"></span>{SEVERITY_LABEL[severity]}'
            f'<span class="rc-count">{len(group)}</span></div>'
        )
        kinds: dict[str, list] = {}
        for e in group:
            kinds.setdefault(e.type, []).append(e)
        for cases in sorted(kinds.values(), key=lambda c: -sum(e.amount_at_risk for e in c)):
            first, total = cases[0], sum(e.amount_at_risk for e in cases)
            count = f'<span class="n">{len(cases)} cases</span>' if len(cases) > 1 else ""
            if len(cases) == 1:
                body = f'<div class="d">{escape(first.detail)}</div>'
            else:
                items = "".join(
                    f'<li><span>{escape(e.detail)}</span><span class="rc-amt">₹{inr(e.amount_at_risk)}</span></li>'
                    for e in cases
                )
                body = f'<ul class="rc-rows">{items}</ul>'
            out.append(
                f'<div class="rc-card"><div class="head"><div class="t">{escape(first.title)}{count}</div>'
                f'<div class="rc-amt">₹{inr(total)}</div></div>{body}'
                f'<div class="rc-next"><b>Next step:</b> {escape(first.action)}</div></div>'
            )
    return "".join(out)


def file_story_html(label: str, loaded) -> str:
    chosen = loaded.chosen
    story = f"Found the column names on row {loaded.header_row + 1} and read {len(loaded.df)} rows."
    how = "Columns were matched by name" if chosen.source == "rules" else "The AI step worked out the columns"
    balance = chosen.checks.get("balance_continuity")
    if balance == 1.0:
        how += ", and the running balance adds up on every row, so they're read the right way round."
    elif balance is not None:
        how += f", and the running balance adds up on {balance:.0%} of rows."
    else:
        how += "."
    lines = [f"{story} {how}"] + [n[0].upper() + n[1:] + "." for n in chosen.notes]
    rows = "".join(
        f"<tr><td>{escape(column)}</td><td>{FIELD_LABELS.get(field, field)}</td></tr>"
        for field, column in chosen.mapping.items()
    )
    return (
        f'<div class="rc-file">{TICK}<div class="t">{escape(label)}</div>'
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + f'<details><summary>Show column mapping</summary><table class="rc-map">{rows}</table></details></div>'
    )

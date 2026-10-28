"""The look shared by the web app and the downloadable report: warm paper, ink, one red.

Plain HTML strings, so the same pieces render in Streamlit and in a standalone file.
"""

from __future__ import annotations

from html import escape

from .parse import inr

PAPER, INK, RED, GREY = "#F5F2EE", "#1A1A18", "#C0392B", "#8A8680"

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
[data-testid="stMainBlockContainer"]{padding-top:2.4rem !important;padding-bottom:3rem !important}
[data-testid="stHeader"]{background:transparent}
.rc-top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px 18px;
  font-family:"DM Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:#8A8680;padding:2px 0 34px}
.rc-top a{color:#8A8680;text-decoration:none;margin-left:20px}
.rc-top a:hover{color:#C0392B}
.rc-brand{color:#C0392B}
.rc-h1{font-family:"Instrument Serif",Georgia,serif;font-style:italic;font-weight:400;color:#1A1A18;
  font-size:clamp(42px,8vw,64px);line-height:1;letter-spacing:-.02em;margin:0 0 22px}
.rc-lede{font-size:17px !important;line-height:1.7 !important;max-width:35em;color:#1A1A18;margin:0 0 14px !important}
.rc-fine{font-size:14px !important;line-height:1.6 !important;color:#8A8680;margin:6px 0 !important}
.rc-sec{display:flex;align-items:baseline;gap:14px;border-top:1px solid rgba(26,26,24,.12);
  padding-top:22px;margin:46px 0 14px}
.rc-num{font-family:"DM Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.16em;color:#C0392B}
.rc-title{font-family:"Instrument Serif",Georgia,serif;font-style:italic;font-size:32px;line-height:1.1;color:#1A1A18}
.rc-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:rgba(26,26,24,.12);
  border:1px solid rgba(26,26,24,.12);border-radius:8px;overflow:hidden;margin:6px 0 22px}
@media (max-width:640px){.rc-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}
.rc-tile{background:#F5F2EE;padding:14px 16px}
.rc-k{font-family:"DM Mono",ui-monospace,monospace;font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:#8A8680}
.rc-v{font-family:"Instrument Serif",Georgia,serif;font-size:28px;line-height:1.15;margin-top:6px;color:#1A1A18;
  font-variant-numeric:tabular-nums}
.rc-v.red{color:#C0392B}
.rc-summary{font-size:16.5px !important;line-height:1.7 !important;max-width:36em;margin:0 0 6px !important;color:#1A1A18}
.rc-group{font-family:"DM Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  margin:30px 0 2px;color:#8A8680}
.rc-group.high{color:#C0392B}
.rc-group.medium{color:#A0522D}
.rc-issue{display:grid;grid-template-columns:1fr auto;gap:3px 18px;border-top:1px solid rgba(26,26,24,.1);padding:14px 0}
.rc-issue .t{font-weight:500;color:#1A1A18}
.rc-issue .amt{font-family:"DM Mono",ui-monospace,monospace;font-size:14px;text-align:right;white-space:nowrap;color:#1A1A18}
.rc-issue .d{grid-column:1/-1;font-size:14.5px;line-height:1.6;color:#3B3A37;overflow-wrap:anywhere}
.rc-issue .n{grid-column:1/-1;font-size:13.5px;line-height:1.55;color:#8A8680}
.rc-issue .x{font-family:"DM Mono",ui-monospace,monospace;font-size:12px;font-weight:400;color:#8A8680;margin-left:4px}
.rc-cases{grid-column:1/-1;list-style:none;margin:4px 0 6px;padding:0}
.rc-cases li{display:grid;grid-template-columns:1fr auto;gap:16px;font-size:14.5px;line-height:1.6;color:#3B3A37;
  padding:3px 0 3px 14px;border-left:1px solid rgba(26,26,24,.16);margin:6px 0;overflow-wrap:anywhere}
.rc-cases .amt{font-size:12.5px;color:#8A8680}
.rc-alert{border-left:2px solid #C0392B;padding:4px 0 4px 16px;margin:10px 0 12px}
.rc-alert .t{font-family:"Instrument Serif",Georgia,serif;font-style:italic;font-size:24px;line-height:1.2;margin-bottom:6px}
.rc-alert p{font-size:15px !important;line-height:1.65 !important;margin:0 0 8px !important;max-width:36em}
.rc-file{border-top:1px solid rgba(26,26,24,.1);padding:14px 0}
.rc-file .t{font-weight:500}
.rc-file p{font-size:14.5px !important;line-height:1.6 !important;margin:4px 0 !important;color:#3B3A37;max-width:40em}
.rc-file details{margin-top:6px;font-size:13.5px;color:#8A8680}
.rc-file summary{cursor:pointer;font-family:"DM Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase}
.rc-map{border-collapse:collapse;margin:8px 0 2px;font-size:13.5px}
.rc-map td{padding:3px 18px 3px 0;color:#3B3A37}
.rc-map td:first-child{font-family:"DM Mono",ui-monospace,monospace;font-size:12.5px;color:#1A1A18}
.rc-how{display:grid;grid-template-columns:2.2em 1fr;gap:4px 10px;border-top:1px solid rgba(26,26,24,.1);padding:14px 0}
.rc-how .i{font-family:"DM Mono",ui-monospace,monospace;font-size:11px;color:#C0392B;padding-top:5px}
.rc-how .t{font-weight:500}
.rc-how p{grid-column:2;font-size:14.5px !important;line-height:1.65 !important;margin:0 !important;color:#3B3A37}
.rc-ask{border-top:1px solid rgba(26,26,24,.12);margin:34px 0 4px;padding-top:18px;font-family:"DM Mono",ui-monospace,monospace;
  font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#8A8680}
.rc-foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;border-top:1px solid rgba(26,26,24,.12);
  margin-top:60px;padding:18px 0 8px;font-family:"DM Mono",ui-monospace,monospace;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:#8A8680}
.rc-foot a{color:#8A8680;text-decoration:none;margin-left:18px}
.rc-foot a:hover{color:#C0392B}
"""


def section(number: int, title: str) -> str:
    return f'<div class="rc-sec"><span class="rc-num">{number:02d}</span><span class="rc-title">{escape(title)}</span></div>'


def tiles_html(stats: dict) -> str:
    def tile(label, value, red=False):
        return f'<div class="rc-tile"><div class="rc-k">{label}</div><div class="rc-v{" red" if red else ""}">{value}</div></div>'

    matched = (
        f"{stats['settlements_matched']} of {stats['settlements_in_period']}" if stats["settlements_in_period"] else "–"
    )
    return (
        '<div class="rc-tiles">'
        + tile("Needs a look now", f"₹{inr(stats['at_risk_high'])}", red=stats["at_risk_high"] > 0)
        + tile("Payouts matched", matched)
        + tile("Reached your bank", f"₹{inr(stats['received_payouts'])}")
        + tile("Fees + GST", f"₹{inr(stats['fees'] + stats['gst'])}")
        + "</div>"
    )


def issues_html(exceptions) -> str:
    """Issues grouped by priority, then by kind: one heading and one next step per kind, cases underneath."""
    if not exceptions:
        return '<p class="rc-summary">Nothing to fix.</p>'
    out = []
    for severity in ("high", "medium", "low"):
        group = [e for e in exceptions if e.severity == severity]
        if not group:
            continue
        out.append(f'<div class="rc-group {severity}">{SEVERITY_LABEL[severity]} · {len(group)}</div>')
        kinds: dict[str, list] = {}
        for e in group:
            kinds.setdefault(e.type, []).append(e)
        for cases in sorted(kinds.values(), key=lambda c: -sum(e.amount_at_risk for e in c)):
            first, total = cases[0], sum(e.amount_at_risk for e in cases)
            count = f' <span class="x">× {len(cases)}</span>' if len(cases) > 1 else ""
            if len(cases) == 1:
                body = f'<div class="d">{escape(first.detail)}</div>'
            else:
                items = "".join(
                    f'<li><span>{escape(e.detail)}</span><span class="amt">₹{inr(e.amount_at_risk)}</span></li>'
                    for e in cases
                )
                body = f'<ul class="rc-cases">{items}</ul>'
            out.append(
                f'<div class="rc-issue"><div class="t">{escape(first.title)}{count}</div>'
                f'<div class="amt">₹{inr(total)}</div>{body}<div class="n">What to do: {escape(first.action)}</div></div>'
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
        f'<div class="rc-file"><div class="t">{escape(label)}</div>'
        + "".join(f"<p>{escape(line)}</p>" for line in lines)
        + f'<details><summary>Column mapping</summary><table class="rc-map">{rows}</table></details></div>'
    )

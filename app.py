"""Recon Agent, the web app.   streamlit run app.py"""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path

import streamlit as st

from recon.engine import Config, reconcile
from recon.ingest import MappingError, load_bank, load_orders, load_report
from recon.llm import get_client
from recon.look import CSS, file_story_html, heading, issues_html, mark_svg, tiles_html
from recon.report import llm_summary, template_summary, to_html

ROOT = Path(__file__).parent
SAMPLES = ROOT / "data" / "samples"
REPO = "https://github.com/codeMaster60/recon-agent"
LINKEDIN = "https://www.linkedin.com/in/asaijayanth"
SAMPLE_BANKS = {
    "Bank A, CSV with separate withdrawal and deposit columns": "bank_format_a.csv",
    "Bank B, Excel download": "bank_format_b.xlsx",
    "Bank C, one amount column marked Cr or Dr": "bank_format_c.csv",
    "Bank D, column names in Hindi (needs the AI step)": "bank_format_d.csv",
}

st.set_page_config(page_title="Recon Agent", page_icon=str(ROOT / "assets" / "favicon.png"), layout="centered")

# On Streamlit Cloud the key lives in the app's Secrets.
try:
    if "GROQ_API_KEY" in st.secrets and not os.getenv("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:  # no secrets file when running locally
    pass

client = get_client()


def show(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def tail() -> None:
    """How it works and the footer. Shown on every page, including before any file is added."""
    show(heading("How it works", "Three steps. Only the first one uses AI, and only when it has to."))
    show(
        '<div class="rc-how">'
        '<div><div class="t">Reads any bank\'s format</div><p>Narration, Particulars, Remarks. Every bank names '
        "things differently. Column names get matched first. When that fails, an LLM reads the headers and a few "
        "rows. Either way, the running balance has to add up on every row before a file is accepted.</p></div>"
        '<div><div class="t">Matches every payout</div><p>UTR first. If the bank cut the narration short, exact '
        "amount within a few days. If a payout came in short, the closest amount - so you see one short payout, "
        "not a missing one and a mystery credit.</p></div>"
        '<div><div class="t">Checks the small stuff</div><p>Fees against your rate card. GST against the fee. '
        "Payments stuck past T+2. Customers charged twice. Cancelled orders nobody refunded.</p></div>"
        "</div>"
        '<p class="rc-fine">The AI never does the maths. If the summary it writes has a number that isn\'t in your '
        "data, the summary gets thrown away.</p>"
    )
    ai = f"AI step on ({escape(client.model)})" if client else "AI step off in this demo"
    show(
        f'<div class="rc-foot"><span>Built by Sai Jayanth. {ai}.</span><span>'
        f'<a href="{REPO}" target="_blank">GitHub</a><a href="{LINKEDIN}" target="_blank">LinkedIn</a></span></div>'
    )


def read_error(label: str, exc: MappingError) -> None:
    if exc.reason == "empty":
        body = "It has column names but no rows under them. Check the date range you picked when you downloaded it."
    elif exc.reason == "no_header":
        body = "I couldn't find a row of column names near the top. Is this the right file?"
    else:
        found = escape(", ".join(exc.headers[:8]) or "none")
        body = f"Its columns are {found}. From the names alone, I can't tell which is the date, the amount and the narration."
        if client is None:
            body += (
                "</p><p>This is exactly what the AI step is for. It reads the headers and a few rows, works out "
                "the mapping, and the running balance checks it. It's off in this public demo because it would run "
                "on my API key. Clone the repo, add a free Groq key, and files like this go straight through."
            )
        else:
            body += " The AI step couldn't make sense of it either, so it was rejected rather than guessed."
    show(f'<div class="rc-alert"><div class="t">Couldn\'t read the {escape(label)}</div><p>{body}</p></div>')
    with st.expander("Technical details"):
        st.code(str(exc), language=None)


def load(label: str, loader, file):
    if not file:
        return None
    try:
        return loader(file, client=client, mode="auto")
    except MappingError as exc:
        read_error(label, exc)
        tail()
        st.stop()


# ------------------------------------------------------------------------------------------- page

show(f"<style>{CSS}</style>")
show(
    f'<div class="rc-nav"><span class="rc-brand">{mark_svg()}Recon Agent</span><span>'
    '<a href="#how-it-works">How it works</a></span></div>'  # Streamlit Cloud adds its own GitHub icon up top
)
show(
    '<div class="rc-h1">Razorpay says it paid you. Did all of it reach your bank?</div>'
    '<p class="rc-lede">Razorpay settles a day or two after each sale. Fee and GST taken out, refunds netted '
    "off, one lump per day.</p>"
    '<p class="rc-lede">Most small businesses never check if every lump showed up. The ones that do, do it in '
    "Excel - two files side by side, row by row, for an afternoon.</p>"
    '<p class="rc-lede">Drop the same files here. It takes a few seconds.</p>'
)

show(
    heading(
        "Your files",
        "Settlement report and bank statement for the same dates. Orders are optional, but they catch more.",
    )
)
with st.container(border=True):
    report_file = st.file_uploader(
        "Razorpay settlement report",
        type=["csv", "xlsx"],
        help="Razorpay Dashboard, Reports, Settlements. CSV or Excel.",
    )
    bank_file = st.file_uploader(
        "Bank statement", type=["csv", "xlsx"], help="Any bank. Download it from net banking as CSV or Excel."
    )
    orders_file = st.file_uploader(
        "Your orders (optional)",
        type=["csv", "xlsx"],
        help="From your own system. Lets it catch double charges and cancelled orders nobody refunded.",
    )
    show('<p class="rc-fine">Files stay in memory and are gone when you close the tab. Nothing is stored.</p>')

if st.button("No files handy? Try a sample month"):
    st.session_state["sample"] = True
if st.session_state.get("sample") and not report_file:
    choice = st.radio("Pick a bank format for the sample", list(SAMPLE_BANKS))
    show(
        '<p class="rc-fine">A made-up home services business, September 2026. Around 320 bookings, with 22 '
        "problems planted for the checker to find.</p>"
    )
    report_file = SAMPLES / "settlement_report.csv"
    bank_file = SAMPLES / SAMPLE_BANKS[choice]
    orders_file = SAMPLES / "orders.csv"

cfg = Config()
with st.expander("Your fee rates and settlement cycle"):
    show('<p class="rc-fine">These defaults are placeholders. Put in what your Razorpay plan actually charges.</p>')
    left, right = st.columns(2)
    methods = [("upi", "UPI"), ("card", "Cards"), ("netbanking", "Net banking"), ("wallet", "Wallets")]
    for i, (method, name) in enumerate(methods):
        column = left if i % 2 == 0 else right
        cfg.rate_card[method] = column.number_input(
            f"{name} fee (%)", 0.0, 5.0, cfg.rate_card[method], 0.05, key=f"rate_{method}"
        )
    cfg.settlement_days = st.number_input("Settlement cycle (T + days)", 0, 10, cfg.settlement_days)

show(heading("What came up"))
if not report_file:
    show('<p class="rc-fine">Results show up here once you add a settlement report, or try the sample month.</p>')
    tail()
    st.stop()

with st.spinner("Reading your files..."):
    report = load("settlement report", load_report, report_file)
    bank = load("bank statement", load_bank, bank_file)
    orders = load("orders file", load_orders, orders_file)

result = reconcile(report.df, bank.df if bank else None, orders.df if orders else None, cfg)
summary, used_llm = llm_summary(result, client) if client else (template_summary(result), False)

show(tiles_html(result.stats))
show(f'<p class="rc-summary">{escape(summary)}</p>')
if used_llm:
    show('<p class="rc-fine">Summary written by the AI step. Every number in it was checked against your data.</p>')
show(issues_html(result.exceptions))
for note in result.notes:
    show(f'<p class="rc-fine">{escape(note)}</p>')

frame = result.exceptions_frame()
d1, d2, _ = st.columns([0.9, 1.1, 1.6], gap="small")
d1.download_button("Download the report", to_html(result, summary), "payout-check.html", "text/html")
d2.download_button(
    "Download issues as CSV", frame.to_csv(index=False), "payout-issues.csv", "text/csv", disabled=frame.empty
)

show(heading("How your files were read", "Worth a glance if a result looks off."))
for label, loaded in (("Settlement report", report), ("Bank statement", bank), ("Orders", orders)):
    if loaded:
        show(file_story_html(label, loaded))

show(heading("Before you go"))
vote = st.radio("Did this catch something you didn't know about?", ["Yes", "Not really"], index=None, horizontal=True)
comment = st.text_input("What would make you use this every month?")
if vote or comment:
    # Streamlit Cloud logs are visible to the app owner; swap for a sheet or webhook once there are real users.
    print("FEEDBACK", json.dumps({"vote": vote, "comment": comment, "issues": len(result.exceptions)}))
    show('<p class="rc-fine">Thanks, noted.</p>')

tail()

"""Streamlit app:  streamlit run app.py

Upload a Razorpay settlement report, a bank statement (any layout) and optionally your orders
export. Or click "Try with sample data" to see it work on a month of synthetic data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from recon.engine import Config, reconcile
from recon.ingest import MappingError, load_bank, load_orders, load_report
from recon.llm import get_client
from recon.parse import inr
from recon.report import SEVERITY_LABEL, llm_summary, template_summary, to_html

SAMPLES = Path(__file__).parent / "data" / "samples"

st.set_page_config(page_title="Recon Agent", page_icon="🧾", layout="wide")

# Streamlit Cloud: put GROQ_API_KEY in the app's Secrets.
try:
    if "GROQ_API_KEY" in st.secrets and not os.getenv("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = st.secrets["GROQ_API_KEY"]
except Exception:  # no secrets file locally
    pass

st.title("Recon Agent")
st.caption("Did every Razorpay payout reach your bank, in full, at the fees you agreed? "
           "Upload three exports and find out in seconds. Files are processed in memory and never stored.")

with st.sidebar:
    st.subheader("Settings")
    client = get_client()
    st.write("AI column mapping: " + ("**on** (" + client.model + ")" if client else "**off** - rules only. Set GROQ_API_KEY to map unfamiliar bank layouts."))
    cfg = Config()
    st.markdown("**Your fee rate card (% before GST)**")
    for method in ("upi", "card", "netbanking", "wallet"):
        cfg.rate_card[method] = st.number_input(method, 0.0, 5.0, cfg.rate_card[method], 0.05, key=f"rate_{method}")
    cfg.settlement_days = st.number_input("Settlement cycle (T+days)", 0, 10, cfg.settlement_days)

c1, c2, c3 = st.columns(3)
report_file = c1.file_uploader("1. Razorpay settlement report", type=["csv", "xlsx"])
bank_file = c2.file_uploader("2. Bank statement (any bank)", type=["csv", "xlsx"])
orders_file = c3.file_uploader("3. Your orders export (optional)", type=["csv", "xlsx"])

use_sample = st.button("Try with sample data")
if use_sample:
    st.session_state["sample"] = True
if st.session_state.get("sample") and not report_file:
    layout = st.radio("Sample bank layout", ["a (CSV, Withdrawal/Deposit)", "b (Excel, Debit/Credit)",
                                             "c (single Amount + Cr/Dr)", "d (Hindi headers - needs AI)"], horizontal=True)
    ext = {"a": "csv", "b": "xlsx", "c": "csv", "d": "csv"}[layout[0]]
    report_file = SAMPLES / "settlement_report.csv"
    bank_file = SAMPLES / f"bank_format_{layout[0]}.{ext}"
    orders_file = SAMPLES / "orders.csv"

if not report_file:
    st.info("Start with the settlement report (Razorpay Dashboard → Reports → Settlement recon). "
            "Add the bank statement for the same dates to check payouts.")
    st.stop()

mode = "auto"
try:
    with st.spinner("Reading files and mapping columns..."):
        report = load_report(report_file, client=client, mode=mode)
        bank = load_bank(bank_file, client=client, mode=mode) if bank_file else None
        orders = load_orders(orders_file, client=client, mode=mode) if orders_file else None
except MappingError as exc:
    st.error(str(exc))
    st.stop()

result = reconcile(report.df, bank.df if bank else None, orders.df if orders else None, cfg)
summary, used_llm = llm_summary(result, client) if client else (template_summary(result), False)
s = result.stats

k1, k2, k3, k4 = st.columns(4)
k1.metric("Needs action now", f"Rs {inr(s['at_risk_high'])}")
k2.metric("Payouts matched", f"{s['settlements_matched']} / {s['settlements_in_period']}")
k3.metric("Expected payouts", f"Rs {inr(s['expected_payouts'])}")
k4.metric("Received in bank", f"Rs {inr(s['received_payouts'])}")

st.subheader("Summary" + (" (AI-written, numbers checked)" if used_llm else ""))
st.text(summary)

st.subheader(f"Issues ({len(result.exceptions)})")
frame = result.exceptions_frame()
if not frame.empty:
    frame.insert(0, "priority", frame.pop("severity").map(SEVERITY_LABEL))
    st.dataframe(frame, width="stretch", hide_index=True,
                 column_config={"amount_at_risk": st.column_config.NumberColumn("amount (Rs)", format="%.2f")})
for note in result.notes:
    st.caption(note)

with st.expander("How each file was read"):
    for label, loaded in (("Settlement report", report), ("Bank statement", bank), ("Orders", orders)):
        if loaded:
            st.markdown(f"**{label}** — header on row {loaded.header_row + 1}, mapped by **{loaded.chosen.source}**, "
                        f"validation score {loaded.chosen.score:.2f} {loaded.chosen.checks}")
            st.json(loaded.chosen.mapping)
            for n in loaded.chosen.notes:
                st.caption(n)

d1, d2 = st.columns(2)
d1.download_button("Download report (HTML)", to_html(result, summary), "recon_report.html", "text/html")
d2.download_button("Download issues (CSV)", frame.to_csv(index=False) if not frame.empty else "", "exceptions.csv", "text/csv")

st.divider()
st.caption("Was this useful? It helps me decide what to build next.")
f1, f2 = st.columns([1, 3])
vote = f1.radio("Found something you didn't know?", ["Yes", "No"], index=None, horizontal=True)
comment = f2.text_input("What would make this worth using every month?")
if vote or comment:
    # Streamlit Cloud logs are visible to the app owner; swap for a sheet/webhook when you have users.
    print("FEEDBACK", json.dumps({"vote": vote, "comment": comment, "exceptions": len(result.exceptions)}))
    st.success("Thanks - noted.")

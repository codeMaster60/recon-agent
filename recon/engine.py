"""Deterministic reconciliation: settlement report <-> bank statement <-> merchant orders.

Three questions a small merchant actually asks:
  1. Did every settlement Razorpay says it paid actually land in my bank, in full?
  2. Was I charged the fees and GST I signed up for, and has every payment been settled?
  3. Does what my own system thinks was paid match what was really collected?
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import pandas as pd

from .parse import extract_utr_candidates, squash

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Config:
    # Fee % per method, before GST. Defaults are a placeholder: edit to match your Razorpay plan.
    rate_card: dict[str, float] = field(
        default_factory=lambda: {
            "upi": 2.0,
            "card": 2.0,
            "netbanking": 2.0,
            "wallet": 2.0,
            "emi": 3.0,
            "international": 3.0,
        }
    )
    default_rate: float = 2.0
    fee_tolerance_pct: float = 0.05  # allowed excess, in percentage points
    gst_rate: float = 0.18
    settlement_days: int = 2  # T+2 default settlement cycle
    grace_days: int = 2  # extra slack before calling a payment "unsettled"
    date_window_days: int = 2  # settlements this far before the statement start are still checked
    max_lag_days: int = 4  # bank may post a payout up to this many days after settlement
    max_pair_gap: float = 0.25  # pass-3 pairing: amounts may differ by up to 25%
    payout_keywords: tuple[str, ...] = ("RAZORPAY",)
    money_tolerance: float = 0.01


@dataclass
class Exception_:
    type: str
    severity: str
    key: str
    amount_at_risk: float
    title: str
    detail: str
    action: str
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Result:
    exceptions: list[Exception_]
    settlements: pd.DataFrame
    stats: dict
    notes: list[str]

    def exceptions_frame(self) -> pd.DataFrame:
        cols = ["severity", "type", "key", "amount_at_risk", "title", "detail", "action"]
        if not self.exceptions:
            return pd.DataFrame(columns=cols)
        return pd.DataFrame([e.to_dict() for e in self.exceptions])[cols]


TITLES = {
    "missing_payout": "Settlement never reached the bank",
    "short_credit": "Bank received less than the settlement amount",
    "excess_credit": "Bank received more than the settlement amount",
    "unknown_credit": "Razorpay credit in bank with no matching settlement",
    "fee_anomaly": "Fee higher than your rate card",
    "gst_mismatch": "GST on fee is not 18%",
    "unsettled_payment": "Captured payment still not settled",
    "duplicate_payment": "Customer charged more than once",
    "order_without_payment": "Order marked paid, but no payment exists",
    "paid_on_cancelled_order": "Cancelled order still holds the customer's money",
    "amount_mismatch_order": "Order value differs from amount collected",
    "payment_without_order": "Payment with no order in your system",
}


def _days(d1: date, d2: date) -> int:
    return abs((d1 - d2).days)


def match_settlements(report: pd.DataFrame, bank: pd.DataFrame, cfg: Config):
    """Return (settlements frame with match info, list of exceptions, set of used bank rows)."""
    settled = report[report["settled"] & (report["settlement_id"] != "")]
    groups = settled.groupby("settlement_id", sort=False)
    settlements = (
        pd.DataFrame(
            {
                "settlement_id": list(groups.groups.keys()),
                "utr": groups["settlement_utr"].first().values,
                "settled_at": groups["settled_at"].first().values,
                "net": (groups["credit"].sum() - groups["debit"].sum()).round(2).values,
                "entities": groups.size().values,
            }
        )
        .sort_values("settled_at", kind="stable")
        .reset_index(drop=True)
    )
    # A settlement whose refunds exceed its payments pays nothing; Razorpay carries the
    # negative balance into the next payout, which then arrives smaller.
    expected, carried, carry = [], [], 0.0
    for net in settlements["net"]:
        value = round(net + carry, 2)
        carried.append(round(carry, 2))
        expected.append(max(value, 0.0))
        carry = min(value, 0.0)
    settlements["carried_in"] = carried
    settlements["expected"] = expected
    settlements["status"] = ""
    settlements["bank_amount"] = None
    settlements["bank_date"] = None
    settlements["match_method"] = ""

    exceptions: list[Exception_] = []
    if bank.empty:
        settlements["status"] = "no_bank_statement"
        return settlements, exceptions, set()

    start, end = bank["date"].min(), bank["date"].max()
    credits = bank[bank["amount"] > 0]
    haystack = {i: squash(f"{r.description} {r.ref}") for i, r in credits.iterrows()}
    is_payout = {i: any(k in h for k in cfg.payout_keywords) for i, h in haystack.items()}
    used: set[int] = set()

    def record(idx, row_i, method):
        bank_row = credits.loc[row_i]
        settlements.at[idx, "bank_amount"] = float(bank_row["amount"])
        settlements.at[idx, "bank_date"] = bank_row["date"]
        settlements.at[idx, "match_method"] = method
        used.add(row_i)

    # Pass 1: UTR printed in the narration or reference column.
    for idx, s in settlements.iterrows():
        if s["settled_at"] is None or s["settled_at"] > end:
            settlements.at[idx, "status"] = "after_statement"
            continue
        if s["settled_at"] < start - timedelta(days=cfg.date_window_days):
            settlements.at[idx, "status"] = "before_statement"
            continue
        if s["expected"] <= cfg.money_tolerance:
            # Refunds exceeded payments: nothing is paid out, the negative balance is carried forward.
            settlements.at[idx, "status"] = "no_payout_expected"
            continue
        utr = squash(s["utr"] or "")
        if len(utr) >= 8:
            hit = next((i for i, h in haystack.items() if i not in used and utr in h), None)
            if hit is not None:
                record(idx, hit, "utr")

    def in_lag(bank_date, settled_at) -> bool:
        # Banks post a payout on the settlement date or a few days later, rarely a day early.
        return -1 <= (bank_date - settled_at).days <= cfg.max_lag_days

    def open_payouts():
        return [i for i in credits.index if i not in used and is_payout[i]]

    # Pass 2: narration cut off before the UTR -> exact amount within the posting-lag window.
    for idx, s in settlements.iterrows():
        if s["status"] or s["match_method"]:
            continue
        candidates = [
            i
            for i in open_payouts()
            if abs(credits.at[i, "amount"] - s["expected"]) <= cfg.money_tolerance
            and in_lag(credits.at[i, "date"], s["settled_at"])
        ]
        if candidates:
            best = min(candidates, key=lambda i: _days(credits.at[i, "date"], s["settled_at"]))
            record(idx, best, "amount+date")

    # Pass 3: still unpaired on both sides -> pair the closest amount within the lag window, if
    # within max_pair_gap. A short credit with a truncated narration lands here instead of
    # showing up as one "missing" payout plus one "unknown" credit.
    pairs = []
    for idx, s in settlements.iterrows():
        if s["status"] or s["match_method"] or s["expected"] <= 0:
            continue
        for i in open_payouts():
            gap = abs(credits.at[i, "amount"] - s["expected"]) / s["expected"]
            if gap <= cfg.max_pair_gap and in_lag(credits.at[i, "date"], s["settled_at"]):
                pairs.append((gap, _days(credits.at[i, "date"], s["settled_at"]), idx, i))
    for _, _, idx, i in sorted(pairs):
        if not settlements.at[idx, "match_method"] and i not in used:
            record(idx, i, "nearest amount")

    for idx, s in settlements.iterrows():
        if s["status"]:
            continue
        if not s["match_method"]:
            settlements.at[idx, "status"] = "missing"
            near_end = (end - s["settled_at"]).days < cfg.max_lag_days
            exceptions.append(
                Exception_(
                    "missing_payout",
                    "medium" if near_end else "high",
                    s["settlement_id"],
                    float(s["expected"]),
                    TITLES["missing_payout"],
                    f"Settlement {s['settlement_id']} of Rs {s['expected']:,.2f} (UTR {s['utr'] or 'n/a'}, "
                    f"{s['settled_at']}) has no matching credit in the statement."
                    + (
                        " It was settled in the last days of the statement, so it may simply post in the next one."
                        if near_end
                        else ""
                    ),
                    "Raise a ticket with Razorpay support quoting the settlement id and UTR; ask your bank to trace the UTR.",
                    {
                        "utr": s["utr"],
                        "settled_at": str(s["settled_at"]),
                        "expected": float(s["expected"]),
                        "carried_in": float(s["carried_in"]),
                    },
                )
            )
            continue
        diff = round(float(s["bank_amount"]) - float(s["expected"]), 2)
        if abs(diff) <= cfg.money_tolerance:
            settlements.at[idx, "status"] = "matched"
        else:
            kind = "short_credit" if diff < 0 else "excess_credit"
            settlements.at[idx, "status"] = kind
            exceptions.append(
                Exception_(
                    kind,
                    "high" if diff < 0 else "low",
                    s["settlement_id"],
                    abs(diff),
                    TITLES[kind],
                    f"Settlement {s['settlement_id']} should be Rs {s['expected']:,.2f}; bank shows Rs "
                    f"{s['bank_amount']:,.2f} on {s['bank_date']} (difference Rs {diff:,.2f}).",
                    "Check for an adjustment or hold deducted outside the report; if none, dispute with Razorpay.",
                    {
                        "utr": s["utr"],
                        "expected": float(s["expected"]),
                        "carried_in": float(s["carried_in"]),
                        "bank_amount": float(s["bank_amount"]),
                        "matched_by": s["match_method"],
                    },
                )
            )

    for i, r in credits.iterrows():
        if i in used or not is_payout[i]:
            continue
        utrs = extract_utr_candidates(f"{r['description']} {r['ref']}")
        exceptions.append(
            Exception_(
                "unknown_credit",
                "low",
                utrs[0] if utrs else f"bank-row-{int(r['row'])}",
                float(r["amount"]),
                TITLES["unknown_credit"],
                f"Rs {r['amount']:,.2f} on {r['date']} ('{r['description'][:60]}') is not in the settlement report.",
                "Re-export the settlement report for a wider date range; it may belong to another account or period.",
                {"description": r["description"], "date": str(r["date"])},
            )
        )
    return settlements, exceptions, used


def check_payments(report: pd.DataFrame, cfg: Config, as_of: date) -> list[Exception_]:
    out: list[Exception_] = []
    payments = report[report["type"] == "payment"]
    for _, p in payments.iterrows():
        amount, fee, tax = float(p["amount"]), float(p["fee"]), float(p["tax"])
        expected_rate = cfg.rate_card.get(p["method"], cfg.default_rate)
        if amount > 0 and fee / amount * 100 > expected_rate + cfg.fee_tolerance_pct:
            excess = round((fee - amount * expected_rate / 100) * (1 + cfg.gst_rate), 2)
            out.append(
                Exception_(
                    "fee_anomaly",
                    "medium",
                    p["entity_id"],
                    excess,
                    TITLES["fee_anomaly"],
                    f"{p['entity_id']} ({p['method'] or 'unknown method'}): fee Rs {fee:.2f} on Rs {amount:,.2f} is "
                    f"{fee / amount * 100:.2f}%, vs {expected_rate:.2f}% on your rate card.",
                    "Check whether this was an international/corporate card; if not, ask Razorpay for a fee reversal.",
                    {
                        "fee": fee,
                        "amount": amount,
                        "rate_pct": round(fee / amount * 100, 3),
                        "expected_pct": expected_rate,
                    },
                )
            )
        if fee > 0 and abs(tax - fee * cfg.gst_rate) > 0.02:
            out.append(
                Exception_(
                    "gst_mismatch",
                    "low",
                    p["entity_id"],
                    round(abs(tax - fee * cfg.gst_rate), 2),
                    TITLES["gst_mismatch"],
                    f"{p['entity_id']}: GST Rs {tax:.2f} on fee Rs {fee:.2f} (expected Rs {fee * cfg.gst_rate:.2f}).",
                    "Flag to your accountant before filing; the GST invoice from Razorpay should match.",
                    {"fee": fee, "tax": tax},
                )
            )
        due = p["created_at"] and p["created_at"] <= as_of - timedelta(days=cfg.settlement_days + cfg.grace_days)
        if not p["settled"] and not p["on_hold"] and due:
            expected_credit = round(amount - fee - tax, 2)
            out.append(
                Exception_(
                    "unsettled_payment",
                    "high",
                    p["entity_id"],
                    expected_credit,
                    TITLES["unsettled_payment"],
                    f"{p['entity_id']} for Rs {amount:,.2f} was captured on {p['created_at']} and is not settled "
                    f"as of {as_of} (beyond T+{cfg.settlement_days}).",
                    "Check the payment in the Razorpay dashboard; if it is not on hold, ask support why it missed settlement.",
                    {"created_at": str(p["created_at"]), "amount": amount},
                )
            )
    return out


def check_orders(report: pd.DataFrame, orders: pd.DataFrame, cfg: Config) -> list[Exception_]:
    out: list[Exception_] = []
    payments = report[report["type"] == "payment"]
    refunds = report[report["type"] == "refund"]
    pays_by = payments.groupby("order_receipt")
    refunded = refunds.groupby("order_receipt")["amount"].sum().to_dict()
    known = set(orders["order_ref"])

    for _, o in orders.iterrows():
        ref, amount, status = o["order_ref"], float(o["amount"]), o["status"]
        pays = pays_by.get_group(ref) if ref in pays_by.groups else payments.iloc[0:0]
        collected = float(pays["amount"].sum())
        back = float(refunded.get(ref, 0.0))
        if status == "paid" and pays.empty:
            out.append(
                Exception_(
                    "order_without_payment",
                    "high",
                    ref,
                    amount,
                    TITLES["order_without_payment"],
                    f"Order {ref} (Rs {amount:,.2f}) is '{o['status_raw'] or 'paid'}' in your system but no Razorpay payment carries this receipt.",
                    "Check whether the customer paid by cash/UPI directly, or whether the order was marked paid by mistake.",
                    {"customer": o["customer"]},
                )
            )
        elif len(pays) > 1 and collected - back > amount + cfg.money_tolerance:
            extra = round(collected - back - amount, 2)
            out.append(
                Exception_(
                    "duplicate_payment",
                    "high",
                    ref,
                    extra,
                    TITLES["duplicate_payment"],
                    f"Order {ref} (Rs {amount:,.2f}) has {len(pays)} captured payments totalling Rs {collected:,.2f}: "
                    f"{', '.join(pays['entity_id'])}.",
                    "Refund the extra payment from the dashboard before the customer raises a chargeback.",
                    {"payments": list(pays["entity_id"]), "collected": collected},
                )
            )
        elif status == "cancelled" and collected - back > cfg.money_tolerance:
            owed = round(collected - back, 2)
            out.append(
                Exception_(
                    "paid_on_cancelled_order",
                    "high",
                    ref,
                    owed,
                    TITLES["paid_on_cancelled_order"],
                    f"Order {ref} is cancelled but Rs {owed:,.2f} collected via {', '.join(pays['entity_id'])} was never refunded.",
                    "Issue the refund (or reinstate the order) and tell the customer.",
                    {"payments": list(pays["entity_id"]), "refunded": back},
                )
            )
        elif status == "paid" and len(pays) == 1 and abs(collected - amount) > cfg.money_tolerance:
            out.append(
                Exception_(
                    "amount_mismatch_order",
                    "medium",
                    ref,
                    round(abs(collected - amount), 2),
                    TITLES["amount_mismatch_order"],
                    f"Order {ref} is Rs {amount:,.2f} in your system but Rs {collected:,.2f} was collected.",
                    "Fix the order total or collect/refund the difference.",
                    {"order_amount": amount, "collected": collected},
                )
            )

    for ref, group in pays_by:
        if ref and ref not in known:
            out.append(
                Exception_(
                    "payment_without_order",
                    "medium",
                    ref,
                    float(group["amount"].sum()),
                    TITLES["payment_without_order"],
                    f"Razorpay payment(s) {', '.join(group['entity_id'])} reference receipt {ref}, which is not in your orders export.",
                    "Check the orders export date range, or link the payment to the right order.",
                    {"payments": list(group["entity_id"])},
                )
            )
    return out


def reconcile(
    report: pd.DataFrame,
    bank: pd.DataFrame | None = None,
    orders: pd.DataFrame | None = None,
    cfg: Config | None = None,
    as_of: date | None = None,
) -> Result:
    cfg = cfg or Config()
    bank = (
        bank if bank is not None else pd.DataFrame(columns=["date", "description", "ref", "amount", "balance", "row"])
    )
    notes: list[str] = []
    if as_of is None:
        dates = [d for d in report["created_at"] if d]
        as_of = bank["date"].max() if not bank.empty else max(dates) if dates else date.today()

    settlements, exceptions, used = match_settlements(report, bank, cfg)
    exceptions += check_payments(report, cfg, as_of)
    if orders is not None and not orders.empty:
        exceptions += check_orders(report, orders, cfg)
    exceptions.sort(key=lambda e: (SEVERITY_ORDER[e.severity], -e.amount_at_risk))

    in_period = settlements[settlements["status"].isin(["matched", "short_credit", "excess_credit", "missing"])]
    after = int((settlements["status"] == "after_statement").sum())
    if after:
        notes.append(
            f"{after} settlement(s) dated after the statement ends were skipped; check them in next month's statement."
        )
    negative = int((settlements["status"] == "no_payout_expected").sum())
    if negative:
        notes.append(f"{negative} settlement(s) had refunds larger than payments, so no payout was expected for them.")
    weak = int((settlements["match_method"] == "amount+date").sum())
    if weak:
        notes.append(
            f"{weak} payout(s) matched on amount and date because the bank narration was cut off before the UTR."
        )

    payments = report[report["type"] == "payment"]
    by_type: dict[str, dict] = {}
    for e in exceptions:
        slot = by_type.setdefault(e.type, {"count": 0, "amount": 0.0})
        slot["count"] += 1
        slot["amount"] = round(slot["amount"] + e.amount_at_risk, 2)
    stats = {
        "as_of": str(as_of),
        "statement_from": str(bank["date"].min()) if not bank.empty else None,
        "statement_to": str(bank["date"].max()) if not bank.empty else None,
        "payments": int(len(payments)),
        "gross_collected": round(float(payments["amount"].sum()), 2),
        "fees": round(float(payments["fee"].sum()), 2),
        "gst": round(float(payments["tax"].sum()), 2),
        "refunds": round(float(report.loc[report["type"] == "refund", "amount"].sum()), 2),
        "settlements_in_period": int(len(in_period)),
        "settlements_matched": int((settlements["status"] == "matched").sum()),
        "expected_payouts": round(float(in_period["expected"].sum()), 2),
        "received_payouts": round(float(sum(a for a in in_period["bank_amount"] if a is not None)), 2),
        "bank_rows_used": len(used),
        "exceptions": len(exceptions),
        "at_risk_high": round(sum(e.amount_at_risk for e in exceptions if e.severity == "high"), 2),
        "at_risk_total": round(sum(e.amount_at_risk for e in exceptions), 2),
        "by_type": by_type,
    }
    return Result(exceptions, settlements, stats, notes)

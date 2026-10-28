"""Generate a realistic month of data for a fictional home-services merchant, with known problems.

Outputs (in --out, default data/samples):
    settlement_report.csv   Razorpay-style settlement recon export
    orders.csv              the merchant's own bookings export
    bank_format_a.csv       private-bank style: preamble rows, dd/mm/yy, Withdrawal/Deposit columns
    bank_format_b.xlsx      Excel export: title rows, dd-Mon-yyyy, amounts as "1,23,456.00" text
    bank_format_c.csv       single Amount + Cr/Dr column, ISO timestamps
    bank_format_d.csv       Hindi headers, newest-first (rules can't map this; the LLM path can)
    ground_truth.json       every injected problem: {type, key}

Same transactions in every bank format, so accuracy is comparable across layouts.
Run:  python data/generate.py --seed 7
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import string
from datetime import date, datetime, timedelta
from pathlib import Path

MERCHANT = "FIXLY HOME SERVICES"
PRICES = [199, 249, 299, 349, 399, 449, 499, 599, 699, 799, 999, 1299, 1499, 1999, 2499, 3499]
METHODS = [("upi", 0.60), ("card", 0.25), ("netbanking", 0.10), ("wallet", 0.05)]
TECHS = ["RAMESH ELECTRICALS", "SURESH PLUMBING", "LAKSHMI CLEANING", "ANIL AC REPAIR", "MOHAN CARPENTRY"]
CUSTOMERS = [
    "Priya",
    "Rahul",
    "Ananya",
    "Vikram",
    "Sneha",
    "Arjun",
    "Kavya",
    "Rohit",
    "Divya",
    "Karthik",
    "Meera",
    "Aditya",
    "Pooja",
    "Sai",
    "Harini",
    "Naveen",
    "Lakshmi",
    "Varun",
    "Swathi",
    "Teja",
]


def _id(rng: random.Random, prefix: str, n: int = 14) -> str:
    return f"{prefix}_" + "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(n))


def _utr(rng: random.Random, d: date) -> str:
    return "AXISN" + d.strftime("%y%j") + "".join(rng.choice(string.digits) for _ in range(6))


def _settle_date(d: date, days: int = 2) -> date:
    s = d + timedelta(days=days)
    return s + timedelta(days=1) if s.weekday() == 6 else s  # no Sunday payouts


def _method(rng: random.Random) -> str:
    return rng.choices([m for m, _ in METHODS], weights=[w for _, w in METHODS])[0]


def build(seed: int = 7, year: int = 2026, month: int = 9, n_orders: int = 320, hard: bool = False) -> dict:
    """hard=True adds real-world mess: bank posting lag of 0-3 days and 30% of narrations cut before the UTR."""
    rng = random.Random(seed)
    noise = random.Random(seed * 7919 + 1)  # separate stream, so hard mode keeps the same base data
    start = date(year, month, 1)
    end = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    days = (end - start).days + 1
    truth: list[dict] = []

    # ---- orders and their payments
    orders, payments = [], []
    for i in range(n_orders):
        created = datetime.combine(start + timedelta(days=rng.randrange(days)), datetime.min.time()) + timedelta(
            hours=rng.randint(8, 21), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
        )
        amount = float(rng.choice(PRICES))
        ref = f"FX{seed:02d}{i:04d}"
        orders.append(
            {
                "ref": ref,
                "amount": amount,
                "status": "Completed",
                "created": created,
                "customer": rng.choice(CUSTOMERS),
                "service": rng.choice(["Electrician", "Plumber", "Cleaning", "AC Service", "Carpenter"]),
            }
        )
        method = _method(rng)
        fee = round(amount * 2.0 / 100, 2)
        payments.append(
            {
                "id": _id(rng, "pay"),
                "receipt": ref,
                "order_id": _id(rng, "order"),
                "amount": amount,
                "fee": fee,
                "tax": round(fee * 0.18, 2),
                "method": method,
                "created": created,
                "settled": True,
                "on_hold": False,
            }
        )

    by_ref = {p["receipt"]: p for p in payments}
    order_by_ref = {o["ref"]: o for o in orders}
    early = [o["ref"] for o in orders if o["created"].date() <= end - timedelta(days=8)]
    pool = rng.sample(early, 34)
    take = lambda n: [pool.pop() for _ in range(n)]  # noqa: E731

    # ---- normal refunds (must NOT be flagged)
    refunds = []
    for k, ref in enumerate(take(10)):
        p = by_ref[ref]
        full = k < 7
        amt = p["amount"] if full else round(p["amount"] * 0.3, 2)
        refunds.append(
            {
                "id": _id(rng, "rfnd"),
                "receipt": ref,
                "payment": p["id"],
                "amount": amt,
                "created": p["created"] + timedelta(days=rng.randint(1, 4), hours=2),
            }
        )
        if full:
            order_by_ref[ref]["status"] = "Cancelled"

    # ---- payment-level problems
    for ref in take(3):
        p = by_ref[ref]
        p["method"] = "card"
        p["fee"] = round(p["amount"] * 3.5 / 100, 2)
        p["tax"] = round(p["fee"] * 0.18, 2)
        truth.append({"type": "fee_anomaly", "key": p["id"]})
    for ref in take(2):
        p = by_ref[ref]
        p["tax"] = round(p["fee"] * 0.28, 2)
        truth.append({"type": "gst_mismatch", "key": p["id"]})
    for ref in take(3):
        p = by_ref[ref]
        p["settled"] = False
        truth.append({"type": "unsettled_payment", "key": p["id"]})
    by_ref[take(1)[0]].update(settled=False, on_hold=True)  # on hold: must NOT be flagged

    # ---- order-level problems
    for ref in take(2):
        p = by_ref[ref]
        dup = dict(p, id=_id(rng, "pay"), created=p["created"] + timedelta(minutes=2))
        payments.append(dup)
        truth.append({"type": "duplicate_payment", "key": ref})
    for ref in take(3):
        payments.remove(by_ref[ref])
        truth.append({"type": "order_without_payment", "key": ref})
    for ref in take(2):
        order_by_ref[ref]["status"] = "Cancelled"
        truth.append({"type": "paid_on_cancelled_order", "key": ref})
    for ref in take(2):
        order_by_ref[ref]["amount"] += 100.0
        truth.append({"type": "amount_mismatch_order", "key": ref})

    # ---- settlements: one per payout day
    report_rows, settlement_of = [], {}
    for p in payments:
        if p["settled"]:
            settlement_of.setdefault(_settle_date(p["created"].date()), []).append(("payment", p))
    for r in refunds:  # refunds are netted off the next payout that has payments in it
        target = _settle_date(r["created"].date())
        settlement_of[min(d for d in settlement_of if d >= target)].append(("refund", r))
    settlements = []
    for sdate in sorted(settlement_of):
        sid, utr = _id(rng, "setl"), _utr(rng, sdate)
        net = 0.0
        for kind, e in settlement_of[sdate]:
            e["settlement"] = (sid, utr, sdate)
            net += (e["amount"] - e["fee"] - e["tax"]) if kind == "payment" else -e["amount"]
        settlements.append({"id": sid, "utr": utr, "date": sdate, "net": round(net, 2)})
    carry = 0.0  # negative balance rolls into the next payout, as Razorpay does
    for s in settlements:
        value = round(s["net"] + carry, 2)
        s["payout"], carry = max(value, 0.0), min(value, 0.0)

    for p in payments:
        s = p.get("settlement")
        report_rows.append(
            {
                "entity_id": p["id"],
                "type": "payment",
                "debit": "0.00",
                "credit": f"{p['amount'] - p['fee'] - p['tax']:.2f}" if p["settled"] else "0.00",
                "amount": f"{p['amount']:.2f}",
                "currency": "INR",
                "fee": f"{p['fee']:.2f}",
                "tax": f"{p['tax']:.2f}",
                "on_hold": int(p["on_hold"]),
                "settled": int(p["settled"]),
                "created_at": p["created"].strftime("%d/%m/%Y %H:%M:%S"),
                "settled_at": s[2].strftime("%d/%m/%Y 09:15:00") if s else "",
                "settlement_id": s[0] if s else "",
                "settlement_utr": s[1] if s else "",
                "description": "",
                "order_id": p["order_id"],
                "order_receipt": p["receipt"],
                "method": p["method"],
            }
        )
    for r in refunds:
        s = r["settlement"]
        report_rows.append(
            {
                "entity_id": r["id"],
                "type": "refund",
                "debit": f"{r['amount']:.2f}",
                "credit": "0.00",
                "amount": f"{r['amount']:.2f}",
                "currency": "INR",
                "fee": "0.00",
                "tax": "0.00",
                "on_hold": 0,
                "settled": 1,
                "created_at": r["created"].strftime("%d/%m/%Y %H:%M:%S"),
                "settled_at": s[2].strftime("%d/%m/%Y 09:15:00"),
                "settlement_id": s[0],
                "settlement_utr": s[1],
                "description": f"Refund for {r['payment']}",
                "order_id": by_ref[r["receipt"]]["order_id"],
                "order_receipt": r["receipt"],
                "method": by_ref[r["receipt"]]["method"],
            }
        )
    report_rows.sort(key=lambda r: datetime.strptime(r["created_at"], "%d/%m/%Y %H:%M:%S"))

    # ---- bank: payouts in the statement month, with problems
    in_month = [s for s in settlements if s["date"] <= end - timedelta(days=2) and s["payout"] > 0]
    picks = rng.sample(in_month, 6)
    missing, short, truncated = picks[:2], picks[2:4], picks[4:6]
    for s in missing:
        truth.append({"type": "missing_payout", "key": s["id"]})
    for s in short:
        truth.append({"type": "short_credit", "key": s["id"]})
    short_by = {s["id"]: rng.choice([150.0, 500.0, 1234.5]) for s in short}

    txns = []  # (datetime, kind, narration_parts, amount)
    for s in settlements:
        if s["date"] > end or s in missing or s["payout"] <= 0:  # refunds > payments -> no payout that day
            continue
        amount = round(s["payout"] - short_by.get(s["id"], 0.0), 2)
        when = datetime.combine(s["date"], datetime.min.time()) + timedelta(
            hours=rng.randint(10, 15), minutes=rng.randint(0, 59)
        )
        cut = s in truncated
        if hard:
            when += timedelta(days=noise.choices([0, 1, 2, 3], weights=[60, 25, 10, 5])[0])
            cut = cut or noise.random() < 0.30
            if when.date() > end:
                continue  # posted after the statement closed
        txns.append((when, "payout", {"utr": None if cut else s["utr"]}, amount))
    stray_utr = _utr(rng, start + timedelta(days=17))
    txns.append(
        (
            datetime.combine(start + timedelta(days=17), datetime.min.time()) + timedelta(hours=13),
            "payout",
            {"utr": stray_utr},
            float(rng.randint(2000, 6000)),
        )
    )
    truth.append({"type": "unknown_credit", "key": stray_utr})

    for d in range(days):
        day = start + timedelta(days=d)
        for _ in range(rng.randint(0, 3)):
            txns.append(
                (
                    datetime.combine(day, datetime.min.time())
                    + timedelta(hours=rng.randint(9, 20), minutes=rng.randint(0, 59)),
                    "upi_dr",
                    {"name": rng.choice(TECHS), "ref": str(rng.randint(10**11, 10**12 - 1))},
                    -float(rng.randint(250, 2200)),
                )
            )
    for d in rng.sample(range(days), 6):
        txns.append(
            (
                datetime.combine(start + timedelta(days=d), datetime.min.time()) + timedelta(hours=16),
                "upi_cr",
                {"name": rng.choice(CUSTOMERS).upper(), "ref": str(rng.randint(10**11, 10**12 - 1))},
                float(rng.choice(PRICES)),
            )
        )
    txns.append(
        (datetime.combine(start + timedelta(days=4), datetime.min.time()) + timedelta(hours=11), "rent", {}, -25000.0)
    )
    for k in range(3):
        txns.append(
            (
                datetime.combine(start, datetime.min.time()) + timedelta(hours=10, minutes=k),
                "salary",
                {"k": k},
                -15000.0,
            )
        )
    txns.append((datetime.combine(end, datetime.min.time()) + timedelta(hours=23), "charges", {}, -118.0))
    txns.sort(key=lambda t: t[0])

    balance = 150000.0
    bank = []
    for when, kind, info, amount in txns:
        balance = round(balance + amount, 2)
        bank.append({"when": when, "kind": kind, "info": info, "amount": amount, "balance": balance})

    return {"report": report_rows, "orders": orders, "bank": bank, "truth": truth, "start": start, "end": end}


# ------------------------------------------------------------------ bank narrations per layout


def _narration(fmt: str, kind: str, info: dict) -> tuple[str, str]:
    utr = info.get("utr")
    if kind == "payout":
        if fmt == "a":
            return (
                f"NEFT CR-UTIB0000247-RAZORPAY SOFTWARE PRIVATE LIMITED-{MERCHANT}-{utr}"
                if utr
                else "NEFT CR-UTIB0000247-RAZORPAY SOFTWARE PRIVATE LIM",
                utr or "0000000000000000",
            )
        if fmt == "b":
            return (f"NEFT/{utr}/RAZORPAY SOFTWARE PVT LTD" if utr else "NEFT/RAZORPAY SOFTWARE PVT", utr or "")
        return (
            f"BY TRANSFER-NEFT*UTIB0000247*{utr}*RAZORPAY SOFTWA"
            if utr
            else "BY TRANSFER-NEFT*UTIB0000247*RAZORPAY SOFTWA",
            "",
        )
    if kind == "upi_dr":
        return f"UPI/DR/{info['ref']}/{info['name']}/YESB/payout", info["ref"]
    if kind == "upi_cr":
        return f"UPI/CR/{info['ref']}/{info['name']}/OKSBI/service", info["ref"]
    if kind == "rent":
        return "NEFT DR-HDFC0001234-SRI VENKATESWARA ESTATES-RENT SEP", ""
    if kind == "salary":
        return f"IMPS-6{info['k']}2490113-STAFF SALARY-{['KIRAN', 'BHARGAV', 'USHA'][info['k']]}", ""
    return "SMS ALERT CHARGES INCL GST", ""


def write(data: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    start, end = data["start"], data["end"]

    with open(out / "settlement_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data["report"][0].keys()))
        w.writeheader()
        w.writerows(data["report"])

    with open(out / "orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Booking ID", "Customer", "Service", "Amount (₹)", "Order Status", "Booked On"])
        for o in data["orders"]:
            w.writerow(
                [
                    o["ref"],
                    o["customer"],
                    o["service"],
                    f"{o['amount']:.0f}",
                    o["status"],
                    o["created"].strftime("%d-%m-%Y %H:%M"),
                ]
            )

    from recon.parse import inr  # noqa: E402  (format amounts the Indian way)

    with open(out / "bank_format_a.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"{MERCHANT}"])
        w.writerow(
            [
                "Account No :",
                "XXXXXXXX4417",
                "",
                "Statement From :",
                start.strftime("%d/%m/%y"),
                "To :",
                end.strftime("%d/%m/%y"),
            ]
        )
        w.writerow([])
        w.writerow(
            ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
        )
        for t in data["bank"]:
            text, ref = _narration("a", t["kind"], t["info"])
            d = t["when"].strftime("%d/%m/%y")
            w.writerow(
                [
                    d,
                    text,
                    ref,
                    d,
                    f"{-t['amount']:.2f}" if t["amount"] < 0 else "",
                    f"{t['amount']:.2f}" if t["amount"] > 0 else "",
                    f"{t['balance']:.2f}",
                ]
            )
        w.writerow([])
        w.writerow(["*** This is a computer generated statement ***"])

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws.append([f"Account Statement - {MERCHANT}"])
    ws.append([f"Period: {start.strftime('%d-%b-%Y')} to {end.strftime('%d-%b-%Y')}"])
    ws.append([])
    ws.append(["Transaction Date", "Value Date", "Description", "Ref No./Cheque No.", "Debit", "Credit", "Balance"])
    for t in data["bank"]:
        text, ref = _narration("b", t["kind"], t["info"])
        d = t["when"].strftime("%d-%b-%Y")
        ws.append(
            [
                d,
                d,
                text,
                ref,
                inr(-t["amount"]) if t["amount"] < 0 else "",
                inr(t["amount"]) if t["amount"] > 0 else "",
                inr(t["balance"]),
            ]
        )
    wb.save(out / "bank_format_b.xlsx")

    with open(out / "bank_format_c.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Txn Posted Date", "Transaction Remarks", "Amount", "Cr/Dr", "Balance"])
        for t in data["bank"]:
            text, _ = _narration("c", t["kind"], t["info"])
            w.writerow(
                [
                    t["when"].strftime("%Y-%m-%d %H:%M:%S"),
                    text,
                    f"{abs(t['amount']):.2f}",
                    "CR" if t["amount"] > 0 else "DR",
                    f"{t['balance']:.2f}",
                ]
            )

    with open(out / "bank_format_d.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["खाता विवरण"])
        w.writerow(["लेनदेन तिथि", "विवरण", "संदर्भ संख्या", "नामे", "जमा", "शेष"])
        for t in reversed(data["bank"]):
            text, ref = _narration("b", t["kind"], t["info"])
            w.writerow(
                [
                    t["when"].strftime("%d/%m/%Y"),
                    text,
                    ref,
                    f"{-t['amount']:.2f}" if t["amount"] < 0 else "",
                    f"{t['amount']:.2f}" if t["amount"] > 0 else "",
                    f"{t['balance']:.2f}",
                ]
            )

    (out / "ground_truth.json").write_text(json.dumps(data["truth"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "samples")
    parser.add_argument("--hard", action="store_true", help="add posting lag and truncated narrations")
    args = parser.parse_args()
    data = build(args.seed, hard=args.hard)
    write(data, args.out)
    print(
        f"wrote {args.out} ({len(data['report'])} report rows, {len(data['bank'])} bank rows, {len(data['truth'])} injected problems)"
    )


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()

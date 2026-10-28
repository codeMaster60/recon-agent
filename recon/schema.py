"""Canonical fields for each input file, with the header names real exports use."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    name: str
    description: str
    synonyms: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True)
class Schema:
    name: str
    fields: tuple[Field, ...] = field(default_factory=tuple)

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]


BANK = Schema(
    "bank_statement",
    (
        Field(
            "date",
            "Date the transaction was posted",
            (
                "date",
                "txn date",
                "transaction date",
                "tran date",
                "posting date",
                "txn posted date",
                "post date",
                "trans date",
                "value date",
            ),
            required=True,
        ),
        Field("value_date", "Value date, if a separate column exists", ("value dt", "value date")),
        Field(
            "description",
            "Narration / particulars text of the transaction",
            (
                "narration",
                "description",
                "particulars",
                "transaction remarks",
                "remarks",
                "details",
                "transaction details",
                "transaction description",
            ),
            required=True,
        ),
        Field(
            "ref",
            "Cheque / reference / UTR number column",
            (
                "chq ref no",
                "ref no cheque no",
                "chq no",
                "cheque no",
                "ref no",
                "reference",
                "reference no",
                "utr",
                "utr no",
                "transaction id",
                "tran id",
            ),
        ),
        Field(
            "debit",
            "Money going out (withdrawal) column",
            (
                "withdrawal amt",
                "withdrawal",
                "withdrawals",
                "debit",
                "debit amount",
                "dr amount",
                "withdrawal amount",
                "withdrawals inr",
                "debit inr",
            ),
        ),
        Field(
            "credit",
            "Money coming in (deposit) column",
            (
                "deposit amt",
                "deposit",
                "deposits",
                "credit",
                "credit amount",
                "cr amount",
                "deposit amount",
                "deposits inr",
                "credit inr",
            ),
        ),
        Field(
            "amount",
            "Single signed or unsigned amount column (only when no separate debit/credit)",
            (
                "amount",
                "txn amount",
                "transaction amount",
                "amount inr",
            ),
        ),
        Field(
            "drcr",
            "Column saying whether the amount is a credit or debit (CR/DR)",
            (
                "cr dr",
                "dr cr",
                "debit credit",
                "credit debit",
                "txn type",
                "type",
                "cr dr indicator",
            ),
        ),
        Field(
            "balance",
            "Running balance after the transaction",
            (
                "closing balance",
                "balance",
                "running balance",
                "available balance",
                "balance inr",
            ),
        ),
    ),
)

ORDERS = Schema(
    "orders",
    (
        Field(
            "order_ref",
            "Merchant's own order / booking / invoice id (sent to Razorpay as receipt)",
            (
                "receipt",
                "order receipt",
                "booking id",
                "order id",
                "order no",
                "order number",
                "invoice no",
                "invoice",
                "order ref",
                "reference",
            ),
            required=True,
        ),
        Field(
            "amount",
            "Order value the customer should have paid, in rupees",
            (
                "amount",
                "order total",
                "total",
                "grand total",
                "amount paid",
                "order amount",
                "net amount",
            ),
            required=True,
        ),
        Field(
            "status",
            "Order status (paid / completed / cancelled ...)",
            (
                "status",
                "order status",
                "payment status",
                "state",
            ),
        ),
        Field(
            "created_at",
            "When the order was placed",
            (
                "created at",
                "order date",
                "booked on",
                "booking date",
                "date",
                "created",
            ),
        ),
        Field("customer", "Customer name", ("customer", "customer name", "name")),
    ),
)

# Column names follow Razorpay's settlement reconciliation export.
REPORT = Schema(
    "settlement_report",
    (
        Field("entity_id", "pay_/rfnd_/adj_ id", ("entity id", "entity_id", "id"), required=True),
        Field("type", "payment, refund, adjustment ...", ("type", "entity type"), required=True),
        Field("debit", "Amount debited from the settlement", ("debit",)),
        Field("credit", "Amount credited to the settlement", ("credit",)),
        Field("amount", "Gross transaction amount", ("amount",), required=True),
        Field("fee", "Gateway fee (pre-tax)", ("fee", "fees")),
        Field("tax", "GST on the fee", ("tax", "gst")),
        Field("on_hold", "1 if the payment is on hold", ("on hold", "on_hold")),
        Field("settled", "1 if settled", ("settled",)),
        Field("created_at", "Transaction time", ("created at", "created_at")),
        Field("settled_at", "Settlement time", ("settled at", "settled_at")),
        Field("settlement_id", "setl_ id", ("settlement id", "settlement_id")),
        Field("settlement_utr", "Bank UTR of the settlement payout", ("settlement utr", "settlement_utr", "utr")),
        Field(
            "order_receipt",
            "Merchant receipt passed when creating the order",
            ("order receipt", "order_receipt", "receipt"),
        ),
        Field("method", "Payment method", ("method", "payment method")),
    ),
)

SCHEMAS = {"bank": BANK, "orders": ORDERS, "report": REPORT}

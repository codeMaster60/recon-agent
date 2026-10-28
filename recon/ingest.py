"""Load any CSV/XLSX export, find its header row, map its columns, and check the mapping.

Column mapping has two sources:
  * rules - header synonyms in schema.py (free, instant, handles common layouts)
  * llm   - the model reads headers + sample rows (handles unfamiliar or non-English layouts)

Neither is trusted blindly. Every candidate mapping is scored by code: do the dates parse,
do the amounts parse, and - for bank statements - does the running balance reconcile row by
row? The balance check also catches swapped debit/credit columns and fixes the sign.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .llm import LLMClient, LLMError, parse_json_object
from .parse import is_blank, norm_text, parse_amount, parse_dates
from .schema import BANK, ORDERS, REPORT, Schema

ACCEPT_SCORE = 0.85       # minimum validation score for a mapping to be used
RULES_FAST_PATH = 0.95    # rules mapping this good -> don't spend an LLM call


class MappingError(ValueError):
    pass


@dataclass
class MappingResult:
    mapping: dict[str, str]
    source: str                      # "rules" | "llm"
    score: float = 0.0
    checks: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class Loaded:
    df: pd.DataFrame
    chosen: MappingResult
    header_row: int
    headers: list[str]
    tried: list[MappingResult]

    def describe(self) -> str:
        pairs = ", ".join(f"{k} <- '{v}'" for k, v in self.chosen.mapping.items())
        return f"[{self.chosen.source}, score {self.chosen.score:.2f}] {pairs}"


# --------------------------------------------------------------------------- reading

def read_raw(source, filename: str | None = None) -> list[list[str]]:
    """Return the sheet as a list of string rows. Accepts a path, bytes, or an uploaded file."""
    name = filename or getattr(source, "name", None) or (str(source) if isinstance(source, (str, Path)) else "")
    if isinstance(source, (str, Path)):
        data = Path(source).read_bytes()
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    elif hasattr(source, "getvalue"):
        data = source.getvalue()
    else:
        data = source.read()

    if name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        frame = pd.read_excel(io.BytesIO(data), header=None, dtype=object)
        rows = []
        for record in frame.itertuples(index=False):
            row = []
            for cell in record:
                if is_blank(cell):
                    row.append("")
                elif hasattr(cell, "strftime"):
                    row.append(cell.strftime("%Y-%m-%d %H:%M:%S"))
                else:
                    row.append(str(cell).strip())
            rows.append(row)
        return rows

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


# --------------------------------------------------------------------------- header + rules mapping

def _norm_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(header).lower()).strip()


def _synonym_score(header: str, synonyms: tuple[str, ...]) -> int:
    h = _norm_header(header)
    if not h:
        return 0
    best = 0
    for rank, synonym in enumerate(synonyms):
        s = _norm_header(synonym)
        if h == s:
            best = max(best, 100 - rank)
        elif re.search(rf"\b{re.escape(s)}\b", h):
            best = max(best, 60 - rank)
    return best


def _looks_like_value(cell: str) -> bool:
    return parse_amount(cell) is not None or bool(parse_dates([cell])[0])


def detect_header_row(rows: list[list[str]], schema: Schema) -> int:
    best_row, best_hits = -1, 1
    for i, row in enumerate(rows[:40]):
        hits = sum(1 for cell in row if any(_synonym_score(cell, f.synonyms) for f in schema.fields))
        if hits > best_hits:
            best_row, best_hits = i, hits
    if best_row >= 0:
        return best_row
    # Structural fallback for headers we have no synonyms for (e.g. Hindi):
    # first row of >= 3 text cells that is followed by a row containing numbers.
    for i, row in enumerate(rows[:40]):
        cells = [c for c in row if c]
        if len(cells) >= 3 and sum(not _looks_like_value(c) for c in cells) >= 0.8 * len(cells):
            nxt = rows[i + 1] if i + 1 < len(rows) else []
            if any(parse_amount(c) is not None for c in nxt if c):
                return i
    raise MappingError("Could not find a header row in the first 40 rows.")


def rules_mapping(headers: list[str], schema: Schema) -> dict[str, str]:
    scored = []
    for f in schema.fields:
        for h in headers:
            s = _synonym_score(h, f.synonyms)
            if s:
                scored.append((s, f.name, h))
    scored.sort(key=lambda t: -t[0])
    mapping, used = {}, set()
    for _, name, header in scored:
        if name not in mapping and header not in used:
            mapping[name] = header
            used.add(header)
    return mapping


def llm_mapping(headers: list[str], samples: list[list[str]], schema: Schema, client: LLMClient) -> dict[str, str]:
    field_lines = "\n".join(f"- {f.name}: {f.description}" for f in schema.fields)
    user = (
        f"Target schema '{schema.name}':\n{field_lines}\n\n"
        f"Column headers (exact strings):\n{json.dumps(headers, ensure_ascii=False)}\n\n"
        f"First data rows:\n{json.dumps(samples, ensure_ascii=False)}\n\n"
        "Return one JSON object: each schema field name -> the exact header string it maps to, "
        "or null if no column fits. Use each header at most once. Read the sample values, not just "
        "the header text. For bank statements map either debit + credit, or amount (+ drcr)."
    )
    system = "You map spreadsheet columns onto a fixed schema for a payment reconciliation tool. Reply with JSON only."
    raw = parse_json_object(client.chat(system, user, json_mode=True))
    mapping, used = {}, set()
    for name in schema.names:
        header = raw.get(name)
        if isinstance(header, str) and header in headers and header not in used:
            mapping[name] = header
            used.add(header)
    return mapping


# --------------------------------------------------------------------------- canonical frames

def _column(rows: list[list[str]], headers: list[str], mapping: dict[str, str], name: str) -> list[str]:
    if name not in mapping:
        return [""] * len(rows)
    idx = headers.index(mapping[name])
    return [row[idx] if idx < len(row) else "" for row in rows]


def _bank_frame(rows, headers, mapping) -> pd.DataFrame:
    dates = parse_dates(_column(rows, headers, mapping, "date"))
    desc = _column(rows, headers, mapping, "description")
    refs = _column(rows, headers, mapping, "ref")
    balances = [parse_amount(v) for v in _column(rows, headers, mapping, "balance")]
    amounts: list[float | None] = []
    if "debit" in mapping or "credit" in mapping:
        for dr, cr in zip(_column(rows, headers, mapping, "debit"), _column(rows, headers, mapping, "credit")):
            d, c = parse_amount(dr), parse_amount(cr)
            amounts.append(None if d is None and c is None else abs(c or 0.0) - abs(d or 0.0))
    elif "amount" in mapping:
        drcr = _column(rows, headers, mapping, "drcr")
        for value, flag in zip(_column(rows, headers, mapping, "amount"), drcr):
            a = parse_amount(value)
            token = norm_text(flag).lower()
            if a is not None and token:
                a = abs(a) if token.startswith("c") else -abs(a) if token.startswith("d") else a
            amounts.append(a)
    else:
        amounts = [None] * len(rows)
    frame = pd.DataFrame({
        "date": dates, "description": [norm_text(d) for d in desc], "ref": [norm_text(r) for r in refs],
        "amount": amounts, "balance": balances, "row": range(len(rows)),
    })
    return frame[frame["date"].notna() & frame["amount"].notna()].reset_index(drop=True)


def _continuity(frame: pd.DataFrame, sign: float = 1.0) -> float:
    """Share of consecutive rows where previous balance + amount == balance (either sort order)."""
    bal, amt = frame["balance"].tolist(), (frame["amount"] * sign).tolist()
    pairs = [(i - 1, i) for i in range(1, len(bal)) if bal[i] is not None and bal[i - 1] is not None]
    if not pairs:
        return float("nan")
    forward = sum(abs(bal[a] + amt[b] - bal[b]) < 0.011 for a, b in pairs) / len(pairs)
    backward = sum(abs(bal[b] + amt[a] - bal[a]) < 0.011 for a, b in pairs) / len(pairs)
    return max(forward, backward)


def _score_bank(rows, headers, mapping) -> tuple[float, dict, list[str], pd.DataFrame]:
    notes: list[str] = []
    missing = [f for f in ("date", "description") if f not in mapping]
    has_amount = any(f in mapping for f in ("debit", "credit", "amount"))
    if missing or not has_amount:
        return 0.0, {}, [f"missing fields: {missing or ['amount']}"], pd.DataFrame()
    frame = _bank_frame(rows, headers, mapping)
    nonblank = [r for r in rows if sum(1 for c in r if c) >= 2]
    date_rate = len(frame) / max(1, len(nonblank))
    text_rate = sum(parse_amount(d) is None for d in frame["description"]) / max(1, len(frame))
    checks = {"rows_parsed": round(date_rate, 3), "description_is_text": round(text_rate, 3)}
    if "balance" in mapping and frame["balance"].notna().any():
        straight, flipped = _continuity(frame, 1.0), _continuity(frame, -1.0)
        if flipped > straight + 0.2:
            frame["amount"] = -frame["amount"]
            notes.append("debit/credit looked swapped; corrected using the running balance")
            straight = flipped
        checks["balance_continuity"] = round(straight, 3)
        score = (date_rate + text_rate + 2 * straight) / 4
    else:
        notes.append("no balance column, so the mapping could not be cross-checked")
        score = 0.9 * (date_rate + text_rate) / 2
    return score, checks, notes, frame


def _orders_frame(rows, headers, mapping) -> pd.DataFrame:
    status_raw = [norm_text(s).lower() for s in _column(rows, headers, mapping, "status")]

    def norm_status(s: str) -> str:
        if not s:
            return "paid"
        if any(k in s for k in ("cancel", "fail", "void", "refund", "reject")):
            return "cancelled"
        if any(k in s for k in ("paid", "complete", "success", "captur", "deliver", "done", "settled")):
            return "paid"
        return "pending"

    frame = pd.DataFrame({
        "order_ref": [norm_text(v) for v in _column(rows, headers, mapping, "order_ref")],
        "amount": [parse_amount(v) for v in _column(rows, headers, mapping, "amount")],
        "status_raw": status_raw,
        "status": [norm_status(s) for s in status_raw],
        "created_at": parse_dates(_column(rows, headers, mapping, "created_at")),
        "customer": [norm_text(v) for v in _column(rows, headers, mapping, "customer")],
    })
    return frame[(frame["order_ref"] != "") & frame["amount"].notna()].reset_index(drop=True)


def _score_orders(rows, headers, mapping):
    if not all(f in mapping for f in ("order_ref", "amount")):
        return 0.0, {}, ["missing order_ref or amount"], pd.DataFrame()
    frame = _orders_frame(rows, headers, mapping)
    nonblank = [r for r in rows if any(r)]
    rate = len(frame) / max(1, len(nonblank))
    unique = frame["order_ref"].nunique() / max(1, len(frame))
    return (rate + unique) / 2, {"rows_parsed": round(rate, 3), "unique_refs": round(unique, 3)}, [], frame


def _flag(value) -> bool:
    return norm_text(value).lower() in {"1", "true", "yes", "y", "t"}


def _report_frame(rows, headers, mapping) -> pd.DataFrame:
    col = lambda name: _column(rows, headers, mapping, name)  # noqa: E731
    num = lambda name: [parse_amount(v) for v in col(name)]  # noqa: E731
    frame = pd.DataFrame({
        "entity_id": [norm_text(v) for v in col("entity_id")],
        "type": [norm_text(v).lower() for v in col("type")],
        "amount": num("amount"), "fee": num("fee"), "tax": num("tax"),
        "credit": num("credit"), "debit": num("debit"),
        "on_hold": [_flag(v) for v in col("on_hold")],
        "settled": [_flag(v) for v in col("settled")],
        "created_at": parse_dates(col("created_at")),
        "settled_at": parse_dates(col("settled_at")),
        "settlement_id": [norm_text(v) for v in col("settlement_id")],
        "settlement_utr": [norm_text(v).upper() for v in col("settlement_utr")],
        "order_receipt": [norm_text(v) for v in col("order_receipt")],
        "method": [norm_text(v).lower() for v in col("method")],
    })
    frame = frame[(frame["entity_id"] != "") & frame["amount"].notna()].reset_index(drop=True)
    for c in ("fee", "tax"):
        frame[c] = frame[c].fillna(0.0)
    is_pay = frame["type"] == "payment"
    frame["credit"] = frame["credit"].where(frame["credit"].notna(), (frame["amount"] - frame["fee"] - frame["tax"]).where(is_pay, 0.0))
    frame["debit"] = frame["debit"].where(frame["debit"].notna(), frame["amount"].where(~is_pay, 0.0))
    if "settled" not in mapping:
        frame["settled"] = frame["settlement_id"] != ""
    return frame


def _score_report(rows, headers, mapping):
    if not all(f in mapping for f in ("entity_id", "type", "amount")):
        return 0.0, {}, ["missing entity_id, type or amount"], pd.DataFrame()
    frame = _report_frame(rows, headers, mapping)
    nonblank = [r for r in rows if any(r)]
    rate = len(frame) / max(1, len(nonblank))
    known = frame["type"].isin(["payment", "refund", "adjustment", "transfer", "reversal", "dispute"]).mean() if len(frame) else 0
    return (rate + known) / 2, {"rows_parsed": round(rate, 3), "known_types": round(float(known), 3)}, [], frame


_SCORERS = {"bank_statement": _score_bank, "orders": _score_orders, "settlement_report": _score_report}


# --------------------------------------------------------------------------- public API

def load(source, schema: Schema, filename: str | None = None, client: LLMClient | None = None,
         mode: str = "auto") -> Loaded:
    """mode: 'rules' (never call the LLM), 'llm' (always try it), 'auto' (LLM only if rules fall short)."""
    rows = read_raw(source, filename)
    header_row = detect_header_row(rows, schema)
    headers = [h.strip() for h in rows[header_row]]
    body = [r + [""] * (len(headers) - len(r)) for r in rows[header_row + 1:]]
    scorer = _SCORERS[schema.name]

    tried: list[MappingResult] = []
    frames: dict[int, pd.DataFrame] = {}

    def attempt(mapping: dict[str, str], source_name: str) -> MappingResult:
        score, checks, notes, frame = scorer(body, headers, mapping)
        result = MappingResult(mapping, source_name, round(score, 3), checks, notes)
        tried.append(result)
        frames[id(result)] = frame
        return result

    rules = attempt(rules_mapping(headers, schema), "rules")
    want_llm = client is not None and (mode == "llm" or (mode == "auto" and rules.score < RULES_FAST_PATH))
    if want_llm:
        samples = [r for r in body if any(r)][:6]
        try:
            attempt(llm_mapping(headers, samples, schema, client), "llm")
        except (LLMError, ValueError) as exc:
            rules.notes.append(f"LLM mapping unavailable: {exc}")

    best = max(tried, key=lambda r: r.score)
    if best.score < ACCEPT_SCORE:
        hint = "" if client else " Set GROQ_API_KEY (or RECON_LLM_API_KEY) so the LLM can map unfamiliar layouts."
        detail = "; ".join(f"{r.source}: score {r.score} {r.notes}" for r in tried)
        raise MappingError(f"Could not map columns of {schema.name} (headers: {headers}). {detail}.{hint}")
    return Loaded(frames[id(best)], best, header_row, headers, tried)


def load_bank(source, filename=None, client=None, mode="auto") -> Loaded:
    return load(source, BANK, filename, client, mode)


def load_orders(source, filename=None, client=None, mode="auto") -> Loaded:
    return load(source, ORDERS, filename, client, mode)


def load_report(source, filename=None, client=None, mode="auto") -> Loaded:
    return load(source, REPORT, filename, client, mode)

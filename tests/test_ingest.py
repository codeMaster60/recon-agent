"""File reading, header detection and column mapping edge cases."""

import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook

from recon.ingest import MappingError, detect_header_row, llm_mapping, load_bank, load_orders, load_report, read_raw
from recon.llm import LLMError
from recon.parse import inr, is_blank, parse_amount, parse_dates
from recon.schema import BANK

BANK_CSV = b"Date,Narration,Debit,Credit,Balance\n01/09/2026,NEFT/RAZORPAY,,100,100\n02/09/2026,RENT,40,,60\n"


class Client:
    model = "stub"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, 0

    def chat(self, system, user, json_mode=False):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reply


# ---------------------------------------------------------------- parse helpers


def test_is_blank_variants():
    assert is_blank(None) and is_blank(float("nan")) and is_blank(" - ") and is_blank("N/A")
    assert not is_blank(0) and not is_blank("0")


def test_parse_amount_numbers_and_plus_sign():
    assert parse_amount(5) == 5.0 and parse_amount(2.5) == 2.5 and parse_amount("+12") == 12.0


def test_parse_dates_objects_blanks_and_bad_values():
    assert parse_dates([datetime(2026, 9, 4, 10), date(2026, 9, 5), "", None]) == [
        date(2026, 9, 4),
        date(2026, 9, 5),
        None,
        None,
    ]
    assert parse_dates(["not a date"]) == [None]
    assert parse_dates(["04/09/2026", "31/02/2026"]) == [date(2026, 9, 4), None]


def test_inr_lakhs_and_crores():
    assert inr(12345678.9) == "1,23,45,678.90" and inr(-1500) == "-1,500.00" and inr(100000) == "1,00,000.00"


# ---------------------------------------------------------------- reading files


def test_read_raw_from_bytes_upload_and_file_handle(tmp_path):
    assert read_raw(b"a,b\n1,2\n") == [["a", "b"], ["1", "2"]]

    class Upload:  # what Streamlit's UploadedFile looks like
        name = "orders.csv"

        def getvalue(self):
            return b"a;b\n1;2\n"

    assert read_raw(Upload()) == [["a", "b"], ["1", "2"]]
    path = tmp_path / "t.csv"
    path.write_bytes(b"a|b\n1|2\n")
    with open(path, "rb") as handle:  # has .read() but no .getvalue()
        assert read_raw(handle) == [["a", "b"], ["1", "2"]]


def test_read_raw_windows_1252_and_single_column():
    text = "Date,Narration\n01/09/2026,Caf\xe9 payout\n".encode("cp1252")
    assert read_raw(text)[1][1] == "Café payout"
    assert read_raw(b"onlyonecolumn\nvalue\n") == [["onlyonecolumn"], ["value"]]


def test_semicolon_bank_file_maps():
    loaded = load_bank(BANK_CSV.replace(b",", b";"), "bank.csv")
    assert loaded.df["amount"].tolist() == [100.0, -40.0]


def test_xlsx_with_real_date_cells(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Narration", "Debit", "Credit", "Balance"])
    ws.append([datetime(2026, 9, 1), "NEFT/RAZORPAY", None, 100, 100])
    ws.append([datetime(2026, 9, 2), "RENT", 40, None, 60])
    wb.save(tmp_path / "s.xlsx")
    loaded = load_bank(tmp_path / "s.xlsx")
    assert loaded.df["date"].tolist() == [date(2026, 9, 1), date(2026, 9, 2)]
    assert loaded.chosen.checks["balance_continuity"] == 1.0


def test_describe_lists_mapping(month):
    out, _ = month
    text = load_bank(out / "bank_format_a.csv").describe()
    assert text.startswith("[rules, score 1.00]") and "description <- 'Narration'" in text


# ---------------------------------------------------------------- header detection


def test_header_fallback_skips_text_rows_without_numbers_below():
    rows = [["title", "more", "words"], ["Tarikh", "Vivran", "Rakam"], ["01/09/2026", "x", "100"]]
    assert detect_header_row(rows, BANK) == 1


def test_header_not_found_raises():
    with pytest.raises(MappingError, match="header row"):
        detect_header_row([["just a note"], ["another"]], BANK)


# ---------------------------------------------------------------- bank mapping checks


def test_bank_without_balance_is_accepted_but_flagged():
    loaded = load_bank(b"Date,Narration,Debit,Credit\n01/09/2026,A,,100\n02/09/2026,B,40,\n", "b.csv")
    assert loaded.chosen.score == 0.9
    assert any("could not be cross-checked" in n for n in loaded.chosen.notes)


def test_bank_balance_on_one_row_only_is_treated_as_unchecked():
    loaded = load_bank(b"Date,Narration,Debit,Credit,Balance\n01/09/2026,A,,100,100\n02/09/2026,B,10,,\n", "b.csv")
    assert "balance_continuity" not in loaded.chosen.checks and loaded.chosen.score == 0.9


def test_blank_balance_cells_do_not_break_the_check():
    data = b"Date,Narration,Debit,Credit,Balance\n01/09/2026,A,,100,100\n02/09/2026,B,10,,\n03/09/2026,C,5,,85\n04/09/2026,D,,15,100\n"
    assert load_bank(data, "b.csv").chosen.checks["balance_continuity"] == 1.0


def test_amount_with_drcr_column_and_unknown_flags():
    data = (
        b"Date,Narration,Amount,Cr/Dr,Balance\n"
        b"01/09/2026,A,100,CR,100\n02/09/2026,B,40,DR,60\n03/09/2026,C,5,X,65\n04/09/2026,D,-5,,60\n"
    )
    loaded = load_bank(data, "b.csv")
    assert loaded.df["amount"].tolist() == [100.0, -40.0, 5.0, -5.0]
    assert loaded.chosen.checks["balance_continuity"] == 1.0


def test_bank_without_any_amount_column_fails():
    with pytest.raises(MappingError, match="amount"):
        load_bank(b"Date,Narration,Balance\n01/09/2026,A,100\n", "b.csv")


# ---------------------------------------------------------------- orders and report mapping


def test_order_status_normalisation():
    data = b"Order ID,Amount,Status\nA1,100,\nA2,200,Awaiting payment\nA3,300,Completed\nA4,400,Refunded\n"
    assert load_orders(data, "o.csv").df["status"].tolist() == ["paid", "pending", "paid", "cancelled"]


def test_orders_without_amount_fail():
    with pytest.raises(MappingError, match="orders"):
        load_orders(b"Order ID,Customer\nA1,x\n", "o.csv")


def test_report_without_type_fails():
    with pytest.raises(MappingError, match="settlement_report"):
        load_report(b"entity_id,amount\npay_1,100\n", "r.csv")


def test_report_without_settled_column_derives_it():
    data = (
        b"entity_id,type,amount,fee,tax,settlement_id,settlement_utr,settled_at\n"
        b"pay_1,payment,100,2,0.36,setl_1,AXISN26245000001,03/09/2026\npay_2,payment,50,1,0.18,,,\n"
    )
    frame = load_report(data, "r.csv").df
    assert frame["settled"].tolist() == [True, False]
    assert frame["credit"].tolist() == [97.64, 48.82]


# ---------------------------------------------------------------- LLM mapping behaviour


def test_llm_error_falls_back_to_rules_with_a_note(month):
    out, _ = month
    loaded = load_bank(out / "bank_format_a.csv", client=Client(error=LLMError("down")), mode="llm")
    assert loaded.chosen.source == "rules"
    assert any("LLM mapping unavailable" in n for n in loaded.chosen.notes)


def test_llm_invalid_json_falls_back_to_rules(month):
    out, _ = month
    loaded = load_bank(out / "bank_format_a.csv", client=Client(reply="{not: valid json}"), mode="llm")
    assert loaded.chosen.source == "rules"
    assert any("LLM mapping unavailable" in n for n in loaded.chosen.notes)


def test_llm_mapping_drops_unknown_and_repeated_headers():
    reply = '{"date": "Date", "value_date": "Date", "description": "Not a header", "credit": 5}'
    assert llm_mapping(["Date", "Narration"], [], BANK, Client(reply=reply)) == {"date": "Date"}


def test_rules_mode_never_calls_the_llm(month):
    out, _ = month
    client = Client(reply="{}")
    with pytest.raises(MappingError):
        load_bank(out / "bank_format_d.csv", client=client, mode="rules")
    assert client.calls == 0


def test_mapping_error_without_client_suggests_api_key_but_not_with_one(month):
    out, _ = month
    with pytest.raises(MappingError) as exc:
        load_bank(out / "bank_format_d.csv", client=Client(reply="{}"))
    assert "GROQ_API_KEY" not in str(exc.value)


def test_read_raw_accepts_bytesio_with_name():
    buffer = io.BytesIO(BANK_CSV)
    buffer.name = "bank.csv"
    assert load_bank(buffer).df["amount"].tolist() == [100.0, -40.0]


def test_header_only_export_gets_a_clear_message():
    with pytest.raises(MappingError, match="no rows"):
        load_report(b"entity_id,type,amount,settlement_id\n\n", "r.csv")


def test_utr_extraction_ignores_run_together_words():
    from recon.parse import extract_utr_candidates

    text = "NEFT CR-RAZORPAYSOFTWAREPVT-FIXLYHOMESERVICESLTD-AXISN26247123456"
    assert extract_utr_candidates(text) == ["AXISN26247123456"]

"""The real HTTP LLM client (against a local fake server), client selection, and the report layer."""

import pytest

from recon import reconcile
from recon.ingest import load_bank, load_orders, load_report
from recon.llm import LLMError, OpenAICompatClient, get_client, parse_json_object
from recon.report import llm_summary, template_summary, to_html


# ---------------------------------------------------------------- choosing a provider


def test_no_key_means_no_client():
    assert get_client() is None


def test_groq_key_uses_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    c = get_client()
    assert (c.base_url, c.model, c.api_key) == ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "g")


def test_openai_key_alone_uses_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    c = get_client()
    assert (c.base_url, c.model) == ("https://api.openai.com/v1", "gpt-4o-mini")


def test_groq_wins_over_openai_when_both_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert get_client().base_url == "https://api.groq.com/openai/v1"


def test_generic_key_with_custom_endpoint(monkeypatch):
    monkeypatch.setenv("RECON_LLM_API_KEY", "r")
    monkeypatch.setenv("RECON_LLM_BASE_URL", "http://localhost:1234/v1/")
    monkeypatch.setenv("RECON_LLM_MODEL", "my-model")
    c = get_client()
    assert (c.base_url, c.model, c.api_key) == ("http://localhost:1234/v1", "my-model", "r")


# ---------------------------------------------------------------- the HTTP client


def test_chat_sends_auth_model_and_json_mode(llm_server):
    client = get_client()
    reply = client.chat("map spreadsheet columns", 'Column headers (exact strings):\n["Date"]\n\nrest', json_mode=True)
    assert reply == "{}"
    request = llm_server.requests[-1]
    assert request["headers"]["Authorization"] == "Bearer test-key"
    assert request["body"]["model"] == "fake-model" and request["body"]["temperature"] == 0
    assert request["body"]["response_format"] == {"type": "json_object"}


def test_chat_without_json_mode_omits_response_format(llm_server):
    get_client().chat("summary", '{"stats": {"at_risk_high": 5}}')
    assert "response_format" not in llm_server.requests[-1]["body"]


@pytest.mark.parametrize("mode", ["http_error", "not_json", "bad_shape"])
def test_chat_failures_raise_llm_error(llm_server, mode):
    llm_server.mode = mode
    with pytest.raises(LLMError):
        get_client().chat("s", "{}")


def test_unreachable_server_raises_llm_error():
    client = OpenAICompatClient("k", "http://127.0.0.1:9/v1", "m", timeout=2)
    with pytest.raises(LLMError, match="LLM call failed"):
        client.chat("s", "u")


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here is the mapping: {"a": 1} hope that helps', {"a": 1}),
    ],
)
def test_parse_json_object_tolerates_wrappers(text, expected):
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text", ["no json here", "[1, 2]"])
def test_parse_json_object_rejects_non_objects(text):
    with pytest.raises(LLMError):
        parse_json_object(text)


def test_hindi_statement_mapped_through_real_http_client(llm_server, month):
    out, _ = month
    loaded = load_bank(out / "bank_format_d.csv", client=get_client())
    assert loaded.chosen.source == "llm" and loaded.chosen.checks["balance_continuity"] == 1.0


# ---------------------------------------------------------------- summary and HTML


def _result(month, with_bank=True):
    out, _ = month
    bank = load_bank(out / "bank_format_a.csv").df if with_bank else None
    return reconcile(load_report(out / "settlement_report.csv").df, bank, load_orders(out / "orders.csv").df)


class Reply:
    model = "stub"

    def __init__(self, text=None, error=None):
        self.text, self.error = text, error

    def chat(self, system, user, json_mode=False):
        if self.error:
            raise self.error
        return self.text


def test_llm_summary_through_real_client_is_kept(llm_server, month):
    text, used = llm_summary(_result(month), get_client())
    assert used and text.endswith("needs action now.")


def test_llm_summary_falls_back_on_error_and_on_empty_reply(month):
    result = _result(month)
    assert llm_summary(result, Reply(error=LLMError("down"))) == (template_summary(result), False)
    assert llm_summary(result, Reply(text="   ")) == (template_summary(result), False)


def test_llm_summary_without_bank_handles_missing_dates(month):
    result = _result(month, with_bank=False)
    assert result.stats["statement_from"] is None
    text, used = llm_summary(result, Reply(text=f"{len(result.exceptions)} issues need a look."))
    assert used


def test_all_clear_summary_and_html(month):
    out, _ = month
    report = load_report(out / "settlement_report.csv").df
    clean = report[report["type"] == "payment"].head(0)
    result = reconcile(clean, load_bank(out / "bank_format_a.csv").df.iloc[0:0])
    assert template_summary(result).startswith("Nothing looks wrong.")
    page = to_html(result, "All clear.", ["bank: no usable balance column"])
    assert "Nothing to fix." in page and "no usable balance column" in page
    assert "no bank statement uploaded" in page


def test_html_escapes_text_and_shows_every_issue(month):
    result = _result(month)
    page = to_html(result, "<script>x</script>", title="Sept & Oct")
    assert "&lt;script&gt;" in page and "Sept &amp; Oct." in page
    assert all(e.key in page for e in result.exceptions)
    assert page.count('class="rc-group') == 3

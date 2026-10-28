<p align="center"><img src="docs/banner.png" alt="Recon Agent: Razorpay says it paid you. Did all of it reach your bank?" width="100%"></p>

<p align="center">
  <a href="https://recon-agent-jayanth.streamlit.app"><b>Try it live</b></a> &nbsp;·&nbsp;
  <a href="#how-it-works">How it works</a> &nbsp;·&nbsp;
  <a href="#does-it-actually-work">Does it work?</a> &nbsp;·&nbsp;
  <a href="#run-it-yourself">Run it yourself</a>
</p>

Razorpay says it paid you. Your bank says what actually arrived.

Nobody checks if those two agree.

It's not laziness. Razorpay settles a day or two after each sale. Fee and GST come out, refunds get
netted off, and one lump lands per day. Every bank exports its statement differently. Narrations
get cut off before the UTR. A day with more refunds than sales pays nothing - and quietly shrinks
the next payout.

So the check happens in Excel, if it happens at all. Two files side by side, an afternoon gone. And
a missing ₹15,000 can still slip through between a hundred UPI debits.

I built Recon Agent to do that check in a few seconds.

You give it three exports: the Razorpay settlement report, your bank statement for the same dates,
and your own orders if you have them. It gives back a short list of what's off, biggest money first,
with what to do about each one.

<img src="docs/app.png" alt="Results page: four totals, a short summary, then issues grouped by priority with a next step for each" width="100%">

## What it catches

- Payouts Razorpay says it sent that never reached your bank
- Payouts that came in short (or, once in a while, higher than expected)
- Payments captured but still not settled days later
- Fees above your plan's rate, and GST that isn't 18% of the fee
- Customers charged twice for the same order
- Cancelled orders where nobody refunded the money
- Orders marked paid with no payment behind them, and payments with no order
- Razorpay money in your bank that isn't in the report at all

## How it works

The maths is the easy part. The files are the hard part.

**Reading the files.** Narration, Particulars, Transaction Remarks. Title rows above the header.
Amounts written as "1,23,456.00 Cr". Newest first, oldest first. No two banks agree.

So the reader tries the obvious thing first - match column names against the usual ones. When that
doesn't work, say an unfamiliar bank or headers in Hindi, an LLM looks at the headers and a few rows
and says which column is which.

Neither guess is trusted. A mapping is only accepted if the previous balance plus each row's amount
equals that row's balance, all the way down. Swap debit and credit by mistake and the same check
catches it - and flips them back.

**Matching payouts.** UTR first. If the bank cut the narration short, exact amount within a few days.
If that fails too, the closest leftover amounts get paired. A payout that came in ₹500 short shows up
as one short payout - not as one missing payout plus one mystery credit.

When refunds beat a day's sales, Razorpay pays nothing that day and takes the difference from the
next one. That's handled too. It was also the first thing that broke.

**The rest is plain rules.** Fees against your rate card. GST against the fee. Settlement against
T+2. Orders against payments.

**Where the AI stops.** I didn't want an LLM anywhere near the money. It reads file layouts and it
can rewrite the summary in friendlier words. That's it. If the summary has a single number that isn't
in the computed results, it gets thrown away and a plain template takes its place.

Money is the one place a made-up digit isn't acceptable.

## Does it actually work?

On synthetic data, yes. On real data, I don't know yet.

Each test month has about 320 orders with 22 problems planted in it, run against three bank layouts,
across 30 months.

| | Precision | Recall |
|---|---|---|
| Clean data | 100% | 100% |
| Messy data: payouts posted up to 3 days late, 30% of narrations cut off | 95.9% | 99.2% |

The clean number doesn't mean much. I wrote the generator and the checker, so of course they agree.

The messy number is the one I'd trust. It started at 89.3% precision. Reading every false alarm,
one by one, is what got it up - the late-posting window, the closest-amount pairing and the refund
carry-forward all came from that. Most of what's left are payouts that land after the statement
closes, and the app already says those will likely show up next month.

Real exports are the actual test. That's next. Full tables are in [eval/RESULTS.md](eval/RESULTS.md).

## Run it yourself

```bash
git clone https://github.com/codeMaster60/recon-agent
cd recon-agent
pip install -r requirements.txt
streamlit run app.py
```

No files of your own? Click "Try a sample month". There's a command line version too:

```bash
python -m recon --report data/samples/settlement_report.csv \
                --bank data/samples/bank_format_b.xlsx \
                --orders data/samples/orders.csv --out out/
```

The AI step is optional. Without a key everything runs on rules - you only lose unusual layouts like
the Hindi sample. To switch it on, get a free key from [Groq](https://console.groq.com) and set
`GROQ_API_KEY`. Any OpenAI-compatible API works through `RECON_LLM_API_KEY`, `RECON_LLM_BASE_URL`
and `RECON_LLM_MODEL`.

The default fee rates (2% for everything) are placeholders. Put in your real plan in the app, or
pass `--rate-card rates.json` on the command line.

## Tests

```bash
pip install -r requirements-dev.txt
pytest --cov
```

The run fails if line or branch coverage drops below 100%. That includes the web app itself, driven
through Streamlit's test harness with real file uploads, and the LLM client, tested against a small
fake server so no key is needed.

But 100% coverage only proves every line ran. Not that the tests would notice a mistake.

So there's a second check. `python tests/mutation_check.py` plants 20 realistic bugs, one at a
time - the wrong GST rate, dates read month-first, refunds ignored in the double-charge check, the
AI allowed to invent numbers - and confirms the tests catch every one. Writing it turned up gaps I
didn't know I had.

CI runs everything on Python 3.10, 3.12 and 3.13. Running more than one version found a real bug:
on pandas 2.x, a report column that was entirely blank came through as text and crashed the app.

## What's in here

```
app.py             the web app
recon/ingest.py    reading files, finding the header row, column mapping, the balance check
recon/engine.py    payout matching and every check
recon/report.py    the summary and the downloadable report
recon/look.py      styling shared by the app and the report
recon/llm.py       a small client for any OpenAI-compatible API, standard library only
data/generate.py   builds a synthetic month with known problems, in four bank layouts
eval/run_eval.py   precision and recall per problem type
tests/             unit, integration and app tests, plus the planted-bug check
```

## Not done yet

- It hasn't seen real merchant exports. That's the next step.
- One settlement is matched to one bank credit. Banks that batch several payouts into one credit
  aren't handled.
- No PDF statements. Download CSV or Excel from net banking instead.
- Nothing is stored and there are no accounts, so no month-on-month history.

---

Built by [Sai Jayanth](https://www.linkedin.com/in/asaijayanth), with an AI pair programmer.
Set in IBM Plex, under the SIL Open Font License - the licences are in `static/fonts`.

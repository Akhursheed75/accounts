# Reconcilia

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

Daily shop accounting, bank statement processing and automatic payment
reconciliation for a business with several shops and several banks, operating in
two currencies.

The question the system exists to answer, quickly and without a spreadsheet:

> The shops say they banked this money. Did the bank receive it?

---

## Contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [Requirements](#requirements)
4. [Running it locally](#running-it-locally)
5. [Environment variables](#environment-variables)
6. [Database and migrations](#database-and-migrations)
7. [Seed and demo data](#seed-and-demo-data)
8. [How PDF processing works](#how-pdf-processing-works)
9. [Adding a new bank parser](#adding-a-new-bank-parser)
10. [How reconciliation works](#how-reconciliation-works)
11. [Running the tests](#running-the-tests)
12. [Deploying with Docker](#deploying-with-docker)
13. [Working with GitHub](#working-with-github)
14. [What is kept out of git](#what-is-kept-out-of-git)
15. [Backups](#backups)
16. [Security notes](#security-notes)
17. [What is deliberately not built yet](#what-is-deliberately-not-built-yet)

---

## What it does

**Daily accounting.** Each shop records one sheet per day: bales, sales,
invoices, expenses, opening and closing balances, notes, and every deposit made
into a bank. A bank can appear many times in one day, because that is what
happens.

**Bank statements.** An administrator uploads the PDF a bank produced. The
system stores the original, extracts the transactions, and reports honestly when
it cannot.

**Reconciliation.** Every shop deposit is compared with the extracted bank
transactions and comes out as **matched**, **possible** or **unmatched**. The
reasoning is shown, not hidden behind a number.

**Exceptions.** Two lists that are the point of the whole exercise: money the
shops banked that the bank has no record of, and money the bank received that no
shop claimed.

**Reports, dashboard, audit log.** Ten reports, exportable to Excel and PDF; an
administrator-only dashboard; and a record of every financial action with who
did it, when, and what changed.

### Two rules that run through everything

**Currencies are never combined.** USD and cordobas are reported side by side
and never summed. `$480` can never match `C$480`. There is no exchange rate
anywhere in the code, because a wrong one would be worse than none.

**Nothing is silently lost or silently invented.** A statement line the parser
cannot read leaves the statement `PARTIALLY_PROCESSED` with the reason attached.
A bank with no parser says so instead of guessing. Two equally good candidates
are both offered rather than one being picked.

---

## Architecture

```
                     ┌──────────────┐
  browser  ────────▶ │  nginx :80   │
                     └──────┬───────┘
                    /api/*  │  everything else
                 ┌──────────┴───────────┐
                 ▼                      ▼
        ┌─────────────────┐    ┌──────────────────┐
        │  FastAPI (api)  │    │  Next.js (web)   │
        │  Python 3.12    │    │  React 19 + TS   │
        └────────┬────────┘    └──────────────────┘
                 │
     ┌───────────┼────────────────┐
     ▼           ▼                ▼
┌──────────┐ ┌────────────┐ ┌──────────────┐
│PostgreSQL│ │ statements │ │ worker       │
│    16    │ │  (volume)  │ │ PDF + OCR    │
└──────────┘ └────────────┘ └──────────────┘
```

**Why a worker.** OCR on a statement takes seconds to minutes — far longer than
an HTTP request should live. Uploads therefore queue a job and return
immediately; the worker picks it up. The queue is a Postgres table claimed with
`SELECT … FOR UPDATE SKIP LOCKED`, which gives at-least-once delivery and
horizontal scaling (run more workers) without adding Redis or Celery to a system
that has to be maintained by whoever inherits it.

### Layout

```
backend/
  app/
    api/v1/          one router per module
    core/            config, security, permissions, dependencies, errors
    db/              engine, session, declarative base
    models/          SQLAlchemy models — the schema lives here
    parsers/         one parser per bank + the shared layout machinery
    schemas/         Pydantic request and response models
    services/        accounting maths, reconciliation engine, reports, storage, jobs
    worker.py        the background worker
    seed.py          reference data, first admin, demo data
  alembic/versions/  migrations
  tests/             80 tests, including the real bank PDFs
frontend/
  src/app/           one directory per screen
  src/components/    shell, shared UI, record form, transaction table
  src/lib/           API client, auth context, types, formatting
nginx/               reverse-proxy configuration
samples/             real statement PDFs used to build and test the parsers
```

### Database

Twenty-two tables, fully normalised. The ones that carry the guarantees:

| Table | What it protects |
|---|---|
| `shop_daily_records` | partial unique index on (shop, date) **where not archived** — one live sheet per shop per day, while archived ones are kept |
| `shop_transfers` | `amount > 0`; soft-deleted, never removed |
| `bank_transactions` | unique (account, `dedupe_hash`) — re-uploading an overlapping period adds only what is new |
| `bank_statements` | unique (account, `file_hash`) — the same file cannot be uploaded twice |
| `reconciliation_matches` | two partial unique indexes: **one active confirmed match per bank transaction, and one per shop payment**. This is enforced by Postgres, not by application code, and there is a test that bypasses the API to prove it |
| `audit_logs` | user, action, module, record, before, after, IP, timestamp |

Money is `NUMERIC(18,2)` throughout and `Decimal` in Python. No floats touch a
financial value anywhere.

---

## Requirements

**With Docker (recommended):** Docker 24+ with the Compose plugin. Nothing else.

**Without Docker:** Python 3.12, Node 22, PostgreSQL 16, `poppler-utils`,
`tesseract-ocr` with the `spa` and `eng` language packs.

---

## Running it locally

```bash
git clone <this repository> reconcilia && cd reconcilia
cp .env.example .env
# Edit .env: set SECRET_KEY, POSTGRES_PASSWORD and ADMIN_PASSWORD.
#   openssl rand -hex 32
docker compose up -d --build
docker compose exec api python -m app.seed --demo
```

Then open <http://localhost> and sign in with the `ADMIN_EMAIL` and
`ADMIN_PASSWORD` from your `.env`.

<details>
<summary>Running the pieces directly, without Docker</summary>

```bash
# database
createdb reconcilia

# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env      # set DATABASE_URL to your local database
alembic upgrade head
python -m app.seed --demo --with-statements
uvicorn app.main:app --reload --port 8000

# worker, in a second terminal
python -m app.worker

# frontend, in a third
cd ../frontend
npm install
npm run dev                  # http://localhost:3000
```

The frontend proxies `/api/*` to `API_URL` (default `http://127.0.0.1:8000`), so
the browser only ever talks to one origin and the session cookie works with no
CORS exception.
</details>

---

## Environment variables

Set in `.env` at the repository root; `docker-compose.yml` passes them through.

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `reconcilia` | **Required.** The password has no default on purpose. |
| `SECRET_KEY` | — | **Required.** Signs session tokens. `openssl rand -hex 32`. Changing it signs everyone out. |
| `ENVIRONMENT` | `production` | Free text, shown on `/api/health`. |
| `COOKIE_SECURE` | `false` | **Set to `true` once HTTPS is in place.** |
| `COOKIE_SAMESITE` | `lax` | |
| `CORS_ORIGINS` | `http://localhost` | Comma-separated. Only needed if a browser calls the API from another origin. |
| `HTTP_PORT` | `80` | Host port nginx binds to. |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MB) | Also raise `client_max_body_size` in `nginx/reconcilia.conf` if you increase it. |
| `OCR_DPI` | `300` | Lower is faster and less accurate. 300 reads these statements perfectly. |
| `OCR_LANGUAGES` | `spa+eng` | |
| `DEFAULT_DATE_WINDOW_DAYS` | `3` | Initial value only; afterwards it is edited in Settings. |
| `ADMIN_EMAIL` / `ADMIN_NAME` / `ADMIN_PASSWORD` | — | Used once, by `python -m app.seed`. |

---

## Database and migrations

Alembic, from `backend/`:

```bash
alembic upgrade head                              # apply (the api container does this on start)
alembic revision --autogenerate -m "what changed" # after editing a model
alembic downgrade -1                              # step back one
alembic history                                   # what exists
```

Autogenerate compares `app/models/` with the live database, so a model change is
the source of a migration — never the other way round. **Read the generated file
before applying it.**

---

## Seed and demo data

```bash
docker compose exec api python -m app.seed
```

Creates every permission and the three built-in roles, both currencies, three
cities, three shops (`Shop 1`–`Shop 3`, renameable in Settings), four banks with
their accounts, the two bale types, and the first administrator. It is safe to
run repeatedly — everything is looked up before it is created.

```bash
docker compose exec api python -m app.seed --demo --with-statements
```

Adds three shop users, four daily sheets and, with `--with-statements`, loads
the PDFs in `samples/` and runs matching. The demo is chosen to show every
outcome rather than a happy path: eleven payments match, one is deliberately
missing from the bank, and one has two equally good candidates and is therefore
**not** matched automatically. Demo rows are flagged `is_demo` and labelled in
the interface.

Sign-in details are printed by the command.

---

## How PDF processing works

```
upload ─▶ validate ─▶ store original ─▶ queue job ─▶ worker
                                                       │
                              text layer? ─────────────┤
                                   yes                 no
                                    │                  │
                            extract words        render 300 dpi
                            with positions       → Tesseract
                                    └────────┬─────────┘
                                             ▼
                                    bank-specific parser
                                             ▼
                                normalised transactions
                                             ▼
                            running-balance cross-check
                                             ▼
                             de-duplicate ─▶ store ─▶ match
```

**Text or image?** A page yielding fewer than 40 characters is treated as having
no usable text and goes to OCR. BAC's statements land at zero: they are produced
by "Microsoft: Print To PDF" with *no embedded fonts at all*, so the text is
drawn as vector outlines and looks perfect on screen while `pdftotext` returns
nothing.

**Columns are learned, not assumed.** A header row seeds the columns; the real
boundaries come from the body text. This matters: LAFISE's description text
starts to the *left* of the word "Description", while BANPRO's runs far to the
right of "Descripción" and, with naïve header-position logic, lands in the
amount column — which would turn a description into a payment.

**The running balance is a free checksum.** Every bank prints the balance after
each movement, so a row's amount and direction must move the balance by exactly
that amount. This catches a mis-assigned debit/credit column and, on OCR'd
statements, a misread digit. Rows the chain confirms are marked at 97%
confidence; rows it cannot vouch for are flagged in the interface.

**Statuses.** `UPLOADED → PROCESSING → PROCESSED` / `PARTIALLY_PROCESSED` /
`FAILED`. A line that looked like a transaction but could not be read makes the
statement partial and is quoted in the warnings — it is never dropped quietly.

### What each bank actually needs

| Bank | Extraction | Notes |
|---|---|---|
| **LAFISE** | Text | Date / Confirmation / Description / Debit / Credit / Balance / Reference / Movement type. Date and description both wrap onto extra lines. Rows print newest first. |
| **BANPRO** | Text | A browser print with only Fechas / Descripción / Monto. No debit-credit split and no balance, so direction cannot be verified from the document and the parser says so. Currency is on the amount (`C$` / `$`), which lets it refuse a file uploaded to the wrong account. |
| **BAC** | **OCR** | No embedded fonts. Rendered at 300 dpi and read by Tesseract, then every amount is checked against the running balance. The account number and currency are read from the header and compared with the selected account. |
| **FICOHSA** | — | **No parser yet**, because no FICOHSA statement has been supplied. Uploads are stored and refused with an explanation. See below. |

---

## Adding a new bank parser

1. Put a real statement in `samples/`.
2. Look at what is actually there:

   ```bash
   cd backend
   python -c "
   from app.parsers.document import PdfDocument
   d = PdfDocument(open('../samples/YOURFILE.pdf','rb').read())
   print('pages', d.page_count, 'text layer:', d.has_text_layer)
   print(d.text[:2000] if d.has_text_layer else d.ocr_page(0)[:2000])
   for w in d.words(0)[:60]: print(round(w.x0), round(w.x1), round(w.top), w.text)
   "
   ```
3. Copy `app/parsers/lafise.py` (text) or `app/parsers/bac.py` (OCR) and adjust.
   Use `find_header`, `ColumnMap` and `cluster_rows` from `app/parsers/layout.py`
   rather than splitting strings on whitespace.
4. Register the class in `app/parsers/registry.py`.
5. Add a test in `tests/test_parsers.py` that asserts the **exact** transactions
   from that file — count, amounts, dates, references.
6. Point the bank at it: Settings → Banks → parser, or `parser_key` in the
   database.

The output shape every parser produces:

```python
NormalizedTransaction(
    txn_date, value_date, description, reference, external_id,
    amount, currency_code, direction,        # CREDIT | DEBIT
    debit, credit, running_balance, movement_type,
    page_number, row_index, raw_text, confidence, chain_verified,
)
```

Nothing outside `app/parsers/` knows how any particular bank formats anything.

---

## How reconciliation works

Three things are **hard requirements**, never traded against a good score:

- **Currency** must be identical.
- **Bank** must be identical (and the account, if the sheet named one).
- **Amount** must be within the configured tolerance, which defaults to zero.

Only the date is allowed to be approximate, because a deposit made at 5pm can
land on the next banking day. Outgoing transactions are excluded by default.

Anything that survives those filters is scored:

| Signal | Points |
|---|---|
| Amount exact | 50 |
| Amount within tolerance | 38 |
| Same bank | 15 |
| Same date | 30 |
| One day apart | 22 |
| Two days apart | 16 |
| Within the window | 10 |
| Reference appears on the bank line | +10 |
| Note appears in the description | +5 |

Exact amount + same bank + same date = **95**, the default automatic threshold.
One day apart gives 87 — a suggestion, not a decision. Below the suggestion
threshold (60) nothing is offered at all.

**Ambiguity stops the machine.** If two or more candidates reach the automatic
threshold, nothing is matched and both are offered. Two identical deposits on
one day are ordinary; picking one at random would reconcile the wrong money and
the mistake would be invisible. The demo data contains exactly this case.

Every match carries its reasoning, shown in the interface as *"Amount matches
exactly (+50) · Same bank (+15) · Same date (+30)"*.

**Manual matching** is always available, with a reason that goes into the audit
log. It still refuses a currency mismatch and still refuses a transaction that
is already reconciled.

**Unmatching keeps the history.** The row is deactivated, not deleted, with who
undid it and why. Both sides become available again.

Thresholds, the date window and the amount tolerance are edited in
**Settings → Matching rules**.

---

## Running the tests

```bash
cd backend
createdb reconcilia_test          # or: docker compose exec db createdb -U reconcilia reconcilia_test
DATABASE_URL=postgresql+psycopg://reconcilia:reconcilia@localhost:5432/reconcilia_test \
  python -m pytest
```

80 tests against a real PostgreSQL — not SQLite, because the partial unique
indexes that make double-matching impossible are a Postgres feature and the
tests must exercise the thing that actually runs.

What they cover: authentication and session invalidation; per-shop
authorisation; the parsers, run against the real bank PDFs and asserting exact
amounts; upload validation, duplicate files and duplicate lines; every matching
edge case in the specification — same amount in another currency, a thousand
times the amount, the wrong bank, a one-day gap, a date far outside the window,
two identical candidates, an already-matched transaction; manual matching and
unmatching; the database-level guarantee, tested by bypassing the API entirely;
all ten reports plus the Excel and PDF exports; the job queue, including a job
with no handler and a worker that died mid-job.

Frontend:

```bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

---

## Deploying with Docker

### The short way — one script, run on the server

```bash
# on your own computer
scp reconcilia.tar.gz root@your-server-ip:/root/

# on the server
ssh root@your-server-ip
tar xzf reconcilia.tar.gz && cd reconcilia
./server-setup.sh
```

`server-setup.sh` adds swap if memory is tight (a 1 GB droplet cannot compile
the frontend without it, and fails with a bare "Killed"), installs Docker if it
is missing, generates a `.env` with fresh random secrets, builds, starts, runs
the migrations, seeds the reference data, **signs in once to prove the account
works**, and prints the address and credentials.

It is safe to run again: it never overwrites an existing `.env` and never
touches the database volume. `--demo` also loads the sample statements and demo
sheets; `--update` rebuilds after a code change.

### The alternative — push from your own machine

```bash
cp .env.example .env    # fill in every CHANGE_ME
./deploy.sh root@your-server-ip
```

`deploy.sh` refuses to run while `.env` still contains placeholders, rsyncs the
project to `/opt/reconcilia`, builds and starts the stack, waits for the API,
and runs the seed. Use this one when you want to keep editing the code locally
and redeploy repeatedly.

On the server afterwards:

```bash
cd /opt/reconcilia
docker compose logs -f api worker
docker compose ps
docker compose exec api python -m app.seed --demo   # optional demo data
docker compose restart api
docker compose down                                 # data survives in named volumes
```

### Putting HTTPS in front of it

One command, once an A record points your domain at the server:

```bash
sudo ./enable-https.sh account.example.com you@example.com
```

It checks that the domain really resolves to this machine (Let's Encrypt
rate-limits failures, so guessing is expensive), adds Caddy to the stack to
obtain and renew the certificate, moves nginx onto `127.0.0.1:8080` so the
application can no longer be reached unencrypted, sets `COOKIE_SECURE=true` and
`CORS_ORIGINS`, and then proves it worked by fetching `/api/health` over HTTPS.

If any of that fails it restores the previous configuration rather than leaving
a half-configured site. Everything it changed is backed up into a
`.https-backup-*` directory, and the exact commands to undo it are printed at
the end.

Until this is done, session cookies travel in clear text over the network.

---

## Working with GitHub

### What runs on every push

`.github/workflows/ci.yml` runs four jobs on every push to `main` and every pull
request:

| Job | What it checks |
|---|---|
| **Backend tests** | The full pytest suite against a real PostgreSQL 16, plus `alembic check` — a model changed without a migration fails here rather than at 3am on the server. |
| **Frontend build** | TypeScript, ESLint and a production build. |
| **Docker configuration** | `docker compose config` on the committed Compose file. |
| **Shell scripts** | ShellCheck over every `.sh` in the repository. |

The parser tests read the real statements in `samples/`, which are not in this
repository (see Security below). They **skip** in CI and run on a machine that
has the files; the job summary says so on every run.

### Deploying

Deployment is a button, not a side effect of pushing. **Actions → Deploy → Run
workflow**, type `deploy` in the confirmation box, and it will:

1. run the whole CI suite again and stop if anything fails;
2. rsync the repository to the server, leaving `.env`, the uploaded statements,
   `samples/` and the database volume alone;
3. rebuild the images and restart the stack;
4. poll `/api/health` from inside the server and fail the run if it does not
   come back.

Nothing in a deployment touches your data. The database lives in a named Docker
volume, and everything machine-specific is excluded from the copy.

### Secrets to set

**Settings → Secrets and variables → Actions**:

| Secret | Value | Required |
|---|---|---|
| `SSH_HOST` | The server's address or IP | yes |
| `SSH_USER` | The user to connect as, e.g. `root` | yes |
| `SSH_PRIVATE_KEY` | A private key whose public half is in the server's `~/.ssh/authorized_keys` | yes |
| `KNOWN_HOSTS` | Output of `ssh-keyscan your-server`. Without it the first connection trusts whatever answers. | strongly recommended |
| `SSH_PORT` | Defaults to `22` | no |
| `REMOTE_DIR` | Defaults to `/root/reconcilia` | no |

Generate a key that exists only for deployments, rather than reusing your own:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f deploy_key -N ""
ssh-copy-id -i deploy_key.pub root@your-server      # or paste into authorized_keys
cat deploy_key                                       # → the SSH_PRIVATE_KEY secret
ssh-keyscan your-server                              # → the KNOWN_HOSTS secret
rm deploy_key deploy_key.pub                         # keep no copy on your laptop
```

For an extra gate, add a `production` environment under **Settings →
Environments** and give it required reviewers. The deploy job already targets
it, so it will then wait for an approval.

---

## What is kept out of git

**`samples/` is not in this repository, on purpose.** It holds real exports from
BAC, LAFISE and BANPRO with real account numbers and the names of people who
paid the business. `.gitignore` excludes them, and the parser tests skip when
they are absent so a clean checkout still runs. Keep the files on the machines
that need them and nowhere else.

**Keep this repository private.** Beyond the code, `docs/Reconcilia-User-Manual.pdf`
is illustrated with screenshots of the running system carrying real transaction
descriptions and customer names. If this repository is ever made public, the
manual has to be removed or rebuilt against invented data — deleting `samples/`
alone is not enough.

`.env` is excluded too. It is the key to every account and every record; it
belongs on the server and in your password manager, not in git.

## Backups

```bash
cd /opt/reconcilia && ./backup.sh
```

Writes a compressed `pg_dump` and a tar of the stored statement PDFs into
`./backups`. Both are needed: the database without the PDFs loses the evidence
behind every extracted transaction. A backup nobody has restored is a guess —
restore one into a scratch stack before you rely on it.

---

## Security notes

- Passwords are hashed with **Argon2id**. Changing a password bumps a token
  version that invalidates every session already issued for that account.
- Sessions are JWTs in **httpOnly** cookies; a short access token is refreshed
  from a longer-lived refresh token. Cookies are never readable from JavaScript.
- Permissions are rows in the database, checked per endpoint. A shop user is
  scoped to their assigned shops on **every** query, not merely hidden from the
  navigation — there is a test that tries to read another shop's sheet directly.
- Uploads are checked by their **bytes**, not the content type the browser
  claimed. Files are stored under a generated key; the original filename never
  becomes a path, and files are served by id through an authorised endpoint.
- The database is not published to the host; only the application containers
  reach it.
- Errors shown to users are written for people. Stack traces stay in the server
  log with a request id.
- Financial records are archived, never deleted, and every change is audited
  with its before and after values.

**Before going live:** change every password in `.env`, put HTTPS in front,
set `COOKIE_SECURE=true`, and change the seeded administrator password.

---

## What is deliberately not built yet

The architecture allows for these; none of them are pretended at:

- **FICOHSA statement parsing** — needs one real statement.
- **Currency conversion.** Matching is currency-specific by design. A conversion
  feature would need a rate source and a policy for which day's rate applies;
  guessing would be worse than the current refusal.
- Bank API integration, automatic email import, WhatsApp, receipt scanning,
  S3 storage (the `StorageBackend` interface is the seam), multi-company.


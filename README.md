# Signals

A local dashboard of SEC insider trades (Forms 3/4/5), planned insider sales (Form 144), 5%+ stakes (Schedules 13D/13G) and fund holdings (Form 13F) since 2016. It keeps each insider's and fund's track record, measured from both the trade date and the filing date.

> Data from SEC EDGAR. Not investment advice.

## What you need

- Docker Desktop, running.
- About 25 GB of free disk for the 10-year backfill.
- An SEC contact for the User-Agent (SEC requires it): your name and email.
- Optional: a free Alpaca account key and secret for prices (otherwise yfinance is used), and a free OpenFIGI API key (faster mapping of 13F holdings to tickers).

## Setup

```bash
cp .env.example .env              # then fill in SEC_USER_AGENT (and Alpaca keys if you have them)
docker compose up -d --build      # db, migrate, api, worker, web
```

Open **http://localhost:5173**. The API is on http://localhost:8000 (docs at `/api/docs`).

## Load history (the backfill)

The dashboard starts empty. Start the full backfill once:

```bash
docker compose exec worker signals jobs request backfill_all
```

It loads the SEC bulk data sets since 2016, fetches newer filings one by one within SEC's rate limit, loads prices, and runs analytics. The first run takes hours (the per-filing part alone is about 9 hours), so leave it running overnight. It picks up where it left off after a restart. Progress shows on the **Health** page.

After the backfill, the worker keeps everything current by itself:
- It polls the SEC live feed every minute from 06:00 to 22:00 ET on business days.
- It reconciles against SEC's daily index every morning.
- It loads prices after the close.
- It recomputes analytics nightly.

Live updates only happen while your Mac is awake and Docker is running.

## Development

See `CLAUDE.md` for the architecture, rules and commands. On macOS, run `bash scripts/setup-venv.sh` before using `uv` in `backend/`.

## Dashboard pages

- **Feed:** filter new filings, inspect trade direction and badges, and open the SEC original.
- **Insider:** decisions, every transaction row, holdings, Form 144 notices, returns and confidence. Returns default to the filing time; switch to the trade basis for comparison.
- **Company:** insider activity, institutional holdings by quarter, ownership stakes and planned sales. Historical ticker aliases resolve to the same CIK.
- **Fund:** holdings, new/add/trim/exit changes and tracked-fund copycat performance. Fund rating metrics use quarterly excess returns.
- **Screener:** filter insider or fund profiles and sort every displayed column. CSV exports the endpoint's current page, with the selected filters.
- **Compare:** overlay up to four insider/fund profiles on the same basis and compare windows and allocations.
- **Watchlists:** create named lists, remove watched entities and read their activity. Profile Watch buttons add to the first list.
- **Health:** job errors, SEC pauses, parse failures, checkpoint progress, coverage and acceptance-to-feed delays.

Use the search button or ⌘K/Ctrl+K to find companies, insiders and funds. Filters and profile selections are kept in the URL.

## Resume and repair

A worker restart requeues interrupted jobs. Re-request a failed backfill with the same parameters to retain its checkpoints; completed units are skipped. An unresolved filing fetch/parse failure remains visible and blocks that unit's completion.

```bash
docker compose exec worker signals jobs request backfill_all
# Re-fetch adjusted price history after an older vendor correction:
docker compose exec worker signals jobs request backfill_prices --params '{"refresh_history":true}'
```

Only one worker can hold the database advisory lock. This ensures every SEC request shares its rate limiter and a persisted 403 pause survives a restart. Keep Docker and the Mac awake throughout the first load.

The spot-check script is in `scripts/spot_check.py`. Stop the scheduled worker before running its separate SEC client, then restart it:

```bash
docker compose stop worker
docker compose run --rm --no-deps -v "$PWD/scripts:/app/scripts:ro" worker python /app/scripts/spot_check.py
docker compose up -d worker
```

It prints field mismatches and five SEC links, exits unsuccessfully if fewer than 20 samples match, and leaves parsed data unchanged. Wait for historical loading to finish before treating the sample as a 2016–2026 validation. See [integration results](docs/superpowers/plans/2026-09-27-sec-dashboard/RESULTS.md) for measured evidence and pending checks.

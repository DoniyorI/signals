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

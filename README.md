# Odds Analytics

A Streamlit application for collecting football odds from The Odds API, storing market data in PostgreSQL, modelling fair prices with a bivariate Poisson model, and tracking value bets.

## What changed

The project is now split into focused modules instead of keeping the whole application in `app.py`.

- `app.py` — Streamlit UI only.
- `odds_analytics/api.py` — The Odds API client.
- `odds_analytics/db.py` — PostgreSQL connection, schema initialization, and migration backfills.
- `odds_analytics/repository.py` — persistent league and bookmaker data.
- `odds_analytics/service.py` — ingestion, result settlement, calculations, and display preparation.
- `odds_analytics/betting_math.py` — probability and Asian-market calculations.
- `odds_analytics/keys.py` — local API-key storage.
- `db/schema.sql` — database schema and migrations.
- `data/*_seed.json` — first-run seed data only.

## Persistent leagues and bookmakers

Leagues and bookmakers are now first-class PostgreSQL records:

- `leagues`
- `bookmakers`

Stored odds and bets link back to these records through foreign keys. Existing JSON selections are used only when the new tables are empty; PostgreSQL becomes the runtime source of truth after initialization.

## Requirements

- Python 3.11+
- PostgreSQL 14+ (or a recent PostgreSQL release)
- A The Odds API key

## Setup

### 1. Create the database

```sql
CREATE DATABASE odds_db;
```

### 2. Install dependencies

```bash
python -m venv .venv

# Windows
.venv\Scriptsctivate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure PostgreSQL

Copy `.env.example` to `.env` and set the PostgreSQL connection values.

### 4. Configure API keys

Copy `api_keys.txt.example` to `api_keys.txt` and add one The Odds API key per line.

### 5. Initialize the schema

```bash
python -m scripts.init_db
```

This creates the tables and seeds the initial league/bookmaker settings.

### 6. Run the app

```bash
streamlit run app.py
```

Windows users can also run `run.bat`.

## Existing database migration

The application is designed to upgrade the existing project database in place.

On startup it:

1. creates the `leagues` and `bookmakers` tables;
2. adds reference-ID columns to existing `odds_data` and `bets` tables when needed;
3. backfills known league/bookmaker references;
4. seeds reference tables only if they are empty.

This preserves existing odds and bets while moving league/bookmaker settings into PostgreSQL.

## GitHub safety

Do **not** commit:

- `.env`
- `api_keys.txt`
- PostgreSQL dumps containing credentials or private data

The Git-ready package contains only safe examples. The original archive's live credentials are intentionally not included.

If any exposed production API key or database password is still active, rotate it before publishing the repository.

## Tests

```bash
pytest -q
```

The tests cover core probability/cache behaviour and do not require a live PostgreSQL instance.

## Repository layout

```text
.
├── app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .env.example
├── api_keys.txt.example
├── .gitignore
├── .streamlit/
│   └── config.toml
├── db/
│   └── schema.sql
├── data/
│   ├── bookmakers_seed.json
│   └── leagues_seed.json
├── odds_analytics/
│   ├── api.py
│   ├── betting_math.py
│   ├── config.py
│   ├── db.py
│   ├── keys.py
│   ├── repository.py
│   └── service.py
├── scripts/
│   ├── fetch_data.py
│   └── init_db.py
└── tests/
    └── test_betting_math.py
```
"# odds_project" 
# odds_project

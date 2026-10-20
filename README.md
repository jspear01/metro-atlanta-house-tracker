# Metro Atlanta Real Estate Price Tracker App

A full-stack real estate price tracking application and analytical intelligence dashboard focused on **Metro Atlanta's Gwinnett & North Fulton submarkets**:
- **Core Cities & ZIPs:** Duluth (`30096`, `30097`), Suwanee (`30024`), Norcross (`30071`, `30092`, `30093`), and Peachtree Corners (`30092`).
- **Extensible Northern Submarkets:** Johns Creek (`30005`, `30022`), Alpharetta (`30004`, `30009`), and Cumming (`30040`, `30041`).

---

## 🌟 Key Features

1. **Automated MLS / Public Feed Ingestion**:
   - Ingestion powered by `HomeHarvest` (scraping MLS, Realtor, Redfin public data) with polite rate-limiting jitter (1.5s–3.0s).
   - High-fidelity synthetic fallback generator for instant offline demonstration, automated CI testing, and simulation of price cuts.
2. **Analytical Data Store & Deduplication**:
   - SQLite transactional analytical store (`data/tracker.db`) combined with a **DuckDB OLAP bridge** for sub-second quantile, cohort, and price-per-square-foot aggregations.
   - Deduplication engine identifying existing listings by MLS ID or address + ZIP code to track historical price modifications.
3. **Price Drop & Bargain Alert Engine**:
   - Configurable alert rules for steep price reductions (e.g., `>5%` cut) and deep-value bargains (e.g., sub-`$220/sqft`).
   - Automated `AlertLog` records generated during pipeline runs.
4. **Interactive Analytical Dashboard (Streamlit)**:
   - **Executive KPI Cards:** Active inventory, median list price, median $/sqft, median days on market (DOM), and price drop ratio.
   - **Interactive Charts:** Price vs. living area scatter plot with regression/threshold lines, submarket comparison bar charts, and DOM distribution histograms.
   - **Geospatial Map & Property Cards:** Interactive coordinate mapping with property thumbnails, bedroom/bathroom stats, $/sqft badges, and direct external MLS links.
   - **Deal Alert Feed & Rule Manager:** Real-time alert viewer and custom rule creator.
   - **Pipeline Control Panel:** One-click live or mock ingestion trigger.
5. **FastAPI REST API**:
   - Full programmatic API for listing filters, price history, executive metrics, alerts, and ingestion triggers.
6. **Persistent Checkpoint Harness Protocol**:
   - Machine-readable state tracking in `.state/checkpoint.json` and human-readable tracking in `PROJECT_STATE.md` with CLI tool `scripts/checkpoint.py`.

---

## 📂 Project Directory Structure

```text
metro-atl-tracker/
├── .state/
│   ├── checkpoint.json       # Machine-readable session state & task graph
│   └── run_history.log       # Execution timestamp & audit log
├── PROJECT_STATE.md          # Human-readable progress, milestones, and blockers
├── scripts/
│   └── checkpoint.py         # State manager & validation harness CLI
├── data/
│   └── tracker.db            # Analytical SQLite / DuckDB database
├── src/
│   ├── __init__.py
│   ├── config.py             # Submarket definitions, coordinates, and thresholds
│   ├── database/             # SQLAlchemy models, SQLite & DuckDB connectors, repository
│   │   ├── models.py
│   │   ├── connection.py
│   │   └── repository.py
│   ├── ingestion/            # Live scraper, mock generator, and normalization pipeline
│   │   ├── scraper.py
│   │   ├── mock_generator.py
│   │   └── pipeline.py
│   ├── analytics/            # DuckDB and Pandas KPI calculations & cohorts
│   │   └── metrics.py
│   ├── backend/              # FastAPI REST endpoints
│   │   └── main.py
│   └── frontend/             # Streamlit analytical dashboard
│       └── dashboard.py
├── tests/
│   └── test_tracker.py       # Pytest unit & integration test suite
├── app.py                    # Streamlit entry point
└── README.md
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
Ensure Python 3.11+ is installed. Activate your virtual environment:
```bash
source venv/bin/activate
```

### 2. Launch the Streamlit Dashboard
The Streamlit application runs at `http://localhost:8501`:
```bash
streamlit run app.py --server.port 8501
```

### 3. Launch the FastAPI Backend (Optional REST API)
Run the REST API server at `http://localhost:8000`:
```bash
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload
```
Interactive Swagger UI documentation is available at `http://localhost:8000/docs`.

### 4. Run the Ingestion Pipeline
To ingest property listings programmatically:
```bash
# Ingest synthetic Metro Atlanta listings (seed)
python -c "from src.ingestion.pipeline import run_pipeline; print(run_pipeline(source='mock'))"

# Ingest live Realtor / MLS listings (with polite jitter)
python -c "from src.ingestion.pipeline import run_pipeline; print(run_pipeline(source='live'))"
```

### 5. Run the Automated Test Suite
```bash
PYTHONPATH=. pytest -v tests/test_tracker.py
```

---

## 🛠️ Persistent Checkpoint Protocol

The project harness tracks development milestones, sessions, and blockers automatically:
```bash
# View current project state
python scripts/checkpoint.py status

# Synchronize PROJECT_STATE.md from .state/checkpoint.json
python scripts/checkpoint.py sync

# Update task status
python scripts/checkpoint.py update T1.1 completed

# Change current phase
python scripts/checkpoint.py phase "Phase 6: Testing & Validation"
```

---

## 📡 REST API Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health status check |
| `GET` | `/api/submarkets` | List supported cities, zip codes, and coordinates |
| `GET` | `/api/properties` | Filter listings by city, zip, price, beds, baths, price drops |
| `GET` | `/api/properties/{id}` | Property details and full historical price changes |
| `GET` | `/api/analytics/kpis` | Executive market KPIs (median price, $/sqft, DOM) |
| `GET` | `/api/analytics/submarkets` | Breakdown statistics grouped by city |
| `GET` | `/api/analytics/zips` | Breakdown statistics grouped by ZIP code |
| `GET` | `/api/analytics/advanced` | DuckDB accelerated quantiles and DOM cohort pricing |
| `GET` | `/api/alerts` | Recent triggered price cut and bargain alerts |
| `GET` | `/api/alerts/rules` | Configured alert rule definitions |
| `POST`| `/api/alerts/rules` | Create a new alert rule |
| `POST`| `/api/ingest` | Trigger data ingestion pipeline (mock or live) |

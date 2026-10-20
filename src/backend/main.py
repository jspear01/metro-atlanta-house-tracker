"""
FastAPI REST API for Metro Atlanta Real Estate Price Tracker.
"""

from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.connection import get_db, init_db
from src.database.models import Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot
from src.database.repository import (
    query_properties,
    get_property_by_id,
    get_price_history_for_property,
    get_alert_rules,
    get_recent_alerts,
    get_snapshots
)
from src.analytics.metrics import (
    get_properties_dataframe,
    compute_executive_kpis,
    compute_submarket_breakdown,
    compute_zip_code_breakdown,
    compute_duckdb_advanced_analytics
)
from src.ingestion.pipeline import run_pipeline
from src.config import TARGET_SUBMARKETS, ALL_ZIP_CODES

app = FastAPI(
    title="Metro Atlanta Real Estate Price Tracker API",
    description="REST API for Gwinnett & North Fulton submarket listings, analytics, and price drop alerts.",
    version="1.0.0"
)

# Enable CORS for frontend integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    init_db()


# -----------------------------
# Schemas
# -----------------------------
class RuleCreateRequest(BaseModel):
    name: str
    is_active: bool = True
    min_price_drop_pct: Optional[float] = None
    max_price_per_sqft: Optional[float] = None
    cities: Optional[str] = None
    zip_codes: Optional[str] = None
    max_price: Optional[float] = None
    min_beds: Optional[float] = None


class IngestionRequest(BaseModel):
    source: str = "all"  # "all", "realtor", "foreclosure", "redfin", "mock"
    sources: Optional[List[str]] = None
    submarkets: Optional[List[str]] = None
    include_foreclosures: bool = True
    include_redfin: bool = False


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "metro-atl-tracker", "version": "1.0.0"}


@app.get("/api/submarkets")
def list_submarkets():
    return {
        "submarkets": TARGET_SUBMARKETS,
        "all_zip_codes": ALL_ZIP_CODES
    }


@app.get("/api/properties")
def get_properties(
    cities: Optional[List[str]] = Query(None),
    zip_codes: Optional[List[str]] = Query(None),
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_beds: Optional[float] = None,
    min_baths: Optional[float] = None,
    max_sqft_price: Optional[float] = None,
    price_drop_only: bool = False,
    foreclosure_only: bool = False,
    source: Optional[str] = None,
    sort_by: str = "last_seen_date",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Retrieve filtered property listings."""
    props = query_properties(
        session=db,
        cities=cities,
        zip_codes=zip_codes,
        min_price=min_price,
        max_price=max_price,
        min_beds=min_beds,
        min_baths=min_baths,
        max_sqft_price=max_sqft_price,
        price_drop_only=price_drop_only,
        foreclosure_only=foreclosure_only,
        source=source,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset
    )
    return [p.to_dict() for p in props]


@app.get("/api/properties/{property_id}")
def get_property_details(property_id: int, db: Session = Depends(get_db)):
    """Retrieve property details and its full price change timeline."""
    prop = get_property_by_id(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    history = get_price_history_for_property(db, property_id)
    data = prop.to_dict()
    data["price_history"] = [h.to_dict() for h in history]
    return data


@app.get("/api/analytics/kpis")
def get_kpis(
    cities: Optional[List[str]] = Query(None),
    zip_codes: Optional[List[str]] = Query(None),
    property_type: Optional[str] = None,
    price_drop_only: bool = False,
    foreclosure_only: bool = False,
    source: Optional[str] = None
):
    """Executive KPI metrics across selected submarkets."""
    df = get_properties_dataframe(
        cities=cities,
        zip_codes=zip_codes,
        property_type=property_type,
        price_drop_only=price_drop_only,
        foreclosure_only=foreclosure_only,
        source=source
    )
    return compute_executive_kpis(df)


@app.get("/api/analytics/submarkets")
def get_submarket_analytics(
    property_type: Optional[str] = None
):
    """Comparative analytics grouped by city."""
    df = get_properties_dataframe(property_type=property_type)
    submarkets_df = compute_submarket_breakdown(df)
    return submarkets_df.to_dict(orient="records")


@app.get("/api/analytics/zips")
def get_zip_analytics():
    """Comparative analytics grouped by ZIP code."""
    df = get_properties_dataframe()
    zips_df = compute_zip_code_breakdown(df)
    return zips_df.to_dict(orient="records")


@app.get("/api/analytics/advanced")
def get_advanced_analytics():
    """DuckDB accelerated quantiles and cohort analysis."""
    return compute_duckdb_advanced_analytics()


@app.get("/api/alerts")
def get_alerts(limit: int = 50, db: Session = Depends(get_db)):
    """Get recent triggered price drop and bargain alerts."""
    alerts = get_recent_alerts(db, limit=limit)
    return [a.to_dict() for a in alerts]


@app.get("/api/alerts/rules")
def list_rules(db: Session = Depends(get_db)):
    """List all configured alert rules."""
    rules = get_alert_rules(db)
    return [r.to_dict() for r in rules]


@app.post("/api/alerts/rules")
def create_rule(req: RuleCreateRequest, db: Session = Depends(get_db)):
    """Create a new alert rule."""
    rule = AlertRule(
        name=req.name,
        is_active=req.is_active,
        min_price_drop_pct=req.min_price_drop_pct,
        max_price_per_sqft=req.max_price_per_sqft,
        cities=req.cities,
        zip_codes=req.zip_codes,
        max_price=req.max_price,
        min_beds=req.min_beds
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict()


@app.put("/api/alerts/rules/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    """Toggle rule active/inactive state."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    db.commit()
    return {"id": rule.id, "name": rule.name, "is_active": rule.is_active}


@app.post("/api/ingest")
def trigger_ingestion(req: IngestionRequest, background_tasks: BackgroundTasks):
    """Trigger ingestion pipeline across selected sources (Realtor, Foreclosure, Redfin, Mock)."""
    result = run_pipeline(
        source=req.source,
        sources=req.sources,
        submarkets=req.submarkets,
        include_foreclosures=req.include_foreclosures,
        include_redfin=req.include_redfin
    )
    return result


@app.get("/api/snapshots")
def get_ingestion_history(limit: int = 20, db: Session = Depends(get_db)):
    """Retrieve historical ingestion snapshots."""
    snaps = get_snapshots(db, limit=limit)
    return [s.to_dict() for s in snaps]

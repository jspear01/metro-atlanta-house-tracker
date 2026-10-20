"""
Analytics and Aggregation Engine using DuckDB & Pandas for Metro Atlanta Real Estate.
"""

from typing import Dict, Any, List, Optional
import pandas as pd
import duckdb

from src.config import DB_PATH
from sqlalchemy.orm import Session
from src.database.connection import get_session
from src.database.models import Property, PriceHistory


def get_properties_dataframe(
    cities: Optional[List[str]] = None,
    zip_codes: Optional[List[str]] = None,
    property_type: Optional[str] = None,
    price_drop_only: bool = False,
    foreclosure_only: bool = False,
    source: Optional[str] = None
) -> pd.DataFrame:
    """Fetch properties as a Pandas DataFrame for analytics."""
    with get_session() as session:
        query = session.query(Property)
        if cities:
            query = query.filter(Property.city.in_(cities))
        if zip_codes:
            query = query.filter(Property.zip_code.in_(zip_codes))
        if property_type and property_type != "All":
            query = query.filter(Property.style == property_type)
        if price_drop_only:
            query = query.filter(Property.is_price_drop == True)
        if foreclosure_only:
            query = query.filter(Property.is_foreclosure == True)
        if source and source != "All":
            query = query.filter(Property.listing_source == source)

        props = query.all()
        if not props:
            return pd.DataFrame()

        data = [p.to_dict() for p in props]
        return pd.DataFrame(data)


def compute_executive_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute high-level executive market KPIs."""
    if df.empty:
        return {
            "total_inventory": 0,
            "median_price": 0.0,
            "median_sqft_price": 0.0,
            "median_dom": 0,
            "price_drop_count": 0,
            "price_drop_pct_inventory": 0.0,
            "avg_price_drop_rate": 0.0,
            "sub_220_count": 0,
            "foreclosure_count": 0
        }

    total_inventory = len(df)
    median_price = float(df["current_list_price"].median())
    
    valid_sqft_prices = df["price_per_sqft"].dropna()
    median_sqft_price = float(valid_sqft_prices.median()) if not valid_sqft_prices.empty else 0.0
    
    median_dom = int(df["days_on_market"].median()) if "days_on_market" in df else 0
    
    price_drops = df[df["is_price_drop"] == True]
    price_drop_count = len(price_drops)
    price_drop_pct_inventory = round((price_drop_count / total_inventory) * 100, 1) if total_inventory > 0 else 0.0
    avg_price_drop_rate = round(float(price_drops["price_drop_pct"].mean()), 1) if not price_drops.empty else 0.0

    sub_220_count = len(df[df["price_per_sqft"] <= 220.0])
    foreclosure_count = int(df["is_foreclosure"].sum()) if "is_foreclosure" in df else 0

    return {
        "total_inventory": total_inventory,
        "median_price": median_price,
        "median_sqft_price": median_sqft_price,
        "median_dom": median_dom,
        "price_drop_count": price_drop_count,
        "price_drop_pct_inventory": price_drop_pct_inventory,
        "avg_price_drop_rate": avg_price_drop_rate,
        "sub_220_count": sub_220_count,
        "foreclosure_count": foreclosure_count
    }


def compute_submarket_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Break down median price, $/sqft, and DOM by City."""
    if df.empty:
        return pd.DataFrame()

    grouped = df.groupby("city").agg(
        inventory_count=("id", "count"),
        median_price=("current_list_price", "median"),
        median_sqft_price=("price_per_sqft", "median"),
        median_dom=("days_on_market", "median"),
        price_drop_count=("is_price_drop", "sum")
    ).reset_index()

    grouped["price_drop_rate"] = (grouped["price_drop_count"] / grouped["inventory_count"] * 100).round(1)
    grouped["median_price"] = grouped["median_price"].round(-2)
    grouped["median_sqft_price"] = grouped["median_sqft_price"].round(1)
    return grouped.sort_values(by="inventory_count", ascending=False)


def compute_zip_code_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Break down median price, $/sqft, and DOM by ZIP Code."""
    if df.empty:
        return pd.DataFrame()

    grouped = df.groupby(["city", "zip_code"]).agg(
        inventory_count=("id", "count"),
        median_price=("current_list_price", "median"),
        median_sqft_price=("price_per_sqft", "median"),
        median_dom=("days_on_market", "median"),
        price_drop_count=("is_price_drop", "sum")
    ).reset_index()

    grouped["price_drop_rate"] = (grouped["price_drop_count"] / grouped["inventory_count"] * 100).round(1)
    grouped["median_price"] = grouped["median_price"].round(-2)
    grouped["median_sqft_price"] = grouped["median_sqft_price"].round(1)
    return grouped.sort_values(by="median_price", ascending=False)


def compute_duckdb_advanced_analytics() -> Dict[str, Any]:
    """Execute high-performance analytical queries with DuckDB."""
    try:
        conn = duckdb.connect()
        conn.execute(f"ATTACH '{DB_PATH}' AS tracker (TYPE SQLITE);")

        # City quantiles query
        city_quantiles = conn.execute("""
            SELECT 
                city,
                COUNT(*) as listing_count,
                ROUND(MEDIAN(current_list_price), 0) as median_price,
                ROUND(QUANTILE_CONT(current_list_price, 0.25), 0) as p25_price,
                ROUND(QUANTILE_CONT(current_list_price, 0.75), 0) as p75_price,
                ROUND(MEDIAN(price_per_sqft), 1) as median_sqft_price,
                ROUND(AVG(days_on_market), 1) as avg_dom,
                SUM(CASE WHEN is_price_drop THEN 1 ELSE 0 END) as price_drops,
                SUM(CASE WHEN price_per_sqft <= 220.0 THEN 1 ELSE 0 END) as bargain_sqft_count
            FROM tracker.properties
            GROUP BY city
            ORDER BY listing_count DESC
        """).fetchdf()

        # Days on market cohorts
        dom_cohorts = conn.execute("""
            SELECT 
                CASE 
                    WHEN days_on_market <= 7 THEN '0-7 Days (Fresh)'
                    WHEN days_on_market <= 21 THEN '8-21 Days (Active)'
                    WHEN days_on_market <= 45 THEN '22-45 Days (Moderate)'
                    ELSE '46+ Days (Stale)'
                END as dom_bucket,
                COUNT(*) as count,
                ROUND(MEDIAN(current_list_price), 0) as median_price,
                ROUND(MEDIAN(price_per_sqft), 1) as median_sqft_price,
                SUM(CASE WHEN is_price_drop THEN 1 ELSE 0 END) as price_drops
            FROM tracker.properties
            GROUP BY 1
            ORDER BY MIN(days_on_market) ASC
        """).fetchdf()

        conn.close()
        return {
            "city_quantiles": city_quantiles.to_dict(orient="records"),
            "dom_cohorts": dom_cohorts.to_dict(orient="records")
        }
    except Exception as e:
        # Fallback if duckdb sqlite extension has path quirks
        return {"error": str(e), "city_quantiles": [], "dom_cohorts": []}


def compute_eviction_metrics(df_ev: pd.DataFrame) -> Dict[str, Any]:
    """Computes executive KPIs and year-over-year trends for eviction filings."""
    if df_ev.empty:
        return {}
    df_sorted = df_ev.sort_values("date").reset_index(drop=True)
    latest_month = df_sorted.iloc[-1]
    prior_month = df_sorted.iloc[-2] if len(df_sorted) > 1 else latest_month

    # Yearly aggregates
    yearly = df_sorted.groupby("year")["filings"].agg(["sum", "mean", "count"]).reset_index()

    # Current 12-month rolling sum
    recent_12m = df_sorted.tail(12)["filings"].sum() if len(df_sorted) >= 12 else df_sorted["filings"].sum()

    # YoY 6-month comparison
    if len(df_sorted) >= 18:
        last_6m_avg = df_sorted.tail(6)["filings"].mean()
        prev_year_6m_avg = df_sorted.iloc[-18:-12]["filings"].mean()
        yoy_pct_change = round(((last_6m_avg - prev_year_6m_avg) / prev_year_6m_avg) * 100, 1) if prev_year_6m_avg > 0 else 0.0
    else:
        yoy_pct_change = 0.0

    return {
        "latest_month_str": str(latest_month["month"]),
        "latest_month_filings": int(latest_month["filings"]),
        "prior_month_filings": int(prior_month["filings"]),
        "month_over_month_diff": int(latest_month["filings"] - prior_month["filings"]),
        "recent_12m_filings": int(recent_12m),
        "total_historical_filings": int(df_sorted["filings"].sum()),
        "yoy_trend_pct": yoy_pct_change,
        "is_increasing": yoy_pct_change > 0,
        "status_summary": "High Crisis Plateau (~3,200/mo)" if latest_month["filings"] > 2500 else "Moderate Baseline"
    }


def compute_mortgage_delinquency_metrics(df_mort: pd.DataFrame) -> Dict[str, Any]:
    """Computes historical delinquency and foreclosure pipeline rates by county."""
    if df_mort.empty:
        return {}

    county_summaries = {}
    for county, cdf in df_mort.groupby("county"):
        csorted = cdf.sort_values("date").reset_index(drop=True)
        latest = csorted.iloc[-1]

        # 2021 low trough (pandemic forbearance)
        cdf_2021 = csorted[csorted["year"] == 2021]
        trough_90 = float(cdf_2021["late_90_plus_pct"].min()) if not cdf_2021.empty else None

        cur_90 = float(latest["late_90_plus_pct"])
        cur_30 = float(latest["late_30_89_pct"]) if pd.notna(latest["late_30_89_pct"]) else 0.0

        pct_increase_from_trough = round(((cur_90 - trough_90) / trough_90) * 100, 1) if trough_90 and trough_90 > 0 else 0.0

        county_summaries[str(county)] = {
            "latest_month": str(latest["month"]),
            "current_90_plus_late_pct": cur_90,
            "current_30_89_late_pct": cur_30,
            "trough_2021_90_pct": trough_90,
            "pct_increase_from_trough": pct_increase_from_trough,
            "is_increasing": cur_90 > (trough_90 or 0.0)
        }

    return county_summaries


def compute_price_drop_summary(
    session: Session,
    cities: Optional[List[str]] = None,
    min_drop_pct: Optional[float] = None,
    max_days_to_drop: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes structured 'How Much within How Long' price drop metrics and deals list.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    query = session.query(Property).filter(Property.is_price_drop == True)
    if cities:
        query = query.filter(Property.city.in_(cities))
    if min_drop_pct is not None and min_drop_pct > 0:
        query = query.filter(Property.price_drop_pct >= min_drop_pct)

    props = query.all()
    deals = []

    for p in props:
        hist = (
            session.query(PriceHistory)
            .filter(PriceHistory.property_id == p.id)
            .order_by(PriceHistory.event_date.asc())
            .all()
        )
        listed_event = next((h for h in hist if h.event_type == "listed"), None)
        drop_events = [h for h in hist if h.event_type == "price_drop"]
        latest_drop = drop_events[-1] if drop_events else None

        listed_date = listed_event.event_date if listed_event else p.first_seen_date
        drop_date = latest_drop.event_date if latest_drop else p.last_seen_date

        # Calculate days to drop (how long did it sit before the cut?)
        if drop_date and listed_date:
            days_to_drop = max(1, (drop_date - listed_date).days)
        else:
            days_to_drop = max(1, int(p.days_on_market * 0.6)) if p.days_on_market else 14

        if max_days_to_drop is not None and days_to_drop > max_days_to_drop:
            continue

        # Days since the drop occurred
        if drop_date:
            if drop_date.tzinfo is None:
                drop_date = drop_date.replace(tzinfo=timezone.utc)
            days_since_drop = max(0, (now - drop_date).days)
        else:
            days_since_drop = 0

        # Velocity badge and category
        if days_to_drop <= 14:
            velocity_tag = "⚡ Fast Slash (< 14 days)"
            velocity_color = "#10b981"  # Emerald
            velocity_desc = "Aggressive seller testing market; quick reduction."
        elif days_to_drop <= 30:
            velocity_tag = "⏳ Steady Cut (15–30 days)"
            velocity_color = "#3b82f6"  # Blue
            velocity_desc = "Standard 3-4 week adjustment cycle."
        else:
            velocity_tag = "🐌 Stale Cut (> 30 days)"
            velocity_color = "#f59e0b"  # Amber
            velocity_desc = "Sat for over a month before price correction."

        timeline_steps = []
        for h in hist:
            ed = h.event_date.strftime("%b %d, %Y") if h.event_date else "N/A"
            timeline_steps.append({
                "date": ed,
                "price": h.price,
                "price_str": f"${h.price:,.0f}",
                "event_type": h.event_type,
                "note": h.note or ""
            })

        drop_amount = p.price_drop_amount or (p.initial_list_price - p.current_list_price)
        drop_pct = p.price_drop_pct or (
            round(((p.initial_list_price - p.current_list_price) / p.initial_list_price) * 100, 1)
            if p.initial_list_price else 0.0
        )

        deals.append({
            "id": p.id,
            "mls_id": p.mls_id,
            "formatted_address": p.formatted_address,
            "city": p.city,
            "zip_code": p.zip_code,
            "county": p.county,
            "current_price": p.current_list_price,
            "initial_price": p.initial_list_price,
            "drop_amount": drop_amount,
            "drop_pct": drop_pct,
            "price_per_sqft": p.price_per_sqft,
            "beds": p.beds,
            "full_baths": p.full_baths,
            "sqft": p.sqft,
            "days_on_market": p.days_on_market,
            "days_to_drop": days_to_drop,
            "days_since_drop": days_since_drop,
            "listed_date_str": listed_date.strftime("%b %d, %Y") if listed_date else "N/A",
            "drop_date_str": drop_date.strftime("%b %d, %Y") if drop_date else "N/A",
            "velocity_tag": velocity_tag,
            "velocity_color": velocity_color,
            "velocity_desc": velocity_desc,
            "primary_photo": p.primary_photo or "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?w=800&auto=format&fit=crop&q=60",
            "property_url": p.property_url,
            "is_foreclosure": bool(p.is_foreclosure),
            "listing_source": p.listing_source or "MLS/Realtor",
            "timeline": timeline_steps
        })

    total_deals = len(deals)
    if total_deals > 0:
        avg_drop_amount = sum(d["drop_amount"] for d in deals) / total_deals
        avg_drop_pct = sum(d["drop_pct"] for d in deals) / total_deals
        avg_days_to_drop = sum(d["days_to_drop"] for d in deals) / total_deals
        fastest_cut = min(d["days_to_drop"] for d in deals)
        largest_amt = max(d["drop_amount"] for d in deals)
        largest_pct = max(d["drop_pct"] for d in deals)
    else:
        avg_drop_amount = 0.0
        avg_drop_pct = 0.0
        avg_days_to_drop = 0.0
        fastest_cut = 0
        largest_amt = 0.0
        largest_pct = 0.0

    return {
        "deals": deals,
        "kpis": {
            "total_deals": total_deals,
            "avg_drop_amount": avg_drop_amount,
            "avg_drop_pct": avg_drop_pct,
            "avg_days_to_drop": avg_days_to_drop,
            "fastest_cut": fastest_cut,
            "largest_amt": largest_amt,
            "largest_pct": largest_pct
        }
    }


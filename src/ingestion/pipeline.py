"""
Ingestion and Normalization Pipeline with Deduplication & Alert Evaluation.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from src.database.connection import get_session
from src.database.models import Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot
from src.ingestion.scraper import scrape_metro_atlanta_submarkets
from src.ingestion.mock_generator import generate_metro_atlanta_listings

logger = logging.getLogger(__name__)


def evaluate_property_alerts(session: Session, prop: Property) -> List[AlertLog]:
    """Check active alert rules against a property and create AlertLog entries."""
    active_rules = session.query(AlertRule).filter(AlertRule.is_active == True).all()
    triggered_logs = []

    for rule in active_rules:
        # Check city filter
        if rule.cities:
            rule_cities = [c.strip().lower() for c in rule.cities.split(",")]
            if prop.city.lower() not in rule_cities:
                continue

        # Check zip filter
        if rule.zip_codes:
            rule_zips = [z.strip() for z in rule.zip_codes.split(",")]
            if prop.zip_code not in rule_zips:
                continue

        # Check max price
        if rule.max_price is not None and prop.current_list_price > rule.max_price:
            continue

        # Check min beds
        if rule.min_beds is not None and (prop.beds is None or prop.beds < rule.min_beds):
            continue

        reasons = []

        # Check price drop %
        if rule.min_price_drop_pct is not None:
            if prop.is_price_drop and prop.price_drop_pct >= rule.min_price_drop_pct:
                reasons.append(f"Price cut of {prop.price_drop_pct:.1f}% (-${prop.price_drop_amount:,.0f})")

        # Check sub $/sqft
        if rule.max_price_per_sqft is not None:
            if prop.price_per_sqft and prop.price_per_sqft <= rule.max_price_per_sqft:
                reasons.append(f"Sub-${rule.max_price_per_sqft:.0f}/sqft deal (${prop.price_per_sqft:.0f}/sqft)")

        if reasons:
            # Check if this rule already triggered for this property recently (past 24h)
            recent_trigger = (
                session.query(AlertLog)
                .filter(
                    AlertLog.rule_id == rule.id,
                    AlertLog.property_id == prop.id,
                    AlertLog.triggered_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                )
                .first()
            )
            if not recent_trigger:
                msg = f"[{rule.name}] {prop.formatted_address} (${prop.current_list_price:,.0f}) - " + "; ".join(reasons)
                alert_log = AlertLog(
                    rule_id=rule.id,
                    property_id=prop.id,
                    triggered_at=datetime.now(timezone.utc),
                    message=msg,
                    status="active"
                )
                session.add(alert_log)
                triggered_logs.append(alert_log)

    return triggered_logs


def ingest_records(records: List[Dict[str, Any]], source_name: str = "custom") -> Dict[str, Any]:
    """
    Ingest, deduplicate, update price histories, and evaluate alerts.
    """
    now = datetime.now(timezone.utc)
    inserted_count = 0
    updated_count = 0
    alerts_count = 0

    with get_session() as session:
        for rec in records:
            mls_id = rec.get("mls_id")
            address = rec.get("formatted_address")
            zip_code = rec.get("zip_code")

            # Deduplication lookup
            existing = None
            if mls_id:
                existing = session.query(Property).filter(Property.mls_id == mls_id).first()
            if not existing and address and zip_code:
                existing = (
                    session.query(Property)
                    .filter(Property.formatted_address == address, Property.zip_code == zip_code)
                    .first()
                )

            current_price = float(rec.get("current_list_price", 0.0))
            if current_price <= 0:
                continue

            sqft = float(rec.get("sqft") or 0.0)
            price_per_sqft = round(current_price / sqft, 2) if sqft > 0 else None

            if existing:
                # Update existing record
                old_price = existing.current_list_price
                price_changed = abs(current_price - old_price) > 1.0

                if price_changed:
                    if current_price < old_price:
                        existing.is_price_drop = True
                        diff = old_price - current_price
                        existing.price_drop_amount = diff
                        existing.price_drop_pct = round((diff / old_price) * 100, 2)
                        event_type = "price_drop"
                    else:
                        event_type = "price_increase"

                    history_item = PriceHistory(
                        property_id=existing.id,
                        price=current_price,
                        price_per_sqft=price_per_sqft,
                        event_type=event_type,
                        event_date=now,
                        note=f"Price changed from ${old_price:,.0f} to ${current_price:,.0f}"
                    )
                    session.add(history_item)

                existing.current_list_price = current_price
                existing.price_per_sqft = price_per_sqft
                existing.days_on_market = rec.get("days_on_market", existing.days_on_market)
                existing.status = rec.get("status", existing.status)
                existing.last_seen_date = now
                if rec.get("is_foreclosure"):
                    existing.is_foreclosure = True
                if rec.get("listing_source"):
                    existing.listing_source = rec.get("listing_source")
                if rec.get("primary_photo"):
                    existing.primary_photo = rec.get("primary_photo")

                updated_count += 1
                prop_for_alert = existing
            else:
                # New property
                initial_price = rec.get("initial_list_price", current_price)
                is_drop = rec.get("is_price_drop", False)
                drop_pct = rec.get("price_drop_pct", 0.0)
                drop_amt = rec.get("price_drop_amount", 0.0)

                prop = Property(
                    mls_id=mls_id,
                    property_url=rec.get("property_url"),
                    formatted_address=address or f"{rec.get('street', '')}, {rec.get('city', '')}, GA {zip_code}",
                    street=rec.get("street"),
                    unit=rec.get("unit"),
                    city=rec.get("city", "Duluth"),
                    state=rec.get("state", "GA"),
                    zip_code=zip_code,
                    county=rec.get("county", "Gwinnett"),
                    beds=rec.get("beds"),
                    full_baths=rec.get("full_baths"),
                    half_baths=rec.get("half_baths"),
                    sqft=sqft if sqft > 0 else None,
                    lot_sqft=rec.get("lot_sqft"),
                    year_built=rec.get("year_built"),
                    style=rec.get("style", "Single Family"),
                    status=rec.get("status", "FOR_SALE"),
                    current_list_price=current_price,
                    initial_list_price=initial_price,
                    price_per_sqft=price_per_sqft,
                    days_on_market=rec.get("days_on_market", 0),
                    hoa_fee=rec.get("hoa_fee"),
                    latitude=rec.get("latitude"),
                    longitude=rec.get("longitude"),
                    primary_photo=rec.get("primary_photo"),
                    first_seen_date=now - timedelta(days=rec.get("days_on_market", 0)),
                    last_seen_date=now,
                    is_price_drop=is_drop,
                    price_drop_pct=drop_pct,
                    price_drop_amount=drop_amt,
                    is_foreclosure=bool(rec.get("is_foreclosure", False)),
                    listing_source=rec.get("listing_source", "MLS/Realtor")
                )
                session.add(prop)
                session.flush()  # assign prop.id

                # Initial price history event
                hist_listed = PriceHistory(
                    property_id=prop.id,
                    price=initial_price,
                    price_per_sqft=round(initial_price / sqft, 2) if sqft > 0 else None,
                    event_type="listed",
                    event_date=now - timedelta(days=rec.get("days_on_market", 0)),
                    note="Initial Listing"
                )
                session.add(hist_listed)

                # If mock or feed has simulated price history events
                for sim in rec.get("_simulated_history", []):
                    if sim.get("event_type") != "listed":
                        hist_sim = PriceHistory(
                            property_id=prop.id,
                            price=sim.get("price"),
                            price_per_sqft=round(sim.get("price") / sqft, 2) if sqft > 0 else None,
                            event_type=sim.get("event_type", "price_drop"),
                            event_date=now - timedelta(days=sim.get("days_ago", 5)),
                            note=f"Price adjustment to ${sim.get('price'):,.0f}"
                        )
                        session.add(hist_sim)

                inserted_count += 1
                prop_for_alert = prop

            # Evaluate alerts for this property
            new_alerts = evaluate_property_alerts(session, prop_for_alert)
            alerts_count += len(new_alerts)

        # Log Ingestion Snapshot
        snapshot = IngestionSnapshot(
            timestamp=now,
            source=source_name,
            records_ingested=inserted_count,
            records_updated=updated_count,
            alerts_triggered=alerts_count,
            notes=f"Ingested {inserted_count} new, {updated_count} updated, {alerts_count} alerts from {source_name}."
        )
        session.add(snapshot)
        session.commit()

    return {
        "status": "success",
        "inserted": inserted_count,
        "updated": updated_count,
        "alerts_triggered": alerts_count,
        "total_processed": len(records)
    }


def run_pipeline(
    source: str = "live",
    sources: Optional[List[str]] = None,
    submarkets: Optional[List[str]] = None,
    include_foreclosures: bool = False,
    include_redfin: bool = False
) -> Dict[str, Any]:
    """
    Run pipeline from multiple sources:
    - 'live' / 'realtor': Standard MLS/Realtor feed via HomeHarvest
    - 'foreclosure': Dedicated foreclosed & bank-owned (REO) feed
    - 'redfin': Redfin public Open Data GIS CSV feed
    - 'auction' / 'legal_notice': Georgia courthouse auctions & trustee foreclosure notices
    - 'mock': High-fidelity synthetic fallback generator
    """
    from src.ingestion.scraper import (
        scrape_metro_atlanta_submarkets,
        scrape_foreclosed_properties,
        scrape_redfin_submarkets,
        scrape_georgia_auctions_and_legal_notices
    )
    from src.ingestion.mock_generator import generate_metro_atlanta_listings

    all_records: List[Dict[str, Any]] = []
    active_sources = list(sources) if sources else []

    # Map string source to active sources list
    if source == "foreclosure":
        active_sources.append("foreclosure")
    elif source == "redfin":
        active_sources.append("redfin")
    elif source in ["auction", "legal_notice", "auctions"]:
        active_sources.append("auction")
    elif source == "all":
        active_sources.extend(["realtor", "foreclosure", "redfin", "auction"])
    elif source == "live":
        active_sources.append("realtor")
        if include_foreclosures:
            active_sources.append("foreclosure")
        if include_redfin:
            active_sources.append("redfin")
    elif source == "mock":
        active_sources.append("mock")

    if not active_sources:
        active_sources = ["realtor"]

    source_labels = []

    # 1. Realtor / MLS Live Feed
    if "realtor" in active_sources:
        logger.info("Executing Realtor / MLS live scraper...")
        realtor_records = scrape_metro_atlanta_submarkets(submarkets=submarkets)
        all_records.extend(realtor_records)
        source_labels.append("Realtor_MLS")

    # 2. Foreclosed & Bank-Owned Properties Feed
    if "foreclosure" in active_sources:
        logger.info("Executing Foreclosed & Bank-Owned Homes scraper...")
        fc_records = scrape_foreclosed_properties()
        all_records.extend(fc_records)
        source_labels.append("Foreclosure_REO")

    # 3. Redfin Open Data GIS Feed (Option 1)
    if "redfin" in active_sources:
        logger.info("Executing Redfin Open Data feed scraper...")
        rf_records = scrape_redfin_submarkets(limit=100, submarkets=submarkets)
        all_records.extend(rf_records)
        source_labels.append("Redfin_OpenData")

    # 4. Georgia Courthouse Auctions & Legal Foreclosure Notices (Option 3)
    if "auction" in active_sources or "legal_notice" in active_sources:
        logger.info("Executing Georgia Courthouse Auctions & Legal Notices scraper...")
        auc_records = scrape_georgia_auctions_and_legal_notices(submarkets=submarkets, limit=60)
        all_records.extend(auc_records)
        source_labels.append("GA_Auctions_LegalNotices")

    # 5. Mock fallback if requested or if live empty
    if "mock" in active_sources:
        mock_records = generate_metro_atlanta_listings(count_per_city=15)
        all_records.extend(mock_records)
        source_labels.append("Mock_Seed")

    if not all_records and "mock" not in active_sources:
        logger.warning("All scraping sources returned 0 records; running fallback mock seed.")
        all_records = generate_metro_atlanta_listings(count_per_city=12)
        source_labels.append("Fallback_Mock")

    combined_source_name = "+".join(source_labels) if source_labels else source
    return ingest_records(all_records, source_name=combined_source_name)

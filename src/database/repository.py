"""
Data repository layer for querying and updating tracker database.
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from src.database.models import Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot


def query_properties(
    session: Session,
    cities: Optional[List[str]] = None,
    zip_codes: Optional[List[str]] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_beds: Optional[float] = None,
    min_baths: Optional[float] = None,
    max_sqft_price: Optional[float] = None,
    price_drop_only: bool = False,
    foreclosure_only: bool = False,
    source: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: str = "last_seen_date",
    sort_dir: str = "desc",
    limit: int = 100,
    offset: int = 0
) -> List[Property]:
    query = session.query(Property)

    if cities:
        query = query.filter(Property.city.in_(cities))
    if zip_codes:
        query = query.filter(Property.zip_code.in_(zip_codes))
    if min_price is not None:
        query = query.filter(Property.current_list_price >= min_price)
    if max_price is not None:
        query = query.filter(Property.current_list_price <= max_price)
    if min_beds is not None:
        query = query.filter(Property.beds >= min_beds)
    if min_baths is not None:
        query = query.filter(Property.full_baths >= min_baths)
    if max_sqft_price is not None:
        query = query.filter(Property.price_per_sqft <= max_sqft_price)
    if price_drop_only:
        query = query.filter(Property.is_price_drop == True)
    if foreclosure_only:
        query = query.filter(Property.is_foreclosure == True)
    if source and source != "All":
        query = query.filter(Property.listing_source == source)
    if status:
        query = query.filter(Property.status == status)

    order_col = getattr(Property, sort_by, Property.last_seen_date)
    if sort_dir.lower() == "asc":
        query = query.order_by(asc(order_col))
    else:
        query = query.order_by(desc(order_col))

    return query.offset(offset).limit(limit).all()


def get_property_by_id(session: Session, property_id: int) -> Optional[Property]:
    return session.query(Property).filter(Property.id == property_id).first()


def get_price_history_for_property(session: Session, property_id: int) -> List[PriceHistory]:
    return (
        session.query(PriceHistory)
        .filter(PriceHistory.property_id == property_id)
        .order_by(asc(PriceHistory.event_date))
        .all()
    )


def get_alert_rules(session: Session, active_only: bool = False) -> List[AlertRule]:
    q = session.query(AlertRule)
    if active_only:
        q = q.filter(AlertRule.is_active == True)
    return q.all()


def get_recent_alerts(session: Session, limit: int = 50) -> List[AlertLog]:
    return (
        session.query(AlertLog)
        .order_by(desc(AlertLog.triggered_at))
        .limit(limit)
        .all()
    )


def get_snapshots(session: Session, limit: int = 20) -> List[IngestionSnapshot]:
    return (
        session.query(IngestionSnapshot)
        .order_by(desc(IngestionSnapshot.timestamp))
        .limit(limit)
        .all()
    )

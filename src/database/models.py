"""
SQLAlchemy models for Metro Atlanta Real Estate Price Tracker.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now():
    return datetime.now(timezone.utc)


class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mls_id = Column(String(64), index=True, nullable=True)
    property_url = Column(Text, nullable=True)
    formatted_address = Column(String(255), nullable=False)
    street = Column(String(255), nullable=True)
    unit = Column(String(64), nullable=True)
    city = Column(String(64), index=True, nullable=False)
    state = Column(String(16), default="GA", nullable=False)
    zip_code = Column(String(16), index=True, nullable=False)
    county = Column(String(64), nullable=True)

    beds = Column(Float, nullable=True)
    full_baths = Column(Float, nullable=True)
    half_baths = Column(Float, nullable=True)
    sqft = Column(Float, nullable=True)
    lot_sqft = Column(Float, nullable=True)
    year_built = Column(Integer, nullable=True)
    style = Column(String(64), nullable=True)  # Single Family, Townhouse, Condo
    status = Column(String(32), default="FOR_SALE", index=True)  # FOR_SALE, PENDING, SOLD

    current_list_price = Column(Float, nullable=False)
    initial_list_price = Column(Float, nullable=False)
    price_per_sqft = Column(Float, nullable=True)
    days_on_market = Column(Integer, default=0)
    hoa_fee = Column(Float, nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    primary_photo = Column(Text, nullable=True)

    first_seen_date = Column(DateTime, default=utc_now, nullable=False)
    last_seen_date = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    last_status_change_date = Column(DateTime, nullable=True)

    is_price_drop = Column(Boolean, default=False, index=True)
    price_drop_pct = Column(Float, default=0.0)
    price_drop_amount = Column(Float, default=0.0)

    is_foreclosure = Column(Boolean, default=False, index=True)
    listing_source = Column(String(64), default="MLS/Realtor", index=True)

    # Relationships
    price_history = relationship("PriceHistory", back_populates="property", cascade="all, delete-orphan", order_by="PriceHistory.event_date.asc()")
    alert_logs = relationship("AlertLog", back_populates="property", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_props_city_zip", "city", "zip_code"),
        Index("ix_props_price_sqft", "current_list_price", "price_per_sqft"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "mls_id": self.mls_id,
            "property_url": self.property_url,
            "formatted_address": self.formatted_address,
            "street": self.street,
            "unit": self.unit,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "county": self.county,
            "beds": self.beds,
            "full_baths": self.full_baths,
            "half_baths": self.half_baths,
            "sqft": self.sqft,
            "lot_sqft": self.lot_sqft,
            "year_built": self.year_built,
            "style": self.style,
            "status": self.status,
            "current_list_price": self.current_list_price,
            "initial_list_price": self.initial_list_price,
            "price_per_sqft": self.price_per_sqft,
            "days_on_market": self.days_on_market,
            "hoa_fee": self.hoa_fee,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "primary_photo": self.primary_photo,
            "first_seen_date": self.first_seen_date.isoformat() if self.first_seen_date else None,
            "last_seen_date": self.last_seen_date.isoformat() if self.last_seen_date else None,
            "is_price_drop": self.is_price_drop,
            "price_drop_pct": self.price_drop_pct,
            "price_drop_amount": self.price_drop_amount,
            "is_foreclosure": bool(self.is_foreclosure),
            "listing_source": self.listing_source or "MLS/Realtor",
        }


class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    price = Column(Float, nullable=False)
    price_per_sqft = Column(Float, nullable=True)
    event_type = Column(String(32), default="listed")  # listed, price_drop, price_increase, pending, sold
    event_date = Column(DateTime, default=utc_now, nullable=False, index=True)
    note = Column(String(255), nullable=True)

    property = relationship("Property", back_populates="price_history")

    def to_dict(self):
        return {
            "id": self.id,
            "property_id": self.property_id,
            "price": self.price,
            "price_per_sqft": self.price_per_sqft,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "note": self.note
        }


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    min_price_drop_pct = Column(Float, nullable=True)  # e.g. 5.0 for >5% drop
    max_price_per_sqft = Column(Float, nullable=True)  # e.g. 220.0 for sub-$220/sqft
    cities = Column(String(255), nullable=True)        # comma-separated
    zip_codes = Column(String(255), nullable=True)     # comma-separated
    max_price = Column(Float, nullable=True)
    min_beds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    alert_logs = relationship("AlertLog", back_populates="rule", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "is_active": self.is_active,
            "min_price_drop_pct": self.min_price_drop_pct,
            "max_price_per_sqft": self.max_price_per_sqft,
            "cities": [c.strip() for c in self.cities.split(",")] if self.cities else [],
            "zip_codes": [z.strip() for z in self.zip_codes.split(",")] if self.zip_codes else [],
            "max_price": self.max_price,
            "min_beds": self.min_beds,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    triggered_at = Column(DateTime, default=utc_now, nullable=False, index=True)
    message = Column(String(255), nullable=False)
    status = Column(String(32), default="active")  # active, archived, dismissed

    rule = relationship("AlertRule", back_populates="alert_logs")
    property = relationship("Property", back_populates="alert_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "property_id": self.property_id,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "message": self.message,
            "status": self.status
        }


class IngestionSnapshot(Base):
    __tablename__ = "ingestion_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    source = Column(String(64), default="homeharvest_realtor")
    records_ingested = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    alerts_triggered = Column(Integer, default=0)
    notes = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": self.source,
            "records_ingested": self.records_ingested,
            "records_updated": self.records_updated,
            "alerts_triggered": self.alerts_triggered,
            "notes": self.notes
        }


class RentalListing(Base):
    __tablename__ = "rental_listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(String(64), index=True, nullable=True)
    property_url = Column(Text, nullable=True)
    formatted_address = Column(String(255), nullable=False)
    street = Column(String(255), nullable=True)
    unit = Column(String(64), nullable=True)
    city = Column(String(64), index=True, nullable=False)
    state = Column(String(16), default="GA", nullable=False)
    zip_code = Column(String(16), index=True, nullable=False)
    county = Column(String(64), nullable=True)

    beds = Column(Float, nullable=True)
    full_baths = Column(Float, nullable=True)
    half_baths = Column(Float, nullable=True)
    sqft = Column(Float, nullable=True)
    style = Column(String(64), default="APARTMENT")  # APARTMENT, TOWNHOMES, CONDO, SINGLE_FAMILY

    monthly_rent = Column(Float, nullable=False)  # Representative or average monthly rent
    rent_min = Column(Float, nullable=True)
    rent_max = Column(Float, nullable=True)
    rent_per_sqft = Column(Float, nullable=True)
    days_on_market = Column(Integer, default=0)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    primary_photo = Column(Text, nullable=True)
    listing_source = Column(String(64), default="Realtor Rentals", index=True)

    first_seen_date = Column(DateTime, default=utc_now, nullable=False)
    last_seen_date = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index("ix_rentals_city_zip", "city", "zip_code"),
        Index("ix_rentals_rent_beds", "monthly_rent", "beds"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "property_id": self.property_id,
            "property_url": self.property_url,
            "formatted_address": self.formatted_address,
            "street": self.street,
            "unit": self.unit,
            "city": self.city,
            "state": self.state,
            "zip_code": self.zip_code,
            "county": self.county,
            "beds": self.beds,
            "full_baths": self.full_baths,
            "half_baths": self.half_baths,
            "sqft": self.sqft,
            "style": self.style or "APARTMENT",
            "monthly_rent": self.monthly_rent,
            "rent_min": self.rent_min,
            "rent_max": self.rent_max,
            "rent_per_sqft": self.rent_per_sqft,
            "days_on_market": self.days_on_market,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "primary_photo": self.primary_photo,
            "listing_source": self.listing_source or "Realtor Rentals",
            "first_seen_date": self.first_seen_date.isoformat() if self.first_seen_date else None,
            "last_seen_date": self.last_seen_date.isoformat() if self.last_seen_date else None,
        }

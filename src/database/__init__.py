"""Database package initialization."""
from src.database.models import Base, Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot, RentalListing
from src.database.connection import init_db, get_session, get_db, get_duckdb_conn, engine
from src.database.repository import query_properties, get_property_by_id, get_price_history_for_property

__all__ = [
    "Base",
    "Property",
    "PriceHistory",
    "AlertRule",
    "AlertLog",
    "IngestionSnapshot",
    "RentalListing",
    "init_db",
    "get_session",
    "get_db",
    "get_duckdb_conn",
    "engine",
    "query_properties",
    "get_property_by_id",
    "get_price_history_for_property",
]

"""
Database connection, session management, and DuckDB analytics connector.
"""

import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
import duckdb

from src.config import DB_PATH, DATA_DIR
from src.database.models import Base, AlertRule


def get_sqlite_url() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


engine = create_engine(
    get_sqlite_url(),
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables in SQLite database, auto-migrate new columns, and seed default alert rules."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # Auto-migrate columns if missing in existing SQLite database
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        existing_cols = [r[1] for r in c.execute("PRAGMA table_info(properties)").fetchall()]
        if "is_foreclosure" not in existing_cols:
            c.execute("ALTER TABLE properties ADD COLUMN is_foreclosure BOOLEAN DEFAULT 0")
        if "listing_source" not in existing_cols:
            c.execute("ALTER TABLE properties ADD COLUMN listing_source VARCHAR(64) DEFAULT 'MLS/Realtor'")
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Seed default alert rules if none exist
    with get_session() as session:
        count = session.query(AlertRule).count()
        if count == 0:
            rule1 = AlertRule(
                name="Steep Price Cut (>5% reduction)",
                is_active=True,
                min_price_drop_pct=5.0,
                max_price_per_sqft=None,
                cities=None,
                zip_codes=None
            )
            rule2 = AlertRule(
                name="Deep Value Bargain (Sub-$220/sqft)",
                is_active=True,
                min_price_drop_pct=None,
                max_price_per_sqft=220.0,
                cities=None,
                zip_codes=None
            )
            rule3 = AlertRule(
                name="Duluth & Suwanee Core Deal (Drop > 3% or Sub-$240/sqft)",
                is_active=True,
                min_price_drop_pct=3.0,
                max_price_per_sqft=240.0,
                cities="Duluth,Suwanee",
                zip_codes="30096,30097,30024"
            )
            session.add_all([rule1, rule2, rule3])
            session.commit()


@contextmanager
def get_session():
    """Context manager for SQLAlchemy database session."""
    session: Session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency for DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_duckdb_conn():
    """
    Get a DuckDB connection attached directly to tracker.db for analytical OLAP queries.
    DuckDB can query SQLite files with ultra-fast vectorization.
    """
    conn = duckdb.connect()
    # Install and load sqlite extension in DuckDB
    try:
        conn.execute(f"ATTACH '{DB_PATH}' AS tracker (TYPE SQLITE);")
    except Exception:
        # Fallback if already attached or path handled
        pass
    return conn

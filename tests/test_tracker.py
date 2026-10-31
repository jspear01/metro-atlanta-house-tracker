"""
Automated unit and integration test suite for Metro Atlanta Real Estate Price Tracker.
"""

import pytest
from fastapi.testclient import TestClient

from src.database.connection import init_db, get_session
from src.database.models import Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot
from src.database.repository import query_properties, get_property_by_id
from src.ingestion.pipeline import run_pipeline, ingest_records, evaluate_property_alerts
from src.analytics.metrics import get_properties_dataframe, compute_executive_kpis, compute_submarket_breakdown
from src.backend.main import app


def _cleanup_test_data():
    with get_session() as session:
        test_props = session.query(Property).filter(Property.mls_id.like("TEST%")).all()
        if test_props:
            ids = [p.id for p in test_props]
            session.query(PriceHistory).filter(PriceHistory.property_id.in_(ids)).delete(synchronize_session=False)
            session.query(AlertLog).filter(AlertLog.property_id.in_(ids)).delete(synchronize_session=False)
            session.query(Property).filter(Property.id.in_(ids)).delete(synchronize_session=False)
        session.query(IngestionSnapshot).filter(IngestionSnapshot.source.like("test%")).delete(synchronize_session=False)
        session.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_and_teardown_test_db():
    init_db()
    _cleanup_test_data()
    yield
    _cleanup_test_data()


def test_database_initialization():
    with get_session() as session:
        rules = session.query(AlertRule).all()
        assert len(rules) >= 3, "Default alert rules should be seeded on initialization"


def test_pipeline_ingestion_and_deduplication():
    # Remove leftovers from previous runs so the test is repeatable
    with get_session() as session:
        session.query(Property).filter(Property.mls_id == "TEST-MLS-9999").delete()
        session.commit()

    # Test synthetic record
    sample_records = [
        {
            "mls_id": "TEST-MLS-9999",
            "property_url": "https://example.com/prop1",
            "formatted_address": "123 Peachtree Industrial Blvd, Duluth, GA 30096",
            "street": "123 Peachtree Industrial Blvd",
            "city": "Duluth",
            "state": "GA",
            "zip_code": "30096",
            "beds": 4.0,
            "full_baths": 3.0,
            "sqft": 2500.0,
            "style": "Single Family",
            "current_list_price": 500000.0,
            "initial_list_price": 500000.0,
            "price_per_sqft": 200.0,
            "days_on_market": 10,
            "is_price_drop": False
        }
    ]

    # Ingest record
    res1 = ingest_records(sample_records, source_name="test")
    assert res1["inserted"] == 1, "Should insert 1 new property"

    # Second ingestion with price reduction
    sample_records[0]["current_list_price"] = 475000.0  # 5% price cut
    res2 = ingest_records(sample_records, source_name="test")
    assert res2["inserted"] == 0, "Should deduplicate existing property"
    assert res2["updated"] == 1, "Should update existing property"

    with get_session() as session:
        prop = session.query(Property).filter(Property.mls_id == "TEST-MLS-9999").first()
        assert prop is not None
        assert prop.current_list_price == 475000.0
        assert prop.is_price_drop is True
        assert prop.price_drop_pct == 5.0
        assert prop.price_drop_amount == 25000.0


def test_analytics_kpi_computation():
    df = get_properties_dataframe()
    assert not df.empty, "Properties dataframe should not be empty"

    kpis = compute_executive_kpis(df)
    assert kpis["total_inventory"] > 0
    assert kpis["median_price"] > 0
    assert kpis["median_sqft_price"] > 0

    submarket_breakdown = compute_submarket_breakdown(df)
    assert not submarket_breakdown.empty
    assert "city" in submarket_breakdown.columns


def test_fastapi_rest_endpoints():
    client = TestClient(app)

    # Health check
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # Submarkets
    res_sub = client.get("/api/submarkets")
    assert res_sub.status_code == 200
    assert "Duluth" in res_sub.json()["submarkets"]

    # Properties list
    res_props = client.get("/api/properties?limit=5")
    assert res_props.status_code == 200
    assert isinstance(res_props.json(), list)

    # KPIs endpoint
    res_kpis = client.get("/api/analytics/kpis")
    assert res_kpis.status_code == 200
    assert res_kpis.json()["total_inventory"] > 0

    # Alerts list
    res_alerts = client.get("/api/alerts")
    assert res_alerts.status_code == 200
    assert isinstance(res_alerts.json(), list)

    # Foreclosure filter endpoint test
    res_fc = client.get("/api/properties?foreclosure_only=true")
    assert res_fc.status_code == 200
    assert isinstance(res_fc.json(), list)


def test_foreclosure_model_and_query():
    # Insert a test foreclosure record
    sample_fc = [
        {
            "mls_id": "TEST-FC-1001",
            "property_url": "https://example.com/fc1",
            "formatted_address": "456 Foreclosure Way, Duluth, GA 30096",
            "street": "456 Foreclosure Way",
            "city": "Duluth",
            "state": "GA",
            "zip_code": "30096",
            "beds": 3.0,
            "full_baths": 2.0,
            "sqft": 1800.0,
            "style": "Single Family",
            "current_list_price": 280000.0,
            "initial_list_price": 310000.0,
            "price_per_sqft": 155.56,
            "days_on_market": 45,
            "is_price_drop": True,
            "price_drop_pct": 9.68,
            "price_drop_amount": 30000.0,
            "is_foreclosure": True,
            "listing_source": "Foreclosure/REO"
        }
    ]
    ingest_records(sample_fc, source_name="test_foreclosure")

    with get_session() as session:
        props = query_properties(session, foreclosure_only=True)
        assert len(props) >= 1
        test_prop = next((p for p in props if p.mls_id == "TEST-FC-1001"), None)
        assert test_prop is not None
        assert test_prop.is_foreclosure is True
        assert test_prop.listing_source == "Foreclosure/REO"



def test_redfin_and_auction_sources_ingestion():
    # Ingest synthetic records matching Redfin and Auction schemas
    test_records = [
        {
            "mls_id": "TEST-RDF-001",
            "property_url": "https://www.redfin.com/GA/Duluth/test/home/12345",
            "formatted_address": "789 Redfin Trace, Duluth, GA 30096",
            "street": "789 Redfin Trace",
            "city": "Duluth",
            "state": "GA",
            "zip_code": "30096",
            "beds": 4.0,
            "full_baths": 3.0,
            "sqft": 2400.0,
            "style": "Single Family Residential",
            "current_list_price": 420000.0,
            "initial_list_price": 420000.0,
            "price_per_sqft": 175.0,
            "days_on_market": 12,
            "is_price_drop": False,
            "is_foreclosure": False,
            "listing_source": "Redfin Open Data"
        },
        {
            "mls_id": "TEST-AUC-001",
            "property_url": "https://www.auction.com/residential/ga/duluth/",
            "formatted_address": "100 Courthouse Steps Way, Duluth, GA 30096",
            "street": "100 Courthouse Steps Way",
            "city": "Duluth",
            "state": "GA",
            "zip_code": "30096",
            "beds": 3.0,
            "full_baths": 2.0,
            "sqft": 1900.0,
            "style": "Single Family",
            "current_list_price": 245000.0,
            "initial_list_price": 245000.0,
            "price_per_sqft": 128.95,
            "days_on_market": 0,
            "is_price_drop": False,
            "is_foreclosure": True,
            "listing_source": "Auction / Legal Notice"
        }
    ]

    res = ingest_records(test_records, source_name="test_options")
    assert res["inserted"] == 2

    with get_session() as session:
        rdf_prop = session.query(Property).filter(Property.mls_id == "TEST-RDF-001").first()
        assert rdf_prop is not None
        assert rdf_prop.listing_source == "Redfin Open Data"
        assert not rdf_prop.is_foreclosure

        auc_prop = session.query(Property).filter(Property.mls_id == "TEST-AUC-001").first()
        assert auc_prop is not None
        assert auc_prop.listing_source == "Auction / Legal Notice"
        assert auc_prop.is_foreclosure is True

        # Test querying by source
        source_filtered = query_properties(session, source="Auction / Legal Notice")
        assert any(p.mls_id == "TEST-AUC-001" for p in source_filtered)


def test_historical_distress_trends_ingestion_and_analytics():
    from src.ingestion.distress_trends import (
        fetch_historical_eviction_filings,
        fetch_historical_mortgage_delinquency
    )
    from src.analytics.metrics import (
        compute_eviction_metrics,
        compute_mortgage_delinquency_metrics
    )

    # 1. Test Eviction Filings Ingestion & KPIs
    df_ev = fetch_historical_eviction_filings()
    assert not df_ev.empty, "Eviction filings dataframe should not be empty"
    assert "filings" in df_ev.columns
    assert "date" in df_ev.columns

    ev_kpis = compute_eviction_metrics(df_ev)
    assert ev_kpis["latest_month_filings"] > 0
    assert ev_kpis["recent_12m_filings"] > 0
    assert "status_summary" in ev_kpis

    # 2. Test CFPB Mortgage Delinquency Ingestion & KPIs
    df_mort = fetch_historical_mortgage_delinquency()
    assert not df_mort.empty, "Mortgage delinquency dataframe should not be empty"
    assert "late_90_plus_pct" in df_mort.columns
    assert "county" in df_mort.columns

    mort_kpis = compute_mortgage_delinquency_metrics(df_mort)
    assert "Gwinnett County" in mort_kpis
    assert "Fulton County" in mort_kpis
    assert mort_kpis["Gwinnett County"]["current_90_plus_late_pct"] > 0


def test_compute_price_drop_summary_velocity():
    from src.analytics.metrics import compute_price_drop_summary
    from src.database.connection import get_session
    from src.ingestion.pipeline import ingest_records

    # Ingest a test listing with price drop
    drop_record = {
        "mls_id": "TEST-DROP-999",
        "formatted_address": "999 Slashed Price Blvd, Duluth, GA 30096",
        "city": "Duluth",
        "state": "GA",
        "zip_code": "30096",
        "beds": 4.0,
        "full_baths": 3.0,
        "sqft": 2500.0,
        "current_list_price": 450000.0,
        "initial_list_price": 500000.0,
        "price_per_sqft": 180.0,
        "days_on_market": 25,
        "is_price_drop": True,
        "price_drop_pct": 10.0,
        "price_drop_amount": 50000.0,
        "listing_source": "MLS/Realtor"
    }
    ingest_records([drop_record], source_name="test_drop")

    with get_session() as session:
        summary = compute_price_drop_summary(session, cities=["Duluth"])
        assert summary["kpis"]["total_deals"] >= 1
        assert summary["kpis"]["avg_drop_amount"] > 0
        assert summary["kpis"]["avg_drop_pct"] > 0

        target = next((d for d in summary["deals"] if d["mls_id"] == "TEST-DROP-999"), None)
        assert target is not None
        assert target["drop_amount"] == 50000.0
        assert target["drop_pct"] == 10.0
        assert target["days_to_drop"] > 0
        assert "velocity_tag" in target


def test_rental_pipeline_and_repository():
    from src.database.models import RentalListing
    from src.ingestion.pipeline import ingest_rental_records
    from src.database.repository import get_rentals_dataframe

    # Clean up test rental
    with get_session() as session:
        session.query(RentalListing).filter(RentalListing.property_id == "TEST-RENTAL-001").delete()
        session.commit()

    sample_rental = [
        {
            "property_id": "TEST-RENTAL-001",
            "property_url": "https://www.realtor.com/apartments/test-001",
            "formatted_address": "456 Test Apt Blvd Unit 101, Duluth, GA 30096",
            "street": "456 Test Apt Blvd",
            "unit": "101",
            "city": "Duluth",
            "state": "GA",
            "zip_code": "30096",
            "county": "Gwinnett",
            "beds": 2.0,
            "full_baths": 2.0,
            "sqft": 1100.0,
            "style": "APARTMENT",
            "monthly_rent": 1850.0,
            "rent_min": 1750.0,
            "rent_max": 1950.0,
            "days_on_market": 5,
            "listing_source": "Realtor Rentals"
        }
    ]

    res = ingest_rental_records(sample_rental, source_name="test_rentals")
    assert res["status"] == "success"
    assert res["inserted"] == 1

    # Query via repository dataframe
    df = get_rentals_dataframe(cities=["Duluth"], min_beds=2)
    assert not df.empty
    match = df[df["property_id"] == "TEST-RENTAL-001"]
    assert len(match) == 1
    assert match.iloc[0]["monthly_rent"] == 1850.0
    assert match.iloc[0]["rent_per_sqft"] == round(1850.0 / 1100.0, 2)

    # Cleanup
    with get_session() as session:
        session.query(RentalListing).filter(RentalListing.property_id == "TEST-RENTAL-001").delete()
        session.commit()


if __name__ == "__main__":
    pytest.main(["-v", __file__])


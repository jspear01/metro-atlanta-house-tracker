"""
Ingestion module for historical macro distress indicators:
1. Fulton County / Metro Atlanta Eviction Filings (Socrata Open Data API)
2. CFPB Mortgage Performance Trends (County-level 30-89 & 90+ days delinquent rates)
"""

import io
import logging
import requests
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
EVICTION_API_URL = "https://data.fultoncountyga.gov/resource/cbu2-qs5w.json?$limit=5000&$order=monthdate ASC"
CFPB_90_PLUS_URL = "https://files.consumerfinance.gov/data/mortgage-performance/downloads/CountyMortgagesPercent-90-plusDaysLate-thru-2025-12.csv"
CFPB_30_89_URL = "https://files.consumerfinance.gov/data/mortgage-performance/downloads/CountyMortgagesPercent-30-89DaysLate-thru-2025-12.csv"

TARGET_COUNTIES = ["Gwinnett County", "Fulton County", "DeKalb County", "Cobb County", "Forsyth County"]

# Citable metadata for every external dataset shown on the distress dashboard
DATA_SOURCES: Dict[str, Dict[str, str]] = {
    "evictions": {
        "name": "Fulton County Eviction (Dispossessory) Filings",
        "publisher": "Fulton County Open Data Portal",
        "page_url": "https://data.fultoncountyga.gov/d/cbu2-qs5w",
        "api_url": "https://data.fultoncountyga.gov/resource/cbu2-qs5w.json",
        "coverage": "Fulton County only · monthly filings",
        "frequency": "Monthly",
        "notes": "Counts court filings, not completed evictions. Gwinnett/DeKalb/Cobb are not included.",
    },
    "mortgage_delinquency": {
        "name": "Mortgage Performance Trends (90+ & 30–89 Days Delinquent)",
        "publisher": "Consumer Financial Protection Bureau (CFPB) · National Mortgage Database",
        "page_url": "https://www.consumerfinance.gov/data-research/mortgage-performance-trends/",
        "api_url": "https://www.consumerfinance.gov/data-research/mortgage-performance-trends/download-the-data/",
        "coverage": "Gwinnett, Fulton, DeKalb, Cobb, Forsyth counties · monthly",
        "frequency": "Quarterly releases (monthly series)",
        "notes": "Share of mortgages 90+ days late — a leading indicator of the foreclosure pipeline, not a count of foreclosure filings.",
    },
    "ga_legal_notices": {
        "name": "Georgia Trustee Foreclosure & Courthouse Auction Notices",
        "publisher": "Rubin Lublin, LLC (RLSE Law) & Auction.com",
        "page_url": "https://rlselaw.com/property-listing/georgia-property-listings/",
        "api_url": "https://www.auction.com/search/residential/ga/",
        "coverage": "Fulton, Gwinnett, Cobb, DeKalb, Forsyth & Metro Atlanta counties",
        "frequency": "Continuous / Weekly updates",
        "notes": "Official non-judicial foreclosure auction notices advertised pursuant to Georgia law prior to first-Tuesday courthouse auctions.",
    },
}

# Records whether each dataset was last loaded from the live endpoint or the local cache
FETCH_STATUS: Dict[str, str] = {"evictions": "unavailable", "mortgage_delinquency": "unavailable"}


def fetch_historical_eviction_filings() -> pd.DataFrame:
    """
    Fetches monthly eviction (dispossessory) filings from the Fulton County
    Open Data Portal (Superior & Magistrate Courts).
    Returns DataFrame with columns: ['date', 'year', 'month', 'filings', 'source']
    """
    cache_file = CACHE_DIR / "eviction_filings_cache.csv"
    try:
        resp = requests.get(EVICTION_API_URL, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                df = pd.DataFrame(data)
                df["date"] = pd.to_datetime(df["monthdate"])
                df["year"] = df["date"].dt.year
                df["month"] = df["date"].dt.strftime("%Y-%m")
                df["filings"] = pd.to_numeric(df["filings"], errors="coerce").fillna(0).astype(int)
                df["county"] = "Fulton County"
                df["source"] = "Fulton County Magistrate & Superior Courts"
                df = df.sort_values("date").reset_index(drop=True)
                
                # Save cache
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                df[["date", "year", "month", "filings", "county", "source"]].to_csv(cache_file, index=False)
                logger.info(f"Successfully fetched {len(df)} monthly eviction records from Fulton Socrata API.")
                FETCH_STATUS["evictions"] = "live"
                return df
    except Exception as ex:
        logger.warning(f"Failed to fetch live eviction filings from API: {ex}")

    # Fallback to cache if available
    if cache_file.exists():
        logger.info("Loading eviction filings from local cache.")
        df = pd.read_csv(cache_file)
        df["date"] = pd.to_datetime(df["date"])
        FETCH_STATUS["evictions"] = "cache"
        return df

    return pd.DataFrame(columns=["date", "year", "month", "filings", "county", "source"])


def fetch_historical_mortgage_delinquency() -> pd.DataFrame:
    """
    Fetches CFPB Mortgage Performance Trends county-level time-series (2008-2025)
    for Metro Atlanta target counties: Gwinnett, Fulton, DeKalb, Cobb, Forsyth.
    Returns clean long-form DataFrame with:
    ['county', 'date', 'year', 'late_90_plus_pct', 'late_30_89_pct']
    """
    cache_file = CACHE_DIR / "mortgage_delinquency_cache.csv"

    try:
        # Fetch 90+ days late (serious delinquency / foreclosure pipeline)
        r90 = requests.get(CFPB_90_PLUS_URL, timeout=15)
        r30 = requests.get(CFPB_30_89_URL, timeout=15)

        if r90.status_code == 200 and r30.status_code == 200:
            df90_raw = pd.read_csv(io.StringIO(r90.text))
            df30_raw = pd.read_csv(io.StringIO(r30.text))

            # Filter to GA target counties
            df90_ga = df90_raw[(df90_raw["State"] == "GA") & (df90_raw["Name"].isin(TARGET_COUNTIES))].copy()
            df30_ga = df30_raw[(df30_raw["State"] == "GA") & (df30_raw["Name"].isin(TARGET_COUNTIES))].copy()

            id_vars = ["RegionType", "State", "Name", "FIPSCode"]
            date_cols = [c for c in df90_ga.columns if c not in id_vars]

            # Melt wide format to long format
            m90 = df90_ga.melt(id_vars=id_vars, value_vars=date_cols, var_name="month", value_name="late_90_plus_pct")
            m30 = df30_ga.melt(id_vars=id_vars, value_vars=date_cols, var_name="month", value_name="late_30_89_pct")

            merged = pd.merge(m90, m30[["Name", "month", "late_30_89_pct"]], on=["Name", "month"], how="left")
            merged["county"] = merged["Name"]
            merged["date"] = pd.to_datetime(merged["month"] + "-01")
            merged["year"] = merged["date"].dt.year
            merged["late_90_plus_pct"] = pd.to_numeric(merged["late_90_plus_pct"], errors="coerce")
            merged["late_30_89_pct"] = pd.to_numeric(merged["late_30_89_pct"], errors="coerce")

            clean_df = merged[["county", "date", "year", "month", "late_90_plus_pct", "late_30_89_pct"]].sort_values(
                ["county", "date"]
            ).reset_index(drop=True)

            # Cache to disk
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            clean_df.to_csv(cache_file, index=False)
            logger.info(f"Successfully processed {len(clean_df)} CFPB mortgage delinquency records.")
            FETCH_STATUS["mortgage_delinquency"] = "live"
            return clean_df

    except Exception as ex:
        logger.warning(f"Error fetching CFPB mortgage delinquency data: {ex}")

    # Fallback to cache if available
    if cache_file.exists():
        logger.info("Loading CFPB delinquency data from local cache.")
        df = pd.read_csv(cache_file)
        df["date"] = pd.to_datetime(df["date"])
        FETCH_STATUS["mortgage_delinquency"] = "cache"
        return df

    return pd.DataFrame(columns=["county", "date", "year", "month", "late_90_plus_pct", "late_30_89_pct"])

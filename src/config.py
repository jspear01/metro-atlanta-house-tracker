"""
Configuration and submarket definitions for Metro Atlanta Real Estate Price Tracker.
"""

from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "tracker.db"
STATE_DIR = PROJECT_ROOT / ".state"

# Target Submarkets in Gwinnett & North Fulton (and adjacent northern areas)
TARGET_SUBMARKETS = {
    "Duluth": {
        "county": "Gwinnett",
        "zip_codes": ["30096", "30097"],
        "center": {"lat": 34.0029, "lon": -84.1446}
    },
    "Suwanee": {
        "county": "Gwinnett",
        "zip_codes": ["30024"],
        "center": {"lat": 34.0526, "lon": -84.0713}
    },
    "Norcross": {
        "county": "Gwinnett",
        "zip_codes": ["30071", "30092", "30093"],
        "center": {"lat": 33.9412, "lon": -84.2135}
    },
    "Peachtree Corners": {
        "county": "Gwinnett",
        "zip_codes": ["30092"],
        "center": {"lat": 33.9698, "lon": -84.2215}
    },
    "Johns Creek": {
        "county": "Fulton",
        "zip_codes": ["30005", "30022"],
        "center": {"lat": 34.0289, "lon": -84.1986}
    },
    "Alpharetta": {
        "county": "Fulton",
        "zip_codes": ["30004", "30009", "30022"],
        "center": {"lat": 34.0754, "lon": -84.2941}
    },
    "Cumming": {
        "county": "Forsyth",
        "zip_codes": ["30040", "30041"],
        "center": {"lat": 34.2073, "lon": -84.1402}
    },
    "Dunwoody": {
        "county": "DeKalb",
        "zip_codes": ["30338", "30346", "30360"],
        "center": {"lat": 33.9462, "lon": -84.3346}
    },
    "Brookhaven": {
        "county": "DeKalb",
        "zip_codes": ["30319", "30329", "30341"],
        "center": {"lat": 33.8651, "lon": -84.3366}
    },
    "Buckhead": {
        "county": "Fulton",
        "zip_codes": ["30305", "30324", "30326", "30327", "30342"],
        "center": {"lat": 33.8395, "lon": -84.3792}
    }
}

# Map each target ZIP to its canonical submarket & county
ZIP_TO_SUBMARKET = {
    z: sm_name
    for sm_name, sm in TARGET_SUBMARKETS.items()
    for z in sm["zip_codes"]
}
ZIP_TO_COUNTY = {
    z: sm["county"]
    for sm in TARGET_SUBMARKETS.values()
    for z in sm["zip_codes"]
}

ALL_ZIP_CODES = sorted(list({z for sm in TARGET_SUBMARKETS.values() for z in sm["zip_codes"]}))
ALL_CITIES = sorted(list(TARGET_SUBMARKETS.keys()))

# Ingestion configuration
DEFAULT_RATE_LIMIT_MIN_SEC = 1.5
DEFAULT_RATE_LIMIT_MAX_SEC = 3.0

# Price alert thresholds
DEFAULT_PRICE_DROP_THRESHOLD_PCT = 5.0
DEFAULT_BARGAIN_SQFT_PRICE = 220.0

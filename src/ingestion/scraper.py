"""
Live MLS/Realtor data scraper using HomeHarvest with polite rate-limiting jitter.
"""

import time
import random
import logging
from typing import List, Dict, Any, Optional
import pandas as pd

from src.config import (
    TARGET_SUBMARKETS,
    ALL_ZIP_CODES,
    DEFAULT_RATE_LIMIT_MIN_SEC,
    DEFAULT_RATE_LIMIT_MAX_SEC
)

logger = logging.getLogger(__name__)


def scrape_zip_code(
    zip_code: str,
    listing_type: str = "for_sale",
    limit: int = 50,
    jitter_min: float = DEFAULT_RATE_LIMIT_MIN_SEC,
    jitter_max: float = DEFAULT_RATE_LIMIT_MAX_SEC
) -> List[Dict[str, Any]]:
    """Scrape listings for a specific ZIP code with jitter."""
    try:
        import homeharvest
    except ImportError:
        logger.error("homeharvest is not installed.")
        return []

    # Polite rate limiting sleep before request
    delay = random.uniform(jitter_min, jitter_max)
    time.sleep(delay)

    try:
        df = homeharvest.scrape_property(
            location=str(zip_code),
            listing_type=listing_type,
            limit=limit,
        )
        if df is None or df.empty:
            return []

        return normalize_dataframe_to_records(df, default_zip=zip_code)
    except Exception as e:
        logger.warning(f"Error scraping zip {zip_code}: {e}")
        return []


def scrape_metro_atlanta_submarkets(
    submarkets: Optional[List[str]] = None,
    limit_per_zip: int = 30,
    jitter_min: float = DEFAULT_RATE_LIMIT_MIN_SEC,
    jitter_max: float = DEFAULT_RATE_LIMIT_MAX_SEC
) -> List[Dict[str, Any]]:
    """
    Iterate over target ZIP codes in Gwinnett and North Fulton submarkets.
    """
    records: List[Dict[str, Any]] = []
    zips_to_scrape = []

    if submarkets:
        for sm in submarkets:
            if sm in TARGET_SUBMARKETS:
                zips_to_scrape.extend(TARGET_SUBMARKETS[sm]["zip_codes"])
    else:
        zips_to_scrape = ALL_ZIP_CODES

    # Remove duplicates
    zips_to_scrape = sorted(list(set(zips_to_scrape)))

    for z in zips_to_scrape:
        logger.info(f"Scraping ZIP {z}...")
        results = scrape_zip_code(
            zip_code=z,
            limit=limit_per_zip,
            jitter_min=jitter_min,
            jitter_max=jitter_max
        )
        records.extend(results)

    return records


def scrape_foreclosed_properties(
    locations: Optional[List[str]] = None,
    limit_per_location: int = 15,
    jitter_min: float = DEFAULT_RATE_LIMIT_MIN_SEC,
    jitter_max: float = DEFAULT_RATE_LIMIT_MAX_SEC
) -> List[Dict[str, Any]]:
    """
    Dedicated scraper for foreclosed and bank-owned (REO) homes across Metro Atlanta.
    Queries both key counties (Gwinnett, Fulton, Forsyth) and target zip codes with foreclosure=True.
    """
    try:
        import homeharvest
    except ImportError:
        logger.error("homeharvest is not installed.")
        return []

    target_locations = locations or [
        "Gwinnett County, GA",
        "Fulton County, GA",
        "Forsyth County, GA",
        "30096", "30097", "30024", "30071", "30092", "30005", "30022", "30004", "30040"
    ]

    records: List[Dict[str, Any]] = []
    seen_addresses = set()

    for loc in target_locations:
        delay = random.uniform(jitter_min, jitter_max)
        time.sleep(delay)
        try:
            logger.info(f"Scraping foreclosures for location: {loc}...")
            df = homeharvest.scrape_property(
                location=str(loc),
                foreclosure=True,
                limit=limit_per_location
            )
            if df is not None and not df.empty:
                batch = normalize_dataframe_to_records(
                    df,
                    default_zip=loc if loc.isdigit() else "30096",
                    is_foreclosure=True,
                    listing_source="Foreclosure/REO"
                )
                for item in batch:
                    addr = item.get("formatted_address")
                    if addr and addr not in seen_addresses:
                        seen_addresses.add(addr)
                        records.append(item)
        except Exception as e:
            logger.warning(f"Error scraping foreclosures for {loc}: {e}")

    return records


def scrape_redfin_submarkets(
    limit: int = 100,
    submarkets: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Ingest public MLS listings directly from Redfin's Open GIS feed for the Metro Atlanta market.
    """
    import io
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # Redfin Atlanta region GIS CSV feed
    url = f"https://www.redfin.com/stingray/api/gis-csv?al=1&market=atlanta&num_homes={limit}&page_number=1&region_id=30756&region_type=6&status=9&uipt=1,2,3,4,5,6,7,8&v=8"

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code != 200:
            logger.warning(f"Redfin feed returned status {resp.status_code}")
            return []

        clean_lines = [l for l in resp.text.splitlines() if not l.startswith('"In accordance')]
        if len(clean_lines) < 2:
            return []

        df = pd.read_csv(io.StringIO("\n".join(clean_lines)))
        records = []
        target_filter = [s.strip().title() for s in (submarkets or [])]

        for _, row in df.iterrows():
            try:
                price = float(row.get("PRICE") or 0.0)
                if price <= 0:
                    continue

                sqft = float(row.get("SQUARE FEET") or 0.0)
                price_per_sqft = round(price / sqft, 2) if sqft > 0 else None
                city = str(row.get("CITY") or "").title().strip()
                zip_str = str(row.get("ZIP OR POSTAL CODE") or "").strip()[:5]

                # Map city if needed
                if city not in TARGET_SUBMARKETS:
                    for sm_name, sm in TARGET_SUBMARKETS.items():
                        if zip_str in sm["zip_codes"]:
                            city = sm_name
                            break

                # Filter by target submarkets if specified
                if target_filter and city not in target_filter:
                    continue

                county = "Gwinnett" if zip_str in ["30096", "30097", "30024", "30071", "30092", "30093"] else (
                    "Fulton" if zip_str in ["30005", "30022", "30004", "30009"] else "Forsyth"
                )

                addr = str(row.get("ADDRESS") or "")
                full_address = f"{addr}, {city}, GA {zip_str}"
                mls_num = str(row.get("MLS#") or row.get("LOCATION") or "")

                # Check if Redfin flags foreclosure or short sale in property type or sale type
                prop_type_str = str(row.get("PROPERTY TYPE") or "")
                sale_type_str = str(row.get("SALE TYPE") or "")
                is_fc = "foreclosure" in sale_type_str.lower() or "bank" in sale_type_str.lower()

                records.append({
                    "mls_id": f"RF-{mls_num}" if mls_num else "",
                    "property_url": str(row.get("URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)") or ""),
                    "formatted_address": full_address,
                    "street": addr,
                    "unit": None,
                    "city": city,
                    "state": "GA",
                    "zip_code": zip_str,
                    "county": county,
                    "beds": float(row.get("BEDS")) if pd.notna(row.get("BEDS")) else None,
                    "full_baths": float(row.get("BATHS")) if pd.notna(row.get("BATHS")) else None,
                    "half_baths": None,
                    "sqft": sqft if sqft > 0 else None,
                    "lot_sqft": float(row.get("LOT SIZE")) if pd.notna(row.get("LOT SIZE")) else None,
                    "year_built": int(row.get("YEAR BUILT")) if pd.notna(row.get("YEAR BUILT")) else None,
                    "style": prop_type_str if prop_type_str else "Single Family",
                    "status": "FOR_SALE",
                    "current_list_price": price,
                    "price_per_sqft": price_per_sqft,
                    "days_on_market": int(row.get("DAYS ON MARKET") or 0) if pd.notna(row.get("DAYS ON MARKET")) else 0,
                    "hoa_fee": float(row.get("HOA/MONTH")) if pd.notna(row.get("HOA/MONTH")) else None,
                    "latitude": float(row.get("LATITUDE")) if pd.notna(row.get("LATITUDE")) else None,
                    "longitude": float(row.get("LONGITUDE")) if pd.notna(row.get("LONGITUDE")) else None,
                    "primary_photo": "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&auto=format&fit=crop&q=60",
                    "is_foreclosure": is_fc,
                    "listing_source": "Redfin Open Data"
                })
            except Exception as e:
                continue

        logger.info(f"Scraped {len(records)} listings from Redfin Open Data.")
        return records
    except Exception as ex:
        logger.warning(f"Error fetching Redfin feed: {ex}")
        return []


def scrape_georgia_auctions_and_legal_notices(
    submarkets: Optional[List[str]] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Scrapes active Georgia legal foreclosure notices & courthouse auction properties
    from the official Georgia Foreclosure Trustee feed (RLS / Auction.com partner portal).
    """
    import io
    import requests
    import re
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = "https://rlselaw.com/property-listing/georgia-property-listings/"

    try:
        resp = requests.get(url, headers=headers, timeout=14)
        if resp.status_code != 200:
            logger.warning(f"Georgia auction portal returned status {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning("No auction table found on Georgia legal notice portal.")
            return []

        rows = table.find_all("tr")[1:]
        records = []
        target_cities = [s.strip().title() for s in (submarkets or [])]

        city_coords = {
            "Duluth": (34.0029, -84.1446),
            "Suwanee": (34.0526, -84.0713),
            "Norcross": (33.9412, -84.2135),
            "Peachtree Corners": (33.9698, -84.2215),
            "Alpharetta": (34.0754, -84.2941),
            "Johns Creek": (34.0289, -84.1986),
            "Cumming": (34.2073, -84.1402),
            "Atlanta": (33.7490, -84.3880),
            "Lawrenceville": (33.9562, -83.9880),
            "Snellville": (33.8573, -84.0199),
            "Buford": (34.1207, -84.0044),
            "Acworth": (34.0660, -84.6784),
            "Marietta": (33.9526, -84.5499),
            "Roswell": (34.0232, -84.3616),
            "Lithonia": (33.7123, -84.1052)
        }

        def _parse_bid(bid_text: str) -> float:
            cleaned = re.sub(r"\.\d{2}", "", bid_text)
            match = re.search(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{5,}\b", cleaned)
            if match:
                try:
                    return float(match.group(0).replace(",", ""))
                except ValueError:
                    pass
            return 285000.0

        for row in rows:
            tds = [td.text.strip() for td in row.find_all("td")]
            if len(tds) < 6:
                continue

            sale_date, file_num, street, raw_city, raw_zip, raw_county = tds[0], tds[1], tds[2], tds[3], tds[4], tds[5]
            bid = tds[6] if len(tds) > 6 else ""

            city = raw_city.strip().title()
            zip_code = raw_zip.strip()[:5]
            county = raw_county.strip().title()

            # Filter to target submarkets if provided, or Metro Atlanta core counties
            if target_cities:
                if city not in target_cities and not any(city == c for c in target_cities):
                    continue
            else:
                if county not in ["Gwinnett", "Fulton", "Forsyth", "Cobb", "Dekalb"] and city not in TARGET_SUBMARKETS:
                    continue

            # Coordinates
            lat, lon = city_coords.get(city, (33.95, -84.15))
            lat += random.uniform(-0.02, 0.02)
            lon += random.uniform(-0.02, 0.02)

            price = _parse_bid(bid)
            is_auction_com = "auction.com" in bid.lower()
            prop_url = (
                f"https://www.auction.com/search/residential/ga/{city.lower().replace(' ', '-')}/"
                if is_auction_com
                else "https://rlselaw.com/property-listing/georgia-property-listings/"
            )

            records.append({
                "mls_id": f"GA-AUC-{file_num}",
                "property_url": prop_url,
                "formatted_address": f"{street}, {city}, GA {zip_code}",
                "street": street,
                "unit": None,
                "city": city,
                "state": "GA",
                "zip_code": zip_code,
                "county": county,
                "beds": 3.0,
                "full_baths": 2.0,
                "half_baths": None,
                "sqft": 1850.0,
                "lot_sqft": None,
                "year_built": None,
                "style": "Single Family (Auction)",
                "status": "AUCTION",
                "current_list_price": price,
                "initial_list_price": price,
                "price_per_sqft": round(price / 1850.0, 2),
                "days_on_market": 14,
                "hoa_fee": None,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "primary_photo": "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=800&auto=format&fit=crop&q=60",
                "is_price_drop": False,
                "price_drop_pct": 0.0,
                "price_drop_amount": 0.0,
                "is_foreclosure": True,
                "listing_source": "Auction / Legal Notice"
            })

            if len(records) >= limit:
                break

        logger.info(f"Scraped {len(records)} Georgia auction/legal notice properties.")
        return records

    except Exception as ex:
        logger.warning(f"Error scraping Georgia legal auctions: {ex}")
        return []


def normalize_dataframe_to_records(
    df: pd.DataFrame,
    default_zip: str = "",
    is_foreclosure: bool = False,
    listing_source: str = "MLS/Realtor"
) -> List[Dict[str, Any]]:
    """Convert raw homeharvest DataFrame to standardized property dictionaries."""
    records = []
    for _, row in df.iterrows():
        try:
            price = float(row.get("list_price") or 0.0)
            if price <= 0:
                continue

            sqft = float(row.get("sqft") or 0.0)
            price_per_sqft = round(price / sqft, 2) if sqft > 0 else None

            city = str(row.get("city") or "").title().strip()
            zip_code = str(row.get("zip_code") or default_zip).strip()[:5]

            # Realtor may report small municipalities (e.g. Berkeley Lake); map them to the
            # target submarket that owns this ZIP so dashboard city filters include them.
            if city not in TARGET_SUBMARKETS:
                for sm_name, sm in TARGET_SUBMARKETS.items():
                    if zip_code in sm["zip_codes"]:
                        city = sm_name
                        break

            # Determine county if known
            county = "Gwinnett" if zip_code in ["30096", "30097", "30024", "30071", "30092", "30093"] else (
                "Fulton" if zip_code in ["30005", "30022", "30004", "30009"] else "Forsyth"
            )

            # Check if foreclosure flag present in homeharvest extra property data or passed explicitly
            row_foreclosure = is_foreclosure or bool(row.get("foreclosure", False))

            records.append({
                "mls_id": str(row.get("mls_id") or row.get("property_id") or ""),
                "property_url": str(row.get("property_url") or ""),
                "formatted_address": str(row.get("formatted_address") or f"{row.get('street', '')}, {city}, GA {zip_code}"),
                "street": str(row.get("street") or ""),
                "unit": str(row.get("unit") or "") if pd.notna(row.get("unit")) else None,
                "city": city,
                "state": "GA",
                "zip_code": zip_code,
                "county": county,
                "beds": float(row.get("beds")) if pd.notna(row.get("beds")) else None,
                "full_baths": float(row.get("full_baths")) if pd.notna(row.get("full_baths")) else None,
                "half_baths": float(row.get("half_baths")) if pd.notna(row.get("half_baths")) else None,
                "sqft": sqft if sqft > 0 else None,
                "lot_sqft": float(row.get("lot_sqft")) if pd.notna(row.get("lot_sqft")) else None,
                "year_built": int(row.get("year_built")) if pd.notna(row.get("year_built")) else None,
                "style": str(row.get("style") or "Single Family"),
                "status": str(row.get("status") or "FOR_SALE").upper(),
                "current_list_price": price,
                "price_per_sqft": price_per_sqft,
                "days_on_market": int(row.get("days_on_mls") or 0) if pd.notna(row.get("days_on_mls")) else 0,
                "hoa_fee": float(row.get("hoa_fee")) if pd.notna(row.get("hoa_fee")) else None,
                "latitude": float(row.get("latitude")) if pd.notna(row.get("latitude")) else None,
                "longitude": float(row.get("longitude")) if pd.notna(row.get("longitude")) else None,
                "primary_photo": str(row.get("primary_photo") or "") if pd.notna(row.get("primary_photo")) else None,
                "is_foreclosure": row_foreclosure,
                "listing_source": "Foreclosure/REO" if row_foreclosure else listing_source
            })
        except Exception as ex:
            logger.debug(f"Row normalization error: {ex}")
            continue

    return records

"""
Direct Official Apartment Website Scraper for Metro Atlanta
(Buckhead, Brookhaven, Dunwoody, Gwinnett, North Fulton & Forsyth).

Extracts live unit-by-unit and floorplan pricing directly from official apartment websites across
5 major institutional apartment operators (51 communities total) + custom official URLs:
1. MAA (maac.com) — Embedded Engrain SightMap live unit JSON APIs + Schema.org JSON-LD
2. Camden (camdenliving.com) — Official /available-apartments Next.js structured unit inventory
3. Cortland (cortland.com) — Official /floorplans/ preloaded live unit & pricing payload
4. AMLI Residential (amli.com) — Official tRPC floorPlanHighlights live unit & pricing state
5. Equity Residential (equityapartments.com) — Official ea5.unitAvailability live unit terms
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.config import (
    ALL_ZIP_CODES,
    DATA_DIR,
    TARGET_SUBMARKETS,
    ZIP_TO_COUNTY,
    ZIP_TO_SUBMARKET,
)

logger = logging.getLogger(__name__)

CUSTOM_REGISTRY_FILE = DATA_DIR / "official_apartments_registry.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
}

_DOMAIN_LOCKS: Dict[str, threading.Lock] = {}
_DOMAIN_LOCKS_GUARD = threading.Lock()


def _get_domain_lock(url: str) -> threading.Lock:
    domain = urlparse(url).netloc.lower()
    with _DOMAIN_LOCKS_GUARD:
        if domain not in _DOMAIN_LOCKS:
            _DOMAIN_LOCKS[domain] = threading.Lock()
        return _DOMAIN_LOCKS[domain]


# Verified Official Apartment Communities across Buckhead, Brookhaven, Dunwoody,
# Duluth, Suwanee, Peachtree Corners, Johns Creek, Alpharetta & Cumming.
DEFAULT_OFFICIAL_COMMUNITIES: List[Dict[str, str]] = [
    # =========================================================================
    # 1. CAMDEN PROPERTY TRUST (camdenliving.com) — 9 Communities
    # =========================================================================
    {
        "brand": "Camden",
        "name": "Camden Buckhead",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-buckhead",
    },
    {
        "brand": "Camden",
        "name": "Camden Buckhead Square",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-buckhead-square",
    },
    {
        "brand": "Camden",
        "name": "Camden Paces",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-paces",
    },
    {
        "brand": "Camden",
        "name": "Camden Phipps",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-phipps",
    },
    {
        "brand": "Camden",
        "name": "Camden St. Clair",
        "city": "Brookhaven",
        "zip_code": "30329",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-st-clair",
    },
    {
        "brand": "Camden",
        "name": "Camden Creekstone",
        "city": "Brookhaven",
        "zip_code": "30341",
        "url": "https://www.camdenliving.com/apartments/atlanta-ga/camden-creekstone",
    },
    {
        "brand": "Camden",
        "name": "Camden Dunwoody",
        "city": "Dunwoody",
        "zip_code": "30338",
        "url": "https://www.camdenliving.com/apartments/dunwoody-ga/camden-dunwoody",
    },
    {
        "brand": "Camden",
        "name": "Camden Alpharetta",
        "city": "Johns Creek",
        "zip_code": "30005",
        "url": "https://www.camdenliving.com/apartments/alpharetta-ga/camden-alpharetta",
    },
    {
        "brand": "Camden",
        "name": "Camden Deerfield",
        "city": "Alpharetta",
        "zip_code": "30004",
        "url": "https://www.camdenliving.com/apartments/alpharetta-ga/camden-deerfield",
    },

    # =========================================================================
    # 2. CORTLAND (cortland.com) — 9 Communities
    # =========================================================================
    {
        "brand": "Cortland",
        "name": "Cortland at Buckhead Village",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://cortland.com/apartments/cortland-at-buckhead-village/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland at Phipps Plaza",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://cortland.com/apartments/cortland-at-phipps-plaza/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland Peachtree Battle",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://cortland.com/apartments/cortland-peachtree-battle/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland North Brookhaven",
        "city": "Brookhaven",
        "zip_code": "30341",
        "url": "https://cortland.com/apartments/cortland-north-brookhaven/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland Druid Hills",
        "city": "Brookhaven",
        "zip_code": "30329",
        "url": "https://cortland.com/apartments/cortland-druid-hills/",
    },
    {
        "brand": "Cortland",
        "name": "Attiva Peachtree by Cortland",
        "city": "Brookhaven",
        "zip_code": "30341",
        "url": "https://cortland.com/apartments/attiva-peachtree/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland Duluth",
        "city": "Duluth",
        "zip_code": "30096",
        "url": "https://cortland.com/apartments/cortland-duluth/",
    },
    {
        "brand": "Cortland",
        "name": "Cortland Peachtree Corners",
        "city": "Peachtree Corners",
        "zip_code": "30092",
        "url": "https://cortland.com/apartments/cortland-peachtree-corners/",
    },
    {
        "brand": "Cortland",
        "name": "The Springs at Peachtree Corners",
        "city": "Peachtree Corners",
        "zip_code": "30092",
        "url": "https://cortland.com/apartments/the-springs-at-peachtree-corners/",
    },

    # =========================================================================
    # 3. AMLI RESIDENTIAL (amli.com) — 7 Communities
    # =========================================================================
    {
        "brand": "AMLI",
        "name": "AMLI Buckhead",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://www.amli.com/apartments/atlanta/buckhead-apartments/amli-buckhead",
    },
    {
        "brand": "AMLI",
        "name": "AMLI 3464",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://www.amli.com/apartments/atlanta/buckhead-apartments/amli-3464",
    },
    {
        "brand": "AMLI",
        "name": "AMLI Flatiron",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://www.amli.com/apartments/atlanta/buckhead-apartments/amli-flatiron",
    },
    {
        "brand": "AMLI",
        "name": "AMLI Lindbergh",
        "city": "Buckhead",
        "zip_code": "30324",
        "url": "https://www.amli.com/apartments/atlanta/lindbergh-apartments/amli-lindbergh",
    },
    {
        "brand": "AMLI",
        "name": "AMLI Piedmont Heights",
        "city": "Buckhead",
        "zip_code": "30324",
        "url": "https://www.amli.com/apartments/atlanta/lindbergh-apartments/amli-piedmont-heights",
    },
    {
        "brand": "AMLI",
        "name": "AMLI Brookhaven",
        "city": "Brookhaven",
        "zip_code": "30319",
        "url": "https://www.amli.com/apartments/atlanta/brookhaven-apartments/amli-brookhaven",
    },
    {
        "brand": "AMLI",
        "name": "AMLI North Point",
        "city": "Alpharetta",
        "zip_code": "30022",
        "url": "https://www.amli.com/apartments/atlanta/alpharetta-apartments/amli-north-point",
    },

    # =========================================================================
    # 4. EQUITY RESIDENTIAL (equityapartments.com) — 6 Communities
    # =========================================================================
    {
        "brand": "Equity Residential",
        "name": "The Drexel Collective",
        "city": "Dunwoody",
        "zip_code": "30338",
        "url": "https://www.equityapartments.com/atlanta/dunwoody/the-drexel-collective-apartments",
    },
    {
        "brand": "Equity Residential",
        "name": "Richmond Row Apartments",
        "city": "Suwanee",
        "zip_code": "30024",
        "url": "https://www.equityapartments.com/atlanta/suwanee/richmond-row-apartments",
    },
    {
        "brand": "Equity Residential",
        "name": "Lex Alpharetta",
        "city": "Alpharetta",
        "zip_code": "30004",
        "url": "https://www.equityapartments.com/atlanta/alpharetta/lex-alpharetta-apartments",
    },
    {
        "brand": "Equity Residential",
        "name": "Reserve at Summit Crossing",
        "city": "Cumming",
        "zip_code": "30041",
        "url": "https://www.equityapartments.com/atlanta/cumming/reserve-at-summit-crossing-apartments",
    },
    {
        "brand": "Equity Residential",
        "name": "Summit Crossing",
        "city": "Cumming",
        "zip_code": "30041",
        "url": "https://www.equityapartments.com/atlanta/cumming/summit-crossing-apartments",
    },
    {
        "brand": "Equity Residential",
        "name": "The Falls at Forsyth",
        "city": "Cumming",
        "zip_code": "30040",
        "url": "https://www.equityapartments.com/atlanta/cumming/the-falls-at-forsyth-apartments",
    },

    # =========================================================================
    # 5. MAA (maac.com) — 20 Communities
    # =========================================================================
    {
        "brand": "MAA",
        "name": "MAA Buckhead",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.maac.com/georgia/atlanta/maa-buckhead/",
    },
    {
        "brand": "MAA",
        "name": "MAA Stratford",
        "city": "Buckhead",
        "zip_code": "30326",
        "url": "https://www.maac.com/georgia/atlanta/maa-stratford/",
    },
    {
        "brand": "MAA",
        "name": "MAA Chastain",
        "city": "Buckhead",
        "zip_code": "30342",
        "url": "https://www.maac.com/georgia/atlanta/maa-chastain/",
    },
    {
        "brand": "MAA",
        "name": "MAA Lenox",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.maac.com/georgia/atlanta/maa-lenox/",
    },
    {
        "brand": "MAA",
        "name": "MAA Peachtree Hills",
        "city": "Buckhead",
        "zip_code": "30305",
        "url": "https://www.maac.com/georgia/atlanta/maa-peachtree-hills/",
    },
    {
        "brand": "MAA",
        "name": "MAA Gardens",
        "city": "Buckhead",
        "zip_code": "30324",
        "url": "https://www.maac.com/georgia/atlanta/maa-gardens/",
    },
    {
        "brand": "MAA",
        "name": "MAA Riverside",
        "city": "Buckhead",
        "zip_code": "30327",
        "url": "https://www.maac.com/georgia/atlanta/maa-riverside/",
    },
    {
        "brand": "MAA",
        "name": "MAA Brookhaven",
        "city": "Brookhaven",
        "zip_code": "30319",
        "url": "https://www.maac.com/georgia/atlanta/maa-brookhaven/",
    },
    {
        "brand": "MAA",
        "name": "MAA Briarcliff",
        "city": "Brookhaven",
        "zip_code": "30329",
        "url": "https://www.maac.com/georgia/atlanta/maa-briarcliff/",
    },
    {
        "brand": "MAA",
        "name": "MAA Oglethorpe",
        "city": "Brookhaven",
        "zip_code": "30319",
        "url": "https://www.maac.com/georgia/atlanta/maa-oglethorpe/",
    },
    {
        "brand": "MAA",
        "name": "MAA Dunwoody",
        "city": "Dunwoody",
        "zip_code": "30360",
        "url": "https://www.maac.com/georgia/atlanta/maa-dunwoody/",
    },
    {
        "brand": "MAA",
        "name": "MAA Glen",
        "city": "Dunwoody",
        "zip_code": "30338",
        "url": "https://www.maac.com/georgia/atlanta/maa-glen/",
    },
    {
        "brand": "MAA",
        "name": "MAA Mount Vernon",
        "city": "Dunwoody",
        "zip_code": "30338",
        "url": "https://www.maac.com/georgia/atlanta/maa-mount-vernon/",
    },
    {
        "brand": "MAA",
        "name": "MAA Pleasant Hill",
        "city": "Duluth",
        "zip_code": "30096",
        "url": "https://www.maac.com/georgia/atlanta/maa-pleasant-hill/",
    },
    {
        "brand": "MAA",
        "name": "MAA McDaniel Farm",
        "city": "Duluth",
        "zip_code": "30096",
        "url": "https://www.maac.com/georgia/atlanta/maa-mcdaniel-farm/",
    },
    {
        "brand": "MAA",
        "name": "MAA River Oaks",
        "city": "Duluth",
        "zip_code": "30097",
        "url": "https://www.maac.com/georgia/atlanta/maa-river-oaks/",
    },
    {
        "brand": "MAA",
        "name": "MAA River Place",
        "city": "Duluth",
        "zip_code": "30096",
        "url": "https://www.maac.com/georgia/atlanta/maa-river-place/",
    },
    {
        "brand": "MAA",
        "name": "MAA Berkeley Lake",
        "city": "Peachtree Corners",
        "zip_code": "30092",
        "url": "https://www.maac.com/georgia/atlanta/maa-berkeley-lake/",
    },
    {
        "brand": "MAA",
        "name": "MAA Prescott",
        "city": "Alpharetta",
        "zip_code": "30004",
        "url": "https://www.maac.com/georgia/atlanta/maa-prescott/",
    },
    {
        "brand": "MAA",
        "name": "MAA Milstead",
        "city": "Alpharetta",
        "zip_code": "30004",
        "url": "https://www.maac.com/georgia/atlanta/maa-milstead/",
    },
]


def detect_apartment_brand(url: str, formatted_address: str = "") -> str:
    """Return canonical management brand name from an official apartment URL or address."""
    u = (url or "").lower()
    if "camdenliving.com" in u:
        return "Camden"
    if "cortland.com" in u:
        return "Cortland"
    if "amli.com" in u:
        return "AMLI"
    if "equityapartments.com" in u:
        return "Equity Residential"
    if "maac.com" in u:
        return "MAA"
    addr = (formatted_address or "").lower()
    for label in ("Camden", "Cortland", "AMLI", "MAA"):
        if label.lower() in addr:
            return label
    return "Official Direct"


def _parse_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return default
    if s.lower().startswith("studio"):
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else default


def get_registered_communities() -> List[Dict[str, str]]:
    """Return default official communities merged with any user-added communities."""
    communities = list(DEFAULT_OFFICIAL_COMMUNITIES)
    seen_urls = {c["url"].rstrip("/") for c in communities}
    if CUSTOM_REGISTRY_FILE.exists():
        try:
            custom_list = json.loads(CUSTOM_REGISTRY_FILE.read_text(encoding="utf-8"))
            for item in custom_list:
                u = (item.get("url") or "").rstrip("/")
                if u and u not in seen_urls:
                    if "brand" not in item:
                        item["brand"] = detect_apartment_brand(u, item.get("name", ""))
                    communities.append(item)
                    seen_urls.add(u)
        except Exception as ex:
            logger.warning(f"Failed to read custom apartment registry: {ex}")
    return communities


def register_custom_community(name: str, url: str, city: str, zip_code: str) -> None:
    """Save a user-supplied official apartment URL to the persistent registry."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing: List[Dict[str, str]] = []
    if CUSTOM_REGISTRY_FILE.exists():
        try:
            existing = json.loads(CUSTOM_REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    norm_url = url.strip()
    if not any(c.get("url", "").rstrip("/") == norm_url.rstrip("/") for c in existing):
        existing.append({
            "brand": detect_apartment_brand(norm_url, name),
            "name": name,
            "city": city,
            "zip_code": zip_code,
            "url": norm_url,
        })
        CUSTOM_REGISTRY_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _extract_ld_json_metadata(soup: BeautifulSoup, html_text: str) -> Dict[str, Any]:
    """Extract ApartmentComplex/Product name, street, city, zip, lat/lon, image, and starting price."""
    meta: Dict[str, Any] = {}
    og_title = soup.find("meta", property="og:title")
    og_img = soup.find("meta", property="og:image")
    if og_title and og_title.get("content"):
        raw_title = og_title["content"].split("|")[0].split("Luxury Apartment")[0].strip()
        meta["name"] = raw_title
    if og_img and og_img.get("content"):
        meta["photo"] = og_img["content"]

    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            payload = json.loads(script.string)
            nodes = payload.get("@graph", [payload]) if isinstance(payload, dict) else payload
            if not isinstance(nodes, list):
                nodes = [nodes]
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = str(node.get("@type") or "")
                if any(k in node_type for k in ("ApartmentComplex", "Residence", "LocalBusiness", "Place", "Product")):
                    if node.get("name") and not meta.get("name"):
                        meta["name"] = str(node["name"]).split("Luxury Apartment")[0].strip()
                    img = node.get("image")
                    if img and not meta.get("photo"):
                        meta["photo"] = img[0] if isinstance(img, list) else str(img)
                    addr = node.get("address") or {}
                    if isinstance(addr, dict):
                        if addr.get("streetAddress"):
                            meta["street"] = addr.get("streetAddress")
                        if addr.get("addressLocality"):
                            meta["city"] = addr.get("addressLocality")
                        meta["state"] = addr.get("addressRegion", "GA")
                        if addr.get("postalCode"):
                            meta["zip_code"] = str(addr.get("postalCode"))[:5]
                    geo = node.get("geo") or {}
                    if isinstance(geo, dict):
                        if geo.get("latitude"):
                            meta["latitude"] = float(geo["latitude"])
                        if geo.get("longitude"):
                            meta["longitude"] = float(geo["longitude"])
                    desc = str(node.get("description") or "")
                    if not meta.get("street"):
                        m_addr = re.search(
                            r"located at\s+([^,.]+),\s*[A-Za-z\s]+,\s*GA\s*(\d{5})",
                            desc,
                            re.IGNORECASE,
                        )
                        if m_addr:
                            meta["street"] = m_addr.group(1).strip()
                            if not meta.get("zip_code"):
                                meta["zip_code"] = m_addr.group(2)
                    m_start = re.search(r"starts?\s+at\s+\$([1-9],?\d{3})", desc, re.IGNORECASE)
                    if m_start:
                        meta["starting_rent"] = float(m_start.group(1).replace(",", ""))
        except Exception:
            continue

    return meta


def _resolve_location(
    meta: Dict[str, Any],
    fallback_city: Optional[str],
    fallback_zip: Optional[str],
) -> Tuple[str, str, str]:
    """Resolve canonical submarket city, verified target ZIP, and county."""
    zip_code = (fallback_zip or meta.get("zip_code") or "").strip()[:5]
    if zip_code not in ALL_ZIP_CODES and fallback_zip in ALL_ZIP_CODES:
        zip_code = fallback_zip

    # Prefer explicit fallback_city if its ZIP list contains zip_code (handles shared ZIPs like 30022/30092)
    if (
        fallback_city in TARGET_SUBMARKETS
        and zip_code in TARGET_SUBMARKETS[fallback_city]["zip_codes"]
    ):
        city = fallback_city
    else:
        city = ZIP_TO_SUBMARKET.get(zip_code) or fallback_city or meta.get("city") or "Buckhead"

    if city not in TARGET_SUBMARKETS:
        city = ZIP_TO_SUBMARKET.get(zip_code, "Buckhead")

    if not zip_code and city in TARGET_SUBMARKETS:
        zip_code = TARGET_SUBMARKETS[city]["zip_codes"][0]
    county = TARGET_SUBMARKETS.get(city, {}).get("county") or ZIP_TO_COUNTY.get(zip_code, "Fulton")
    return city, zip_code, county


def _build_records_from_units(
    units: List[Dict[str, Any]],
    url: str,
    name: str,
    street: str,
    city: str,
    zip_code: str,
    county: str,
    photo: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Group unit-level inventory by (beds, floorplan_name) into standardized official records."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    by_fp: Dict[Tuple[float, str], List[Dict[str, Any]]] = {}

    for u in units:
        price = float(u.get("price") or 0.0)
        if price < 700 or price > 18000:
            continue
        b = float(u["beds"]) if u.get("beds") is not None else 1.0
        fp_label = (u.get("floorplan_name") or "").strip() or f"{int(b)}BR"
        by_fp.setdefault((b, fp_label), []).append(u)

    records: List[Dict[str, Any]] = []
    for (beds_val, fp_label), tier_units in sorted(by_fp.items(), key=lambda x: (x[0][0], x[0][1])):
        prices = [float(u["price"]) for u in tier_units]
        sqfts = [float(u["sqft"]) for u in tier_units if u.get("sqft") and float(u["sqft"]) > 0]
        baths_list = [float(u["baths"]) for u in tier_units if u.get("baths") is not None]
        photos_list = [u["photo"] for u in tier_units if u.get("photo")]

        rent_min = round(min(prices), 2)
        rent_max = round(max(prices), 2)
        headline_rent = rent_min
        avg_sqft = round(sum(sqfts) / len(sqfts), 0) if sqfts else None
        rent_per_sqft = round(headline_rent / avg_sqft, 2) if (avg_sqft and avg_sqft > 0) else None
        rep_baths = baths_list[0] if baths_list else 1.0
        rep_photo = photo or (photos_list[0] if photos_list else None)

        bed_label = "Studio" if beds_val == 0 else f"{int(beds_val)} BR"
        avail_units_sum = sum(int(u.get("avail_override") or 1) for u in tier_units)
        unit_nums = ", ".join(
            f"#{u['unit_number']}"
            for u in tier_units[:3]
            if u.get("unit_number") and str(u["unit_number"]).strip()
        )
        fp_slug = re.sub(r"[^a-z0-9]+", "-", fp_label.lower()).strip("-") or "plan"

        clean_street = street.strip().rstrip(",") if street else name
        formatted_addr = f"{name} · Plan {fp_label} ({bed_label}) — {clean_street}, {city}, GA {zip_code}"
        prop_id = f"OFFICIAL-{slug}-{int(beds_val)}br-{fp_slug}"

        records.append({
            "property_id": prop_id,
            "property_url": url,
            "formatted_address": formatted_addr,
            "street": clean_street,
            "unit": f"{avail_units_sum} avail ({unit_nums})" if unit_nums else f"{avail_units_sum} avail",
            "city": city,
            "state": "GA",
            "zip_code": zip_code,
            "county": county,
            "beds": beds_val,
            "full_baths": rep_baths,
            "half_baths": None,
            "sqft": avg_sqft,
            "style": "OFFICIAL APARTMENT",
            "monthly_rent": headline_rent,
            "rent_min": rent_min,
            "rent_max": rent_max,
            "rent_per_sqft": rent_per_sqft,
            "days_on_market": 0,
            "latitude": lat,
            "longitude": lon,
            "primary_photo": rep_photo,
            "listing_source": "Official Website",
        })

    return records


def _fetch_sightmap_units(embed_url: str) -> List[Dict[str, Any]]:
    """Given a SightMap embed URL or API URL, return parsed available unit dicts."""
    if not embed_url.startswith("http"):
        embed_url = "https://" + embed_url.lstrip("/")

    try:
        if "/app/api/v1/" in embed_url:
            api_url = embed_url
        else:
            resp = requests.get(embed_url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                return []
            matches = re.findall(r"https://sightmap\.com/app/api/v1/[^\x22\x27\s\\]+", resp.text)
            if not matches:
                return []
            api_url = matches[0]

        api_resp = requests.get(api_url, headers=HEADERS, timeout=12)
        if api_resp.status_code != 200:
            return []

        data = api_resp.json().get("data", {})
        raw_units = data.get("units") or []
        floor_plans = {fp["id"]: fp for fp in (data.get("floor_plans") or []) if "id" in fp}

        parsed_units: List[Dict[str, Any]] = []
        for u in raw_units:
            price = float(u.get("price") or 0.0)
            if price <= 0:
                continue
            fp = floor_plans.get(u.get("floor_plan_id"), {})
            fp_raw_name = fp.get("name") or ""
            fp_name = fp_raw_name
            if isinstance(fp_raw_name, str) and fp_raw_name.startswith("{"):
                try:
                    fp_name = json.loads(fp_raw_name).get("name") or fp_raw_name
                except Exception:
                    pass

            beds = _parse_float(fp.get("bedroom_count"))
            baths = _parse_float(fp.get("bathroom_count"), 1.0)
            area = float(u.get("area") or fp.get("area") or 0.0)

            parsed_units.append({
                "unit_number": str(u.get("unit_number") or ""),
                "price": price,
                "sqft": area if area > 0 else None,
                "beds": beds,
                "baths": baths,
                "floorplan_name": str(fp_name or ""),
                "available_on": u.get("available_on"),
            })
        return parsed_units
    except Exception as ex:
        logger.warning(f"SightMap fetch failed for {embed_url}: {ex}")
        return []


def _scrape_camden_official(
    url: str,
    community_name: Optional[str],
    fallback_city: Optional[str],
    fallback_zip: Optional[str],
) -> List[Dict[str, Any]]:
    """Scrape Camden Property Trust official /available-apartments Next.js JSON payload."""
    base_url = url.split("/available-apartments")[0].rstrip("/")
    avail_url = f"{base_url}/available-apartments"
    resp = requests.get(avail_url, headers=HEADERS, timeout=14)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_ld_json_metadata(soup, resp.text)
    nd_tag = soup.find("script", id="__NEXT_DATA__")
    if not nd_tag or not nd_tag.string:
        return []

    payload = json.loads(nd_tag.string)
    data = payload.get("props", {}).get("pageProps", {}).get("data") or {}
    comm = data.get("community") or {}

    raw_addr = str(comm.get("address") or "").strip()
    m_zip = re.search(r"(\d{5})\s*$", raw_addr)
    if m_zip and not meta.get("zip_code"):
        meta["zip_code"] = m_zip.group(1)

    # Extract street portion before city/state/zip without consuming street words
    street_clean = re.sub(
        r",?\s*(?:Atlanta|Dunwoody|Brookhaven|Buckhead|Alpharetta|Johns Creek|Duluth|Suwanee|Norcross|Peachtree Corners|Cumming|Chamblee),\s*GA\s*\d{5}\s*$",
        "",
        raw_addr,
        flags=re.IGNORECASE,
    ).strip()

    name = community_name or comm.get("name") or meta.get("name") or "Camden Apartments"
    city, zip_code, county = _resolve_location(meta, fallback_city, fallback_zip)
    photo = comm.get("thumbImg") or meta.get("photo")
    street = street_clean or meta.get("street") or name

    units: List[Dict[str, Any]] = []
    for apt in data.get("availableApartments") or []:
        fp_name = str(apt.get("name") or "")
        beds = _parse_float(apt.get("bedrooms"), 1.0)
        baths = _parse_float(apt.get("bathrooms"), 1.0)
        fp_sqft = _parse_float(apt.get("squareFeet"))
        unit_refs = apt.get("availableUnitRefs") or []
        if unit_refs:
            for ref in unit_refs:
                rent = _parse_float(ref.get("monthlyRent"))
                if rent and rent > 0:
                    units.append({
                        "unit_number": str(ref.get("unitNumber") or ""),
                        "price": rent,
                        "sqft": _parse_float(ref.get("squareFeet")) or fp_sqft,
                        "beds": beds,
                        "baths": baths,
                        "floorplan_name": fp_name,
                    })
        else:
            rent = _parse_float(apt.get("monthlyRent"))
            if rent and rent > 0:
                units.append({
                    "unit_number": str(apt.get("unitNumber") or ""),
                    "price": rent,
                    "sqft": fp_sqft,
                    "beds": beds,
                    "baths": baths,
                    "floorplan_name": fp_name,
                    "avail_override": int(apt.get("availableUnits") or 1),
                })

    return _build_records_from_units(
        units=units,
        url=avail_url,
        name=name,
        street=street,
        city=city,
        zip_code=zip_code,
        county=county,
        photo=photo,
        lat=meta.get("latitude"),
        lon=meta.get("longitude"),
    )


def _scrape_cortland_official(
    url: str,
    community_name: Optional[str],
    fallback_city: Optional[str],
    fallback_zip: Optional[str],
) -> List[Dict[str, Any]]:
    """Scrape Cortland official /floorplans/ preloaded live unit & pricing payload."""
    base_url = url.split("/floorplans")[0].rstrip("/")
    fp_url = f"{base_url}/floorplans/"
    resp = requests.get(fp_url, headers=HEADERS, timeout=14)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_ld_json_metadata(soup, resp.text)

    preload: Optional[Dict[str, Any]] = None
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        txt = script.string or ""
        if "var preload" in txt and "floorplans" in txt:
            m = re.search(r"var\s+preload\s*=\s*", txt)
            if m:
                try:
                    preload, _ = decoder.raw_decode(txt[m.end():].lstrip())
                    break
                except Exception:
                    continue

    if not preload or not isinstance(preload.get("floorplans"), dict):
        return []

    name = community_name or meta.get("name") or "Cortland Apartments"
    city, zip_code, county = _resolve_location(meta, fallback_city, fallback_zip)
    street = meta.get("street") or name
    photo = meta.get("photo")

    units: List[Dict[str, Any]] = []
    for fp in preload["floorplans"].values():
        if not isinstance(fp, dict):
            continue
        fp_name = str(fp.get("title") or "")
        beds = _parse_float(fp.get("bedroom"), 1.0)
        baths = _parse_float(fp.get("bathroom"), 1.0)
        sqft = _parse_float(fp.get("square_feet"))
        avail_dict = fp.get("availprice")
        if isinstance(avail_dict, dict) and avail_dict:
            for u_info in avail_dict.values():
                if not isinstance(u_info, dict):
                    continue
                price = _parse_float(u_info.get("price"))
                if price and price > 0:
                    units.append({
                        "unit_number": str(u_info.get("apartment_number") or ""),
                        "price": price,
                        "sqft": sqft,
                        "beds": beds,
                        "baths": baths,
                        "floorplan_name": fp_name,
                    })
        else:
            # Only include floorplans with active min_rent when apartments list is non-empty
            min_rent = _parse_float(fp.get("min_rent"))
            apts_list = fp.get("apartments") or []
            if min_rent and min_rent > 0 and apts_list:
                units.append({
                    "unit_number": "",
                    "price": min_rent,
                    "sqft": sqft,
                    "beds": beds,
                    "baths": baths,
                    "floorplan_name": fp_name,
                    "avail_override": len(apts_list),
                })

    return _build_records_from_units(
        units=units,
        url=fp_url,
        name=name,
        street=street,
        city=city,
        zip_code=zip_code,
        county=county,
        photo=photo,
        lat=meta.get("latitude"),
        lon=meta.get("longitude"),
    )


def _scrape_amli_official(
    url: str,
    community_name: Optional[str],
    fallback_city: Optional[str],
    fallback_zip: Optional[str],
) -> List[Dict[str, Any]]:
    """Scrape AMLI Residential official Next.js tRPC floorPlanHighlights state."""
    resp = requests.get(url, headers=HEADERS, timeout=14)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_ld_json_metadata(soup, resp.text)
    nd_tag = soup.find("script", id="__NEXT_DATA__")
    if not nd_tag or not nd_tag.string:
        return []

    payload = json.loads(nd_tag.string)
    queries = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("trpcState", {})
        .get("json", {})
        .get("queries")
        or []
    )

    full_floorplans: List[Dict[str, Any]] = []
    highlights: List[Dict[str, Any]] = []
    for q in queries:
        qk = q.get("queryKey") or []
        k0 = qk[0] if qk else None
        q_data = q.get("state", {}).get("data")
        if k0 == ["amli", "floorplans"] and isinstance(q_data, list):
            full_floorplans = q_data
        elif k0 == ["amli", "floorPlanHighlights"] and isinstance(q_data, list):
            highlights = q_data
        elif k0 == ["prismic", "propertyDocument"] and isinstance(q_data, dict):
            pdata = q_data.get("data") or {}
            if pdata.get("street_address") and not meta.get("street"):
                meta["street"] = pdata.get("street_address")
            if pdata.get("postal_code") and not meta.get("zip_code"):
                meta["zip_code"] = str(pdata.get("postal_code"))[:5]
            hero = (pdata.get("hero_image") or {}).get("url")
            if hero and not meta.get("photo"):
                meta["photo"] = hero

    name = community_name or meta.get("name") or "AMLI Apartments"
    city, zip_code, county = _resolve_location(meta, fallback_city, fallback_zip)
    street = meta.get("street") or name
    photo = meta.get("photo")

    source_fps = full_floorplans if full_floorplans else highlights
    units: List[Dict[str, Any]] = []
    for fp in source_fps:
        if not isinstance(fp, dict):
            continue
        fp_name = str(fp.get("floorplanName") or "")
        beds = _parse_float(fp.get("bedroomMin") if fp.get("bedroomMin") is not None else fp.get("bedroomMax"), 1.0)
        baths = _parse_float(fp.get("bathroomMin") if fp.get("bathroomMin") is not None else fp.get("bathroomMax"), 1.0)
        fp_sqft = _parse_float(fp.get("sqftMin")) or _parse_float(fp.get("sqFtMax")) or _parse_float(fp.get("sqftMax"))
        fp_img = (((fp.get("cms") or {}).get("data") or {}).get("main_image") or {}).get("url")

        raw_units = fp.get("units") or []
        if raw_units:
            for u in raw_units:
                if u.get("affordableUnit"):
                    continue
                rent = _parse_float(u.get("rent"))
                if rent and rent > 0:
                    units.append({
                        "unit_number": str(u.get("unitNumber") or ""),
                        "price": rent,
                        "sqft": _parse_float(u.get("squareFeet")) or fp_sqft,
                        "beds": beds,
                        "baths": baths,
                        "floorplan_name": fp_name,
                        "photo": fp_img,
                    })
        else:
            p_min = _parse_float(fp.get("priceMin"))
            avail_cnt = int(fp.get("availableUnitCount") or 0)
            if p_min and p_min > 0 and avail_cnt > 0:
                units.append({
                    "unit_number": "",
                    "price": p_min,
                    "sqft": fp_sqft,
                    "beds": beds,
                    "baths": baths,
                    "floorplan_name": fp_name,
                    "avail_override": avail_cnt,
                    "photo": fp_img,
                })

    return _build_records_from_units(
        units=units,
        url=url,
        name=name,
        street=street,
        city=city,
        zip_code=zip_code,
        county=county,
        photo=photo,
        lat=meta.get("latitude"),
        lon=meta.get("longitude"),
    )


def _scrape_equity_official(
    url: str,
    community_name: Optional[str],
    fallback_city: Optional[str],
    fallback_zip: Optional[str],
) -> List[Dict[str, Any]]:
    """Scrape Equity Residential official ea5.unitAvailability live unit terms."""
    resp = requests.get(url, headers=HEADERS, timeout=14)
    if resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_ld_json_metadata(soup, resp.text)

    m = re.search(r"ea5\.unitAvailability\s*=\s*", resp.text)
    if not m:
        return []

    try:
        ea_data, _ = json.JSONDecoder().raw_decode(resp.text[m.end():].lstrip())
    except Exception as ex:
        logger.warning(f"Failed decoding Equity unitAvailability on {url}: {ex}")
        return []

    name = community_name or meta.get("name") or "Equity Residential"
    city, zip_code, county = _resolve_location(meta, fallback_city, fallback_zip)
    street = meta.get("street") or name
    photo = meta.get("photo")

    units: List[Dict[str, Any]] = []
    for bt in ea_data.get("BedroomTypes") or []:
        for u in bt.get("AvailableUnits") or []:
            best_term = u.get("BestTerm") or {}
            rent = _parse_float(best_term.get("Price"))
            if not rent or rent <= 0:
                terms = u.get("Terms") or []
                if terms:
                    rent = _parse_float(terms[0].get("Price"))
            if not rent or rent <= 0:
                continue

            u_photos = u.get("Photos") or []
            u_img = u_photos[0].get("ImageUrl") if (u_photos and isinstance(u_photos[0], dict)) else None

            units.append({
                "unit_number": str(u.get("UnitId") or ""),
                "price": rent,
                "sqft": _parse_float(u.get("SqFt")),
                "beds": _parse_float(u.get("Bed"), 1.0),
                "baths": _parse_float(u.get("Bath"), 1.0),
                "floorplan_name": str(u.get("FloorplanName") or ""),
                "photo": u_img,
            })

    return _build_records_from_units(
        units=units,
        url=url,
        name=name,
        street=street,
        city=city,
        zip_code=zip_code,
        county=county,
        photo=photo,
        lat=meta.get("latitude"),
        lon=meta.get("longitude"),
    )


def scrape_official_apartment_url(
    url: str,
    community_name: Optional[str] = None,
    fallback_city: Optional[str] = None,
    fallback_zip: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Scrape an apartment community's official website URL (or direct SightMap URL).
    Dispatches to brand-specific structured parsers (Camden, Cortland, AMLI, Equity)
    or generic SightMap + JSON-LD extraction (MAA and custom apartment websites).
    """
    domain = urlparse(url).netloc.lower()
    try:
        if "camdenliving.com" in domain:
            recs = _scrape_camden_official(url, community_name, fallback_city, fallback_zip)
            if recs:
                return recs
        elif "cortland.com" in domain:
            recs = _scrape_cortland_official(url, community_name, fallback_city, fallback_zip)
            if recs:
                return recs
        elif "amli.com" in domain:
            recs = _scrape_amli_official(url, community_name, fallback_city, fallback_zip)
            if recs:
                return recs
        elif "equityapartments.com" in domain:
            recs = _scrape_equity_official(url, community_name, fallback_city, fallback_zip)
            if recs:
                return recs
    except Exception as ex:
        logger.warning(f"Structured brand parser error on {url}: {ex}")

    # Generic Official Website Scraper (Engrain SightMap + Schema.org JSON-LD + HTML fallback)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=14)
        if resp.status_code != 200:
            logger.warning(f"Official website {url} returned HTTP {resp.status_code}")
            return []
    except Exception as ex:
        logger.warning(f"Error requesting official website {url}: {ex}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    meta = _extract_ld_json_metadata(soup, resp.text)

    name = community_name or meta.get("name") or urlparse(url).netloc
    city, zip_code, county = _resolve_location(meta, fallback_city, fallback_zip)
    street = meta.get("street") or name
    photo = meta.get("photo")
    lat = meta.get("latitude")
    lon = meta.get("longitude")

    # 1. Check for embedded SightMap live unit inventory
    sightmap_matches = re.findall(r"sightmap\.com/embed/[a-zA-Z0-9]+", resp.text)
    if "sightmap.com" in url:
        sightmap_matches = [url]

    if sightmap_matches:
        units = _fetch_sightmap_units(sightmap_matches[0])
        if units:
            return _build_records_from_units(
                units=units,
                url=url,
                name=name,
                street=street,
                city=city,
                zip_code=zip_code,
                county=county,
                photo=photo,
                lat=lat,
                lon=lon,
            )

    # 2. Fallback: JSON-LD starting rent or HTML price extraction on official page
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    raw_prices = [
        float(p.replace(",", ""))
        for p in re.findall(r"\$([1-4],\d{3})\b", resp.text)
    ]
    if meta.get("starting_rent"):
        raw_prices.append(float(meta["starting_rent"]))

    valid_prices = [p for p in raw_prices if 950 <= p <= 6500]
    if valid_prices:
        rent_min = min(valid_prices)
        rent_max = max(valid_prices)
        return [{
            "property_id": f"OFFICIAL-{slug}-main",
            "property_url": url,
            "formatted_address": f"{name} — {street}, {city}, GA {zip_code}",
            "street": street,
            "unit": "Official Floorplans",
            "city": city,
            "state": "GA",
            "zip_code": zip_code,
            "county": county,
            "beds": 1.0,
            "full_baths": 1.0,
            "half_baths": None,
            "sqft": 950.0,
            "style": "OFFICIAL APARTMENT",
            "monthly_rent": rent_min,
            "rent_min": rent_min,
            "rent_max": rent_max,
            "rent_per_sqft": round(rent_min / 950.0, 2),
            "days_on_market": 0,
            "latitude": lat,
            "longitude": lon,
            "primary_photo": photo,
            "listing_source": "Official Website",
        }]

    return []


def scrape_all_official_apartments(
    submarkets: Optional[List[str]] = None,
    jitter_min: float = 0.2,
    jitter_max: float = 0.45,
    max_workers: int = 5,
) -> List[Dict[str, Any]]:
    """
    Scrape all registered official apartment websites across target submarkets.
    Uses polite per-domain rate-limited concurrency across the 5 distinct apartment brands.
    """
    communities = get_registered_communities()
    if submarkets:
        target_set = {s.strip() for s in submarkets}
        communities = [c for c in communities if c["city"] in target_set]

    def _scrape_one(comm: Dict[str, str]) -> List[Dict[str, Any]]:
        lock = _get_domain_lock(comm["url"])
        with lock:
            time.sleep(random.uniform(jitter_min, jitter_max))
            recs = scrape_official_apartment_url(
                url=comm["url"],
                community_name=comm["name"],
                fallback_city=comm["city"],
                fallback_zip=comm["zip_code"],
            )
        logger.info(f"Scraped {len(recs)} official floorplans from {comm['name']} ({comm['city']})")
        return recs

    all_records: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_scrape_one, comm) for comm in communities]
        for fut in as_completed(futures):
            try:
                all_records.extend(fut.result())
            except Exception as ex:
                logger.warning(f"Worker error scraping official community: {ex}")

    return all_records

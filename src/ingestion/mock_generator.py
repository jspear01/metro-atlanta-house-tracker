"""
Realistic Metro Atlanta Listing Generator (Gwinnett & North Fulton focus).
Generates geographically authentic property data with price drop histories and deal criteria.
"""

import random
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta

from src.config import TARGET_SUBMARKETS

STREET_NAMES = {
    "Duluth": [
        "Meadow Church Road", "Pleasant Hill Road", "Buford Highway", "Rogers Bridge Road",
        "Howell Ferry Road", "Albemarle Lane", "Sugarloaf Parkway", "Chattahoochee Drive",
        "Berkeley Lake Road", "River Plantation Way", "Stonemill Way", "Sweetwater Club Drive"
    ],
    "Suwanee": [
        "McGinnis Ferry Road", "Suwanee Dam Road", "Peachtree Industrial Boulevard",
        "Scales Road", "Settles Bridge Road", "Moore Road", "Old Alpharetta Road",
        "Town Center Avenue", "Highland Gate Drive", "River Club Drive", "Morningview Drive"
    ],
    "Norcross": [
        "Buford Highway NW", "Holcomb Bridge Road", "South Peachtree Street",
        "Jimmy Carter Boulevard", "Northwoods Parkway", "Medlock Bridge Road",
        "Langford Road", "Beaver Ruin Road", "Singing Pines Drive", "Britt Road"
    ],
    "Peachtree Corners": [
        "Peachtree Parkway", "Spalding Drive", "Technology Parkway", "Winters Chapel Road",
        "Crooked Creek Road", "Davinci Court", "River Exchange Drive", "Amherst Lane",
        "Wetherburn Way", "Simpson Circle", "Cornerstone Drive"
    ],
    "Johns Creek": [
        "Medlock Bridge Road", "State Bridge Road", "Abbotts Bridge Road", "Jones Bridge Road",
        "Buice Road", "Bell Road", "Morton Road", "St Ives Country Club Parkway",
        "Country Club Drive", "Barnwell Road"
    ],
    "Alpharetta": [
        "Old Milton Parkway", "Windward Parkway", "Haynes Bridge Road", "Kimball Bridge Road",
        "North Point Parkway", "Milton Avenue", "Midfield Way", "Academy Street",
        "Webb Bridge Road", "Deerfield Parkway"
    ],
    "Cumming": [
        "Buford Dam Road", "Sawnee Drive", "Castleberry Road", "Bethelview Road",
        "Kelly Mill Road", "Post Road", "Trammel Road", "Pilgrim Mill Road",
        "Vickery Creek Road", "Lakeview Drive"
    ]
}

STYLES = ["Single Family", "Single Family", "Single Family", "Townhouse", "Condo"]


def generate_metro_atlanta_listings(count_per_city: int = 15, seed: int = 42) -> List[Dict[str, Any]]:
    """Generate realistic listings across target cities."""
    random.seed(seed)
    records = []
    listing_id_counter = 10001

    sample_photos = [
        "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?w=800&auto=format&fit=crop&q=60",  # Modern home exterior
        "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=800&auto=format&fit=crop&q=60",  # Suburban craftsman home
        "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=800&auto=format&fit=crop&q=60",  # Atlanta brick estate
        "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800&auto=format&fit=crop&q=60",  # Luxury residential home
        "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800&auto=format&fit=crop&q=60",  # Contemporary house
        "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800&auto=format&fit=crop&q=60",  # Classic Georgia suburban home
        "https://images.unsplash.com/photo-1598228723793-52759bba239c?w=800&auto=format&fit=crop&q=60",  # Single family house
        "https://images.unsplash.com/photo-1613977257363-707ba9348227?w=800&auto=format&fit=crop&q=60"   # Beautiful suburban front porch home
    ]

    for city, meta in TARGET_SUBMARKETS.items():
        county = meta["county"]
        zip_codes = meta["zip_codes"]
        center_lat = meta["center"]["lat"]
        center_lon = meta["center"]["lon"]
        streets = STREET_NAMES.get(city, ["Main Street", "Peachtree Road"])

        for i in range(count_per_city):
            mls_id = f"FMLS-{listing_id_counter}"
            listing_id_counter += 1

            zip_code = random.choice(zip_codes)
            street_num = random.randint(100, 9990)
            street_name = random.choice(streets)
            formatted_address = f"{street_num} {street_name}, {city}, GA {zip_code}"

            style = random.choice(STYLES)
            if style == "Condo":
                beds = random.choice([1.0, 2.0, 3.0])
                full_baths = random.choice([1.0, 2.0])
                half_baths = 0.0
                sqft = round(random.uniform(950, 1650), -1)
                lot_sqft = None
                hoa_fee = round(random.uniform(220, 550), 2)
                base_price = random.uniform(230_000, 420_000)
            elif style == "Townhouse":
                beds = random.choice([3.0, 4.0])
                full_baths = random.choice([2.0, 3.0])
                half_baths = 1.0
                sqft = round(random.uniform(1600, 2600), -1)
                lot_sqft = round(random.uniform(1200, 2800), -1)
                hoa_fee = round(random.uniform(150, 320), 2)
                base_price = random.uniform(340_000, 560_000)
            else:  # Single Family
                beds = random.choice([3.0, 4.0, 5.0, 6.0])
                full_baths = random.choice([2.0, 3.0, 4.0, 5.0])
                half_baths = random.choice([0.0, 1.0])
                sqft = round(random.uniform(2100, 5200), -1)
                lot_sqft = round(random.uniform(8000, 32000), -1)
                hoa_fee = round(random.uniform(40, 180), 2) if random.random() > 0.25 else 0.0

                # Premium for North Fulton (Johns Creek / Alpharetta) vs Gwinnett
                if county == "Fulton":
                    base_price = random.uniform(550_000, 1_350_000)
                elif city == "Suwanee":
                    base_price = random.uniform(480_000, 950_000)
                else:
                    base_price = random.uniform(380_000, 820_000)

            # Introduce intentional bargain / sub-$220 sqft candidates
            if random.random() < 0.18:
                # Target sub-$220/sqft
                target_sqft_price = random.uniform(185, 218)
                base_price = round(sqft * target_sqft_price, -3)

            initial_price = round(base_price, -3)
            current_price = initial_price

            # Simulate price cuts on ~22% of properties
            is_price_drop = False
            drop_pct = 0.0
            drop_amount = 0.0
            price_history_events = [
                {"price": initial_price, "event_type": "listed", "days_ago": random.randint(15, 60)}
            ]

            if random.random() < 0.25:
                is_price_drop = True
                drop_rate = random.uniform(0.04, 0.12)  # 4% to 12% drop
                drop_amount = round(initial_price * drop_rate, -3)
                current_price = initial_price - drop_amount
                drop_pct = round((drop_amount / initial_price) * 100, 2)
                price_history_events.append({
                    "price": current_price,
                    "event_type": "price_drop",
                    "days_ago": random.randint(1, 14)
                })

            price_per_sqft = round(current_price / sqft, 2) if sqft > 0 else None
            days_on_market = random.randint(3, 85)
            year_built = random.randint(1986, 2024)

            # Jitter coords around center
            lat = center_lat + random.uniform(-0.045, 0.045)
            lon = center_lon + random.uniform(-0.045, 0.045)

            photo = random.choice(sample_photos)
            is_fc = random.random() < 0.10
            source_tag = "Foreclosure/REO" if is_fc else "MLS/Realtor"

            records.append({
                "mls_id": mls_id,
                "property_url": f"https://www.realtor.com/realestateandhomes-search/{zip_code}",
                "formatted_address": formatted_address,
                "street": f"{street_num} {street_name}",
                "unit": None,
                "city": city,
                "state": "GA",
                "zip_code": zip_code,
                "county": county,
                "beds": beds,
                "full_baths": full_baths,
                "half_baths": half_baths,
                "sqft": sqft,
                "lot_sqft": lot_sqft,
                "year_built": year_built,
                "style": style,
                "status": "FOR_SALE",
                "current_list_price": current_price,
                "initial_list_price": initial_price,
                "price_per_sqft": price_per_sqft,
                "days_on_market": days_on_market,
                "hoa_fee": hoa_fee,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "primary_photo": photo,
                "is_price_drop": is_price_drop,
                "price_drop_pct": drop_pct,
                "price_drop_amount": drop_amount,
                "is_foreclosure": is_fc,
                "listing_source": source_tag,
                "_simulated_history": price_history_events
            })

    return records

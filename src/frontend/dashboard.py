"""
Interactive Real Estate Analytics Dashboard for Metro Atlanta (Gwinnett & North Fulton).
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from src.config import TARGET_SUBMARKETS, ALL_ZIP_CODES
from src.database.connection import get_session, init_db
from src.database.models import Property, PriceHistory, AlertRule, AlertLog, IngestionSnapshot, RentalListing
from src.database.repository import query_properties, get_recent_alerts, get_alert_rules, get_rentals_dataframe
from src.analytics.metrics import (
    get_properties_dataframe,
    compute_executive_kpis,
    compute_submarket_breakdown,
    compute_zip_code_breakdown,
    compute_duckdb_advanced_analytics,
    compute_eviction_metrics,
    compute_mortgage_delinquency_metrics,
    compute_price_drop_summary
)
from src.ingestion.pipeline import run_pipeline, run_rental_pipeline
from src.ingestion.distress_trends import (
    fetch_historical_eviction_filings,
    fetch_historical_mortgage_delinquency,
    DATA_SOURCES,
    FETCH_STATUS
)


def md_escape(text) -> str:
    """Escape '$' so Streamlit markdown doesn't render text between dollar signs as LaTeX."""
    return str(text).replace("$", "\\$")


# Known listing origin websites: domain fragment -> (display name, badge color)
LISTING_SITES = {
    "realtor.com": ("Realtor.com", "#f87171"),
    "redfin.com": ("Redfin", "#fb7185"),
    "zillow.com": ("Zillow", "#60a5fa"),
    "auction.com": ("Auction.com", "#a78bfa"),
    "rlselaw.com": ("RLSE Law (GA Trustee Notices)", "#c4b5fd"),
}


def get_listing_site(url, feed_name=None) -> tuple:
    """Return (site display name, badge color) based on the listing URL's domain."""
    url_str = str(url or "").lower()
    for domain, (name, color) in LISTING_SITES.items():
        if domain in url_str:
            return name, color
    return (feed_name or "Unknown Source"), "#94a3b8"



def is_synthetic_listing(prop: dict) -> bool:
    """Synthetic seed listings use the 'FMLS-' prefix and have no real MLS detail page."""
    return str(prop.get("mls_id") or "").startswith("FMLS-")


def apply_custom_css():
    st.markdown("""
    <style>
    /* Metric Card Styling */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
        border: 1px solid rgba(255, 255, 255, 0.12);
        padding: 16px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        border-color: #3b82f6;
        transform: translateY(-2px);
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94a3b8 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
    }
    /* Badges */
    .deal-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 700;
        margin-right: 6px;
    }
    .badge-price-drop {
        background-color: #ef4444;
        color: white;
    }
    .badge-bargain {
        background-color: #10b981;
        color: white;
    }
    .badge-city {
        background-color: #3b82f6;
        color: white;
    }
    </style>
    """, unsafe_allow_html=True)


def render_dashboard():
    st.set_page_config(
        page_title="Metro Atlanta Real Estate Tracker",
        page_icon="🏡",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    apply_custom_css()

    # Ensure DB is initialized
    init_db()

    # Title & Subtitle Header
    col_hdr_1, col_hdr_2 = st.columns([3, 1])
    with col_hdr_1:
        st.title("🏡 Metro Atlanta Real Estate Price Tracker")
        st.caption("Analytical intelligence & price drop tracking across **Gwinnett & North Fulton** submarkets (Duluth, Suwanee, Norcross, Peachtree Corners & Adjacent).")
    with col_hdr_2:
        st.markdown(f"**Last Sync:** `{datetime.now().strftime('%Y-%m-%d %H:%M')}`")
        if st.button("🔄 Sync / Refresh Data", width="stretch"):
            st.rerun()

    # Sidebar Filter Controls
    st.sidebar.header("🔍 Market Search & Filters")

    # City Multi-Select
    all_cities = list(TARGET_SUBMARKETS.keys())
    default_selected = [c for c in ["Duluth", "Suwanee", "Norcross", "Peachtree Corners", "Atlanta"] if c in all_cities]
    selected_cities = st.sidebar.multiselect(
        "Submarket Cities",
        options=all_cities,
        default=default_selected
    )

    # Calculate available zip codes for selected cities
    available_zips = []
    for c in selected_cities:
        available_zips.extend(TARGET_SUBMARKETS[c]["zip_codes"])
    available_zips = sorted(list(set(available_zips)))

    selected_zips = st.sidebar.multiselect(
        "ZIP Codes Filter",
        options=available_zips,
        default=[]
    )

    # Property Type Filter
    property_types = ["All", "Single Family", "Townhouse", "Condo"]
    selected_prop_type = st.sidebar.selectbox("Property Type", property_types, index=0)

    # Price Range Slider
    price_range = st.sidebar.slider(
        "Price Range ($)",
        min_value=200_000,
        max_value=1_600_000,
        value=(250_000, 1_300_000),
        step=25_000,
        format="$%d"
    )

    # Deal Toggles
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Deal & Distress Filters")
    price_drops_only = st.sidebar.checkbox("🔥 Price Drops Only", value=False)
    bargains_only = st.sidebar.checkbox("💎 Bargain Sub-$220/sqft Only", value=False)
    foreclosures_only = st.sidebar.checkbox("⚠️ Foreclosures Only", value=False)

    source_filter = st.sidebar.selectbox(
        "Listing Source",
        ["All", "MLS/Realtor", "Foreclosure/REO", "Redfin Open Data", "Auction / Legal Notice"],
        index=0
    )

    # Fetch Data with Filters
    df = get_properties_dataframe(
        cities=selected_cities if selected_cities else None,
        zip_codes=selected_zips if selected_zips else None,
        property_type=selected_prop_type,
        price_drop_only=price_drops_only,
        foreclosure_only=foreclosures_only,
        source=source_filter if source_filter != "All" else None
    )

    if not df.empty:
        df = df[
            (df["current_list_price"] >= price_range[0]) &
            (df["current_list_price"] <= price_range[1])
        ]
        if bargains_only:
            df = df[df["price_per_sqft"] <= 220.0]

    # Compute KPI metrics
    kpis = compute_executive_kpis(df)

    # Top KPI Metrics Row
    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Active Listings", f"{kpis['total_inventory']:,}")
    m2.metric("Median List Price", f"${kpis['median_price']:,.0f}" if kpis['median_price'] else "$0")
    m3.metric("Median $/SqFt", f"${kpis['median_sqft_price']:.1f}" if kpis['median_sqft_price'] else "$0")
    m4.metric("Median DOM", f"{kpis['median_dom']} days")
    m5.metric("Price Drops", f"{kpis['price_drop_count']}", f"{kpis['price_drop_pct_inventory']}% inv", delta_color="inverse")
    m6.metric("Sub-$220 Deals", f"{kpis['sub_220_count']}", "Value")
    m7.metric("Foreclosures", f"{kpis.get('foreclosure_count', 0)}", "Bank Owned")

    st.markdown("---")

    # Navigation Tabs
    tab_overview, tab_valuation, tab_listings, tab_rentals, tab_distress, tab_deals, tab_pipeline = st.tabs([
        "📊 Market Overview",
        "📉 Price vs. SqFt Valuation",
        "🏡 Property Listings",
        "🏢 Apartments & Rentals",
        "⚖️ Eviction & Foreclosure Trends",
        "🎯 Price Drop Alerts & Rules",
        "⚡ Ingestion & Live Scraper"
    ])

    # ----------------------------------------------------
    # TAB 1: Market Overview
    # ----------------------------------------------------
    with tab_overview:
        if df.empty:
            st.warning("No properties found matching current filter criteria.")
        else:
            col_chart_1, col_chart_2 = st.columns([1, 1])

            with col_chart_1:
                st.subheader("Submarket Median Price & $/SqFt Comparison")
                submarket_df = compute_submarket_breakdown(df)
                if not submarket_df.empty:
                    fig_sub = go.Figure()
                    fig_sub.add_trace(go.Bar(
                        x=submarket_df["city"],
                        y=submarket_df["median_price"],
                        name="Median Price ($)",
                        marker_color="#3b82f6",
                        yaxis="y"
                    ))
                    fig_sub.add_trace(go.Scatter(
                        x=submarket_df["city"],
                        y=submarket_df["median_sqft_price"],
                        name="Median $/SqFt",
                        mode="lines+markers",
                        marker=dict(color="#10b981", size=10),
                        yaxis="y2"
                    ))
                    fig_sub.update_layout(
                        yaxis=dict(title="Median List Price ($)", tickformat="$,.0f"),
                        yaxis2=dict(title="$/SqFt ($)", overlaying="y", side="right", tickformat="$.1f"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        margin=dict(l=20, r=20, t=30, b=20),
                        template="plotly_dark",
                        height=380
                    )
                    st.plotly_chart(fig_sub, width="stretch")

            with col_chart_2:
                st.subheader("Days on Market (DOM) Distribution")
                fig_dom = px.histogram(
                    df,
                    x="days_on_market",
                    nbins=20,
                    color="city",
                    labels={"days_on_market": "Days on Market (DOM)", "count": "Properties"},
                    template="plotly_dark"
                )
                fig_dom.update_layout(
                    margin=dict(l=20, r=20, t=30, b=20),
                    height=380
                )
                st.plotly_chart(fig_dom, width="stretch")

            # ZIP Code Breakdown Table
            st.subheader("📍 ZIP Code Breakdown (Gwinnett & North Fulton)")
            zip_df = compute_zip_code_breakdown(df)
            if not zip_df.empty:
                st.dataframe(
                    zip_df.rename(columns={
                        "city": "Submarket",
                        "zip_code": "ZIP",
                        "inventory_count": "Active Listings",
                        "median_price": "Median Price ($)",
                        "median_sqft_price": "Median $/SqFt",
                        "median_dom": "Median DOM",
                        "price_drop_count": "Price Drop Count",
                        "price_drop_rate": "Price Drop Rate (%)"
                    }),
                    width="stretch",
                    hide_index=True
                )

    # ----------------------------------------------------
    # TAB 2: Price vs. SqFt Valuation
    # ----------------------------------------------------
    with tab_valuation:
        if df.empty:
            st.warning("No listings available.")
        else:
            st.subheader("List Price vs. Square Footage (Valuation Scatter)")
            st.caption("Hover over points to inspect address, price, $/sqft, and days on market.")

            fig_scatter = px.scatter(
                df,
                x="sqft",
                y="current_list_price",
                color="city",
                symbol="is_price_drop",
                size="days_on_market",
                hover_name="formatted_address",
                hover_data={
                    "current_list_price": ":$,.0f",
                    "price_per_sqft": ":$.1f",
                    "days_on_market": True,
                    "beds": True,
                    "full_baths": True,
                    "is_price_drop": True,
                    "price_drop_pct": ":.1f%"
                },
                labels={
                    "sqft": "Square Feet (Living Area)",
                    "current_list_price": "Current List Price ($)",
                    "city": "Submarket",
                    "is_price_drop": "Price Cut?"
                },
                template="plotly_dark",
                height=520
            )

            # Add bargain threshold line ($220/sqft reference)
            max_sqft = df["sqft"].max() or 5000
            x_line = np.linspace(1000, max_sqft, 50)
            y_line = x_line * 220.0
            fig_scatter.add_trace(go.Scatter(
                x=x_line,
                y=y_line,
                mode="lines",
                name="Bargain Threshold ($220/sqft)",
                line=dict(color="#10b981", dash="dash")
            ))

            st.plotly_chart(fig_scatter, width="stretch")

            # DuckDB OLAP Cohorts Analysis
            st.subheader("⚡ DuckDB Accelerated Cohort Analytics")
            adv = compute_duckdb_advanced_analytics()
            col_adv_1, col_adv_2 = st.columns(2)

            with col_adv_1:
                st.markdown("**Submarket Price Quartiles (p25, Median, p75)**")
                if adv.get("city_quantiles"):
                    q_df = pd.DataFrame(adv["city_quantiles"])
                    st.dataframe(q_df, width="stretch", hide_index=True)

            with col_adv_2:
                st.markdown("**Days on Market (DOM) Cohort Pricing**")
                if adv.get("dom_cohorts"):
                    dom_df = pd.DataFrame(adv["dom_cohorts"])
                    st.dataframe(dom_df, width="stretch", hide_index=True)

    # ----------------------------------------------------
    # TAB 3: Property Listings
    # ----------------------------------------------------
    with tab_listings:
        if df.empty:
            st.warning("No properties found matching current filter criteria.")
        else:
            # Property Cards Gallery
            st.subheader(f"🏡 Property Listings ({len(df)} properties)")

            sort_option = st.selectbox(
                "Sort Listings By",
                ["Lowest $/SqFt (Deals First)", "Highest Price Drop %", "Newest / Lowest DOM", "Price: Low to High", "Price: High to Low"]
            )

            if sort_option == "Lowest $/SqFt (Deals First)":
                sorted_df = df.sort_values(by="price_per_sqft", ascending=True)
            elif sort_option == "Highest Price Drop %":
                sorted_df = df.sort_values(by="price_drop_pct", ascending=False)
            elif sort_option == "Newest / Lowest DOM":
                sorted_df = df.sort_values(by="days_on_market", ascending=True)
            elif sort_option == "Price: Low to High":
                sorted_df = df.sort_values(by="current_list_price", ascending=True)
            else:
                sorted_df = df.sort_values(by="current_list_price", ascending=False)

            # Paginate listings so every filtered property is reachable
            total_listings = len(sorted_df)

            def _set_listings_page(target_page: int) -> None:
                st.session_state["listings_page_num"] = target_page

            pg_col1, pg_col2 = st.columns([1, 3])
            with pg_col1:
                page_size = st.selectbox(
                    "Listings per page",
                    [15, 30, 50, 100],
                    index=0,
                    key="listings_page_size",
                    on_change=_set_listings_page,
                    args=(1,)
                )
            total_pages = max(1, -(-total_listings // page_size))
            page_num = min(max(1, int(st.session_state.get("listings_page_num", 1))), total_pages)
            st.session_state["listings_page_num"] = page_num
            start_idx = (page_num - 1) * page_size
            end_idx = min(start_idx + page_size, total_listings)
            with pg_col2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                st.caption(f"Page **{page_num}** of **{total_pages}** · Showing **{start_idx + 1}–{end_idx}** of **{total_listings}** listings")

            top_listings = sorted_df.iloc[start_idx:end_idx].to_dict(orient="records")
            for prop in top_listings:
                with st.container():
                    p_col1, p_col2 = st.columns([1, 3])
                    with p_col1:
                        photo = prop.get("primary_photo") or "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?w=800&auto=format&fit=crop&q=60"
                        st.image(photo, width="stretch")
                    with p_col2:
                        # Clean inline-styled HTML badges rendered directly via st.html() to avoid markdown/LaTeX parsing
                        badges = [
                            f"<span style='background-color:#2563eb;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>{prop['city']} ({prop['zip_code']})</span>"
                        ]
                        if prop.get("is_foreclosure"):
                            badges.append(
                                "<span style='background-color:#d97706;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>⚠️ Foreclosure / Bank Owned</span>"
                            )
                        if prop.get("is_price_drop"):
                            drop_pct = prop.get("price_drop_pct") or 0.0
                            drop_amt = prop.get("price_drop_amount") or 0.0
                            badges.append(
                                f"<span style='background-color:#dc2626;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>🔥 -{drop_pct:.1f}% (-${drop_amt:,.0f})</span>"
                            )
                        if prop.get("price_per_sqft") and prop["price_per_sqft"] <= 220:
                            badges.append(
                                f"<span style='background-color:#059669;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>💎 ${prop['price_per_sqft']:.0f}/sqft Bargain</span>"
                            )
                        if prop.get("listing_source") == "Auction / Legal Notice":
                            badges.append(
                                "<span style='background-color:#7c3aed;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>🏛️ Courthouse Auction / Notice</span>"
                            )

                        # Source badge: origin website (from listing URL) + ingestion feed
                        site_name, site_color = get_listing_site(prop.get("property_url"), prop.get("listing_source"))
                        feed_name = prop.get("listing_source") or "MLS/Realtor"
                        badges.append(
                            f"<span title='Ingestion feed: {feed_name}' style='background-color:transparent;color:{site_color};border:1px solid {site_color};padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>🔗 Source: {site_name} · {feed_name}</span>"
                        )

                        badges_html = f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;'>{''.join(badges)}</div>"
                        st.html(badges_html)

                        st.markdown(f"### \\${prop['current_list_price']:,.0f}")
                        st.markdown(f"**{md_escape(prop['formatted_address'])}**")
                        sqft_txt = f"{int(prop['sqft']):,}" if prop.get('sqft') else "-"
                        ppsf_txt = f"\\${prop['price_per_sqft']:.1f}/sqft" if prop.get('price_per_sqft') else "n/a"
                        st.caption(f"🛏️ {int(prop['beds']) if prop['beds'] else '-'} Beds | 🛁 {int(prop['full_baths']) if prop['full_baths'] else '-'} Baths | 📐 {sqft_txt} SqFt ({ppsf_txt}) | ⏱️ {prop['days_on_market']} DOM | 🏛️ Built {int(prop['year_built']) if pd.notna(prop.get('year_built')) else '-'}")
                        
                        listing_url = prop.get("property_url")
                        if listing_url and str(listing_url).strip() and str(listing_url) != "None":
                            st.link_button(f"View on {site_name} ↗", listing_url, type="primary")
                        else:
                            st.link_button("View Submarket MLS Search ↗", f"https://www.realtor.com/realestateandhomes-search/{prop['zip_code']}", type="secondary")
                    st.divider()

            # Bottom numbered pager (synced with the top page input via session state)
            if total_pages > 1:
                current_page = int(page_num)
                window = 2
                page_items = []
                for p in range(1, total_pages + 1):
                    if p == 1 or p == total_pages or abs(p - current_page) <= window:
                        page_items.append(p)
                    elif page_items and page_items[-1] != "…":
                        page_items.append("…")

                slots = ["prev"] + page_items + ["next"]
                _, pager_center, _ = st.columns([1, 4, 1])
                with pager_center:
                    pager_cols = st.columns(len(slots))
                    for i, item in enumerate(slots):
                        with pager_cols[i]:
                            if item == "prev":
                                st.button(
                                    "‹ Prev", key="listings_pager_prev", width="stretch",
                                    disabled=current_page <= 1,
                                    on_click=_set_listings_page, args=(current_page - 1,)
                                )
                            elif item == "next":
                                st.button(
                                    "Next ›", key="listings_pager_next", width="stretch",
                                    disabled=current_page >= total_pages,
                                    on_click=_set_listings_page, args=(current_page + 1,)
                                )
                            elif item == "…":
                                st.markdown("<div style='text-align:center;padding-top:6px;color:#94a3b8;'>…</div>", unsafe_allow_html=True)
                            else:
                                st.button(
                                    str(item), key=f"listings_pager_{item}", width="stretch",
                                    type="primary" if item == current_page else "secondary",
                                    on_click=_set_listings_page, args=(item,)
                                )
                st.caption(f"<div style='text-align:center;'>Page {current_page} of {total_pages} · Showing {start_idx + 1}–{end_idx} of {total_listings} listings</div>", unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 4: Apartments & Rentals
    # ----------------------------------------------------
    with tab_rentals:
        st.subheader("🏢 Metro Atlanta Apartment & Rental Tracker")
        st.caption(
            "Live multi-family communities, apartment complexes, and rental properties scraped across Duluth, Suwanee, Norcross, Alpharetta, Atlanta, and surrounding North Metro submarkets."
        )

        # Rental Submarket / Parameter Filters Bar
        r_fcol1, r_fcol2, r_fcol3, r_fcol4 = st.columns([1.2, 1.2, 1.2, 1.4])
        with r_fcol1:
            rent_beds_filter = st.selectbox(
                "Bedroom Minimum",
                ["All Bedrooms", "1+ Beds", "2+ Beds", "3+ Beds", "4+ Beds"],
                index=0,
                key="rent_beds_filter"
            )
        with r_fcol2:
            rent_max_slider = st.slider(
                "Max Monthly Rent ($)",
                min_value=800,
                max_value=5000,
                value=4000,
                step=100,
                format="$%d/mo",
                key="rent_max_slider"
            )
        with r_fcol3:
            rent_sort_option = st.selectbox(
                "Sort Rentals By",
                [
                    "Rent: Low to High",
                    "Rent: High to Low",
                    "Lowest $/SqFt",
                    "Newest / Lowest DOM",
                    "Most Bedrooms"
                ],
                index=0,
                key="rent_sort_option"
            )
        with r_fcol4:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("🔄 Scrape / Refresh Rentals", key="refresh_rentals_btn", width="stretch"):
                with st.spinner("Scraping live apartment listings from Realtor.com Rentals..."):
                    res = run_rental_pipeline(
                        submarkets=selected_cities if selected_cities else ["Duluth", "Suwanee", "Norcross", "Alpharetta", "Atlanta"],
                        limit_per_zip=15
                    )
                    st.success(f"Ingested {res.get('inserted', 0)} new and updated {res.get('updated', 0)} rental records!")
                    st.rerun()

        # Query Rental Dataframe
        min_beds_val = None
        if rent_beds_filter == "1+ Beds":
            min_beds_val = 1
        elif rent_beds_filter == "2+ Beds":
            min_beds_val = 2
        elif rent_beds_filter == "3+ Beds":
            min_beds_val = 3
        elif rent_beds_filter == "4+ Beds":
            min_beds_val = 4

        raw_rentals_df = get_rentals_dataframe(
            cities=selected_cities if selected_cities else None,
            zip_codes=selected_zips if selected_zips else None,
            min_beds=min_beds_val,
            max_rent=rent_max_slider
        )

        if raw_rentals_df.empty:
            st.warning("No rental properties found matching current filter criteria. Try expanding your search or clicking '🔄 Scrape / Refresh Rentals'.")
        else:
            # Rental Executive KPI Strip
            total_rentals = len(raw_rentals_df)
            median_rent = raw_rentals_df["monthly_rent"].median() if not raw_rentals_df["monthly_rent"].empty else 0
            min_rent = raw_rentals_df["monthly_rent"].min() if not raw_rentals_df["monthly_rent"].empty else 0
            max_rent = raw_rentals_df["monthly_rent"].max() if not raw_rentals_df["monthly_rent"].empty else 0
            sqft_mask = raw_rentals_df["rent_per_sqft"].notna() & (raw_rentals_df["rent_per_sqft"] > 0)
            median_rent_sqft = raw_rentals_df.loc[sqft_mask, "rent_per_sqft"].median() if sqft_mask.any() else 0.0
            
            top_city = raw_rentals_df["city"].value_counts().index[0] if "city" in raw_rentals_df.columns and not raw_rentals_df.empty else "N/A"
            top_city_count = raw_rentals_df["city"].value_counts().iloc[0] if "city" in raw_rentals_df.columns and not raw_rentals_df.empty else 0

            rk1, rk2, rk3, rk4, rk5 = st.columns(5)
            rk1.metric("Active Rentals", f"{total_rentals:,} units")
            rk2.metric("Median Rent", f"${median_rent:,.0f} / mo" if median_rent > 0 else "N/A")
            rk3.metric("Rent Range", f"${min_rent:,.0f} – ${max_rent:,.0f}" if min_rent > 0 else "N/A")
            rk4.metric("Median Rent / SqFt", f"${median_rent_sqft:.2f} / sqft" if median_rent_sqft > 0 else "N/A")
            rk5.metric("Top Rental Market", f"{top_city}", f"{top_city_count} listings")

            st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

            # Rental Visual Charts
            r_chart_col1, r_chart_col2 = st.columns([1, 1])

            with r_chart_col1:
                st.subheader("Submarket Median Rent Comparison")
                city_rent_stats = (
                    raw_rentals_df.groupby("city")
                    .agg(
                        median_rent=("monthly_rent", "median"),
                        count=("id", "count"),
                        min_rent=("monthly_rent", "min"),
                        max_rent=("monthly_rent", "max")
                    )
                    .reset_index()
                    .sort_values(by="median_rent", ascending=False)
                )
                fig_rent_city = px.bar(
                    city_rent_stats,
                    x="city",
                    y="median_rent",
                    color="median_rent",
                    color_continuous_scale="Viridis",
                    text="median_rent",
                    labels={"city": "Submarket", "median_rent": "Median Rent ($/mo)"},
                    template="plotly_dark",
                    hover_data=["count", "min_rent", "max_rent"]
                )
                fig_rent_city.update_traces(
                    texttemplate="$%{y:,.0f}",
                    textposition="outside",
                    marker_line_color="rgba(255,255,255,0.2)",
                    marker_line_width=1
                )
                fig_rent_city.update_layout(
                    height=350,
                    margin=dict(l=10, r=10, t=20, b=30),
                    plot_bgcolor="rgba(15, 23, 42, 0.6)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    coloraxis_showscale=False,
                    yaxis_title="Median Monthly Rent ($)"
                )
                st.plotly_chart(fig_rent_city, width="stretch")

            with r_chart_col2:
                st.subheader("Monthly Rent by Bedroom Count")
                bed_df = raw_rentals_df[raw_rentals_df["beds"].notna() & (raw_rentals_df["beds"] > 0)].copy()
                if not bed_df.empty:
                    bed_df["beds_label"] = bed_df["beds"].apply(lambda b: f"{int(b)} Bed" if b == 1 else f"{int(b)} Beds")
                    bed_order = sorted(bed_df["beds_label"].unique(), key=lambda x: int(x.split()[0]))
                    fig_bed_box = px.box(
                        bed_df,
                        x="beds_label",
                        y="monthly_rent",
                        category_orders={"beds_label": bed_order},
                        color="beds_label",
                        labels={"beds_label": "Bedrooms", "monthly_rent": "Monthly Rent ($/mo)"},
                        template="plotly_dark"
                    )
                    fig_bed_box.update_layout(
                        height=350,
                        margin=dict(l=10, r=10, t=20, b=30),
                        plot_bgcolor="rgba(15, 23, 42, 0.6)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        showlegend=False,
                        yaxis_title="Monthly Rent ($)"
                    )
                    st.plotly_chart(fig_bed_box, width="stretch")
                else:
                    st.info("No bedroom data available for chart.")

            # Sorting logic for rental cards
            sorted_rentals = raw_rentals_df.copy()
            if rent_sort_option == "Rent: Low to High":
                sorted_rentals = sorted_rentals.sort_values(by="monthly_rent", ascending=True)
            elif rent_sort_option == "Rent: High to Low":
                sorted_rentals = sorted_rentals.sort_values(by="monthly_rent", ascending=False)
            elif rent_sort_option == "Lowest $/SqFt":
                sorted_rentals = sorted_rentals.sort_values(by="rent_per_sqft", ascending=True, na_position="last")
            elif rent_sort_option == "Newest / Lowest DOM":
                sorted_rentals = sorted_rentals.sort_values(by="days_on_market", ascending=True)
            elif rent_sort_option == "Most Bedrooms":
                sorted_rentals = sorted_rentals.sort_values(by="beds", ascending=False, na_position="last")

            # Rental Pagination
            total_rental_listings = len(sorted_rentals)

            def _set_rentals_page(target_page: int) -> None:
                st.session_state["rentals_page_num"] = target_page

            r_pg_col1, r_pg_col2 = st.columns([1, 3])
            with r_pg_col1:
                r_page_size = st.selectbox(
                    "Rentals per page",
                    [15, 30, 50, 100],
                    index=0,
                    key="rentals_page_size",
                    on_change=_set_rentals_page,
                    args=(1,)
                )
            r_total_pages = max(1, -(-total_rental_listings // r_page_size))
            r_page_num = min(max(1, int(st.session_state.get("rentals_page_num", 1))), r_total_pages)
            st.session_state["rentals_page_num"] = r_page_num
            r_start_idx = (r_page_num - 1) * r_page_size
            r_end_idx = min(r_start_idx + r_page_size, total_rental_listings)
            with r_pg_col2:
                st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                st.caption(f"Page **{r_page_num}** of **{r_total_pages}** · Showing **{r_start_idx + 1}–{r_end_idx}** of **{total_rental_listings}** rentals")

            # Render Rental Cards
            paged_rentals = sorted_rentals.iloc[r_start_idx:r_end_idx].to_dict(orient="records")
            for rent in paged_rentals:
                with st.container():
                    rp_col1, rp_col2 = st.columns([1, 3])
                    with rp_col1:
                        rent_photo = rent.get("primary_photo") or "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800&auto=format&fit=crop&q=60"
                        st.image(rent_photo, width="stretch")
                    with rp_col2:
                        rent_badges = [
                            f"<span style='background-color:#2563eb;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>{rent['city']} ({rent['zip_code']})</span>"
                        ]
                        rent_style = rent.get("style") or "APARTMENT"
                        rent_badges.append(
                            f"<span style='background-color:#0284c7;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>🏢 {rent_style.title()}</span>"
                        )
                        if rent.get("rent_per_sqft") and rent["rent_per_sqft"] > 0:
                            rent_badges.append(
                                f"<span style='background-color:#059669;color:#ffffff;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>📐 ${rent['rent_per_sqft']:.2f}/sqft</span>"
                            )
                        rent_badges.append(
                            "<span style='background-color:transparent;color:#f87171;border:1px solid #f87171;padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700;display:inline-block;'>🔗 Source: Realtor.com · Rental Community</span>"
                        )
                        badges_html = f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px;'>{''.join(rent_badges)}</div>"
                        st.html(badges_html)

                        r_min = rent.get("rent_min")
                        r_max = rent.get("rent_max")
                        m_rent = rent.get("monthly_rent")
                        if r_min and r_max and r_min != r_max:
                            rent_display = f"\\${r_min:,.0f} – \\${r_max:,.0f} / mo"
                        elif m_rent:
                            rent_display = f"\\${m_rent:,.0f} / mo"
                        else:
                            rent_display = "Contact for Rent"

                        st.markdown(f"### {rent_display}")
                        st.markdown(f"**{md_escape(rent.get('formatted_address', 'Address not disclosed'))}**")
                        
                        beds_val = int(rent['beds']) if rent.get('beds') is not None and not pd.isna(rent['beds']) else "-"
                        baths_val = int(rent['full_baths']) if rent.get('full_baths') is not None and not pd.isna(rent['full_baths']) else "-"
                        sqft_val = f"{int(rent['sqft']):,}" if rent.get('sqft') and not pd.isna(rent['sqft']) and rent['sqft'] > 0 else "-"
                        dom_val = f"{int(rent['days_on_market'])} DOM" if rent.get('days_on_market') is not None and not pd.isna(rent['days_on_market']) else "Active"
                        st.caption(f"🛏️ {beds_val} Beds | 🛁 {baths_val} Baths | 📐 {sqft_val} SqFt | ⏱️ {dom_val}")

                        r_url = rent.get("property_url")
                        if r_url and str(r_url).strip() and str(r_url) != "None":
                            st.link_button("View on Realtor.com Rentals ↗", r_url, type="primary")
                        else:
                            st.link_button("View Submarket Rentals ↗", f"https://www.realtor.com/apartments/{rent['zip_code']}", type="secondary")
                    st.divider()

            # Bottom numbered pager for rentals
            if r_total_pages > 1:
                r_current_page = int(r_page_num)
                r_window = 2
                r_page_items = []
                for p in range(1, r_total_pages + 1):
                    if p == 1 or p == r_total_pages or abs(p - r_current_page) <= r_window:
                        r_page_items.append(p)
                    elif r_page_items and r_page_items[-1] != "…":
                        r_page_items.append("…")

                r_slots = ["prev"] + r_page_items + ["next"]
                _, r_pager_center, _ = st.columns([1, 4, 1])
                with r_pager_center:
                    r_pager_cols = st.columns(len(r_slots))
                    for i, item in enumerate(r_slots):
                        with r_pager_cols[i]:
                            if item == "prev":
                                st.button(
                                    "‹ Prev", key="rentals_pager_prev", width="stretch",
                                    disabled=r_current_page <= 1,
                                    on_click=_set_rentals_page, args=(r_current_page - 1,)
                                )
                            elif item == "next":
                                st.button(
                                    "Next ›", key="rentals_pager_next", width="stretch",
                                    disabled=r_current_page >= r_total_pages,
                                    on_click=_set_rentals_page, args=(r_current_page + 1,)
                                )
                            elif item == "…":
                                st.markdown("<div style='text-align:center;padding-top:6px;color:#94a3b8;'>…</div>", unsafe_allow_html=True)
                            else:
                                st.button(
                                    str(item), key=f"rentals_pager_{item}", width="stretch",
                                    type="primary" if item == r_current_page else "secondary",
                                    on_click=_set_rentals_page, args=(item,)
                                )
                st.caption(f"<div style='text-align:center;'>Page {r_current_page} of {r_total_pages} · Showing {r_start_idx + 1}–{r_end_idx} of {total_rental_listings} rentals</div>", unsafe_allow_html=True)

    # ----------------------------------------------------
    # TAB 5: Eviction & Foreclosure Trends
    # ----------------------------------------------------
    with tab_distress:
        st.subheader("⚖️ Metro Atlanta Historical Distress: Evictions & Foreclosures")
        st.caption("Historical macro indicators tracking mortgage foreclosure pipelines and eviction court filings across Fulton, Gwinnett, and Metro Atlanta counties.")

        # Load historical datasets (cached for performance)
        df_ev = fetch_historical_eviction_filings()
        df_mort = fetch_historical_mortgage_delinquency()

        ev_metrics = compute_eviction_metrics(df_ev)
        mort_metrics = compute_mortgage_delinquency_metrics(df_mort)

        # Official Source Verification & Quick-Links Toolbar
        src_btn_col1, src_btn_col2, src_btn_col3, src_btn_col4 = st.columns(4)
        with src_btn_col1:
            st.link_button(
                "🏛️ Fulton Evictions Portal ↗",
                DATA_SOURCES["evictions"]["page_url"],
                help="Fulton County Government Open Data Socrata Portal",
                width="stretch"
            )
        with src_btn_col2:
            st.link_button(
                "🏦 CFPB Mortgage Trends ↗",
                DATA_SOURCES["mortgage_delinquency"]["page_url"],
                help="Consumer Financial Protection Bureau National Mortgage Database",
                width="stretch"
            )
        with src_btn_col3:
            st.link_button(
                "⚖️ GA Trustee Legal Notices ↗",
                DATA_SOURCES["ga_legal_notices"]["page_url"],
                help="Official Georgia Foreclosure Trustee notices (RLSE Law)",
                width="stretch"
            )
        with src_btn_col4:
            st.link_button(
                "📥 CFPB County Datasets ↗",
                DATA_SOURCES["mortgage_delinquency"]["api_url"],
                help="Direct CSV download portal from CFPB",
                width="stretch"
            )

        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

        # 1. Executive Status Cards (Direct Answers to Key Questions with Verified Citations)
        col_ans_1, col_ans_2 = st.columns(2)

        with col_ans_1:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);border:1px solid #6366f1;border-radius:12px;padding:18px;margin-bottom:16px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-weight:700;font-size:16px;color:#a5b4fc;">⚖️ Are Eviction Filings Increasing?</span>
                    <span style="background:#ef4444;color:white;padding:3px 10px;border-radius:9999px;font-size:11px;font-weight:700;">🔴 HIGH CRISIS PLATEAU</span>
                </div>
                <div style="font-size:26px;font-weight:800;color:#ffffff;margin:8px 0 4px 0;">~3,100 – 3,500 / month</div>
                <p style="color:#cbd5e1;font-size:13px;line-height:1.5;margin-bottom:8px;">
                    <b>Massively elevated vs. pre-pandemic baseline.</b> Fulton County filings jumped from <b>~500/mo</b> in 2016 to over <b>3,400/mo</b> in 2025–2026 (+580% surge). 
                    Metro Atlanta remains the <b>#1 eviction filing epicenter</b> nationwide (~1 in 4 renter households annually). 
                    While recent data shows a slight plateau (-5% from peak), filing volumes remain locked at crisis levels due to cheap court filing fees ($54–$75) and institutional landlord serial filings.
                </p>
                <div style="border-top:1px solid rgba(99,102,241,0.3);padding-top:8px;font-size:12px;color:#a5b4fc;display:flex;justify-content:space-between;align-items:center;">
                    <span>🔗 <b>Source:</b> <a href="{DATA_SOURCES['evictions']['page_url']}" target="_blank" style="color:#c7d2fe;text-decoration:underline;">Fulton County Courts Open Data (Dataset cbu2-qs5w) ↗</a></span>
                    <span style="color:#94a3b8;font-size:11px;">Updated Monthly · Socrata API</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_ans_2:
            st.markdown(f"""
            <div style="background:linear-gradient(135deg, #1e293b 0%, #0f172a 100%);border:1px solid #38bdf8;border-radius:12px;padding:18px;margin-bottom:16px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-weight:700;font-size:16px;color:#7dd3fc;">🏛️ Are Foreclosures Increasing?</span>
                    <span style="background:#f59e0b;color:white;padding:3px 10px;border-radius:9999px;font-size:11px;font-weight:700;">🟡 STEADILY INCREASING</span>
                </div>
                <div style="font-size:26px;font-weight:800;color:#ffffff;margin:8px 0 4px 0;">+100% to +250% vs. 2021 Trough</div>
                <p style="color:#cbd5e1;font-size:13px;line-height:1.5;margin-bottom:8px;">
                    <b>Steadily climbing year-over-year.</b> CFPB serious delinquency rates (90+ days late, the direct foreclosure pipeline) have <b>doubled in Gwinnett County</b> (0.6% in 2021 &rarr; 1.2% in 2025) 
                    and <b>more than tripled in Fulton County</b> (0.4% in 2021 &rarr; 1.4% in 2025). 
                    However, because Metro Atlanta homeowners hold substantial accumulated home equity, the overall rate remains <b>~75% below 2008 Great Recession peak levels (8.0%–9.5%)</b> as distressed owners sell on the open market.
                </p>
                <div style="border-top:1px solid rgba(56,189,248,0.3);padding-top:8px;font-size:12px;color:#7dd3fc;display:flex;justify-content:space-between;align-items:center;">
                    <span>🔗 <b>Source:</b> <a href="{DATA_SOURCES['mortgage_delinquency']['page_url']}" target="_blank" style="color:#bae6fd;text-decoration:underline;">CFPB Mortgage Performance Trends (NMDB) ↗</a></span>
                    <span style="color:#94a3b8;font-size:11px;">Quarterly Series · County Delinquency</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # 2. Macro Metric Strip
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric(
            "Fulton Evictions (Latest Mo)",
            f"{ev_metrics.get('latest_month_filings', 0):,}",
            f"{ev_metrics.get('month_over_month_diff', 0):+} vs prior mo"
        )
        col_m2.metric(
            "Fulton Evictions (12-Mo Rolling)",
            f"{ev_metrics.get('recent_12m_filings', 0):,}",
            "Cases filed"
        )
        gwinnett_delinq = mort_metrics.get("Gwinnett County", {})
        col_m3.metric(
            "Gwinnett 90+ Day Late Rate",
            f"{gwinnett_delinq.get('current_90_plus_late_pct', 0.0):.1f}%",
            f"+{gwinnett_delinq.get('pct_increase_from_trough', 0.0):.0f}% vs 2021 trough"
        )
        fulton_delinq = mort_metrics.get("Fulton County", {})
        col_m4.metric(
            "Fulton 90+ Day Late Rate",
            f"{fulton_delinq.get('current_90_plus_late_pct', 0.0):.1f}%",
            f"+{fulton_delinq.get('pct_increase_from_trough', 0.0):.0f}% vs 2021 trough"
        )

        st.markdown("---")

        # 3. Interactive Charts & Verification Section
        tab_ev_chart, tab_mort_chart, tab_annual_chart, tab_sources_meta = st.tabs([
            "📈 Monthly Eviction Filings Timeline (2016 – 2026)",
            "🏛️ Mortgage Delinquency & Foreclosure Pipeline (2008 – 2025)",
            "📊 Annual Totals & Multi-Year Comparison",
            "📚 Data Sources, Methodology & Raw Data"
        ])

        with tab_ev_chart:
            if not df_ev.empty:
                st.markdown("#### Monthly Eviction Filings (Fulton County Magistrate & Superior Courts)")
                st.markdown(
                    f"Official Socrata monthly dataset tracking dispossessory warrants. "
                    f"🔗 **Primary Source Link:** [{DATA_SOURCES['evictions']['name']} ({DATA_SOURCES['evictions']['publisher']}) ↗]({DATA_SOURCES['evictions']['page_url']}) · "
                    f"[Raw API Endpoint ↗]({DATA_SOURCES['evictions']['api_url']})"
                )

                # Calculate 3-month rolling average
                df_ev_plot = df_ev.copy()
                df_ev_plot["rolling_3m"] = df_ev_plot["filings"].rolling(3, min_periods=1).mean()

                fig_ev = go.Figure()
                fig_ev.add_trace(go.Bar(
                    x=df_ev_plot["date"],
                    y=df_ev_plot["filings"],
                    name="Monthly Filings",
                    marker_color="#818cf8",
                    opacity=0.65
                ))
                fig_ev.add_trace(go.Scatter(
                    x=df_ev_plot["date"],
                    y=df_ev_plot["rolling_3m"],
                    name="3-Month Moving Average",
                    mode="lines",
                    line=dict(color="#f43f5e", width=3)
                ))
                # Add moratorium reference line/shading
                fig_ev.add_vrect(
                    x0="2020-03-01", x1="2021-08-31",
                    fillcolor="#38bdf8", opacity=0.1,
                    layer="below", line_width=0,
                    annotation_text="CDC / CARES Moratorium", annotation_position="top left"
                )
                fig_ev.update_layout(
                    yaxis=dict(title="Eviction Filings (Cases)", tickformat=","),
                    xaxis=dict(title="Filing Date"),
                    template="plotly_dark",
                    height=420,
                    margin=dict(l=20, r=20, t=30, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_ev, width="stretch")

        with tab_mort_chart:
            if not df_mort.empty:
                st.markdown("#### CFPB Mortgage 90+ Days Delinquent Rate (%) by County (2008 – 2025)")
                st.markdown(
                    f"National Mortgage Database (NMDB) county-level time-series. "
                    f"🔗 **Primary Source Link:** [{DATA_SOURCES['mortgage_delinquency']['name']} ({DATA_SOURCES['mortgage_delinquency']['publisher']}) ↗]({DATA_SOURCES['mortgage_delinquency']['page_url']}) · "
                    f"[CFPB Download Portal ↗]({DATA_SOURCES['mortgage_delinquency']['api_url']})"
                )

                # County filter selector
                selected_mort_counties = st.multiselect(
                    "Filter Counties for Mortgage Delinquency Trend:",
                    options=sorted(df_mort["county"].unique()),
                    default=["Gwinnett County", "Fulton County", "DeKalb County", "Cobb County"]
                )
                df_mort_filtered = df_mort[df_mort["county"].isin(selected_mort_counties)]

                fig_mort = px.line(
                    df_mort_filtered,
                    x="date",
                    y="late_90_plus_pct",
                    color="county",
                    labels={"late_90_plus_pct": "90+ Days Late / Foreclosure Rate (%)", "date": "Date"},
                    template="plotly_dark",
                    color_discrete_map={
                        "Gwinnett County": "#38bdf8",
                        "Fulton County": "#f43f5e",
                        "DeKalb County": "#fbbf24",
                        "Cobb County": "#34d399",
                        "Forsyth County": "#a78bfa"
                    }
                )
                fig_mort.update_layout(
                    yaxis=dict(title="90+ Days Delinquent Rate (%)", tickformat=".1f"),
                    xaxis=dict(title="Date"),
                    height=420,
                    margin=dict(l=20, r=20, t=30, b=20),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_mort, width="stretch")

        with tab_annual_chart:
            col_ann_1, col_ann_2 = st.columns(2)
            with col_ann_1:
                st.markdown("#### Annual Eviction Filings (Fulton County)")
                st.caption(f"Source: [Fulton County Courts Open Data ↗]({DATA_SOURCES['evictions']['page_url']})")
                if not df_ev.empty:
                    df_annual = df_ev.groupby("year")["filings"].sum().reset_index()
                    fig_ann_ev = px.bar(
                        df_annual,
                        x="year",
                        y="filings",
                        text="filings",
                        labels={"year": "Year", "filings": "Total Cases Filed"},
                        template="plotly_dark",
                        color_discrete_sequence=["#6366f1"]
                    )
                    fig_ann_ev.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
                    fig_ann_ev.update_layout(height=380, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig_ann_ev, width="stretch")

            with col_ann_2:
                st.markdown("#### 90+ Day Delinquency vs 30–89 Day Delinquency (Gwinnett & Fulton)")
                st.caption(f"Source: [CFPB Mortgage Performance Trends ↗]({DATA_SOURCES['mortgage_delinquency']['page_url']})")
                if not df_mort.empty:
                    recent_mort = df_mort[df_mort["county"].isin(["Gwinnett County", "Fulton County"])].groupby(["county", "year"])[["late_90_plus_pct", "late_30_89_pct"]].mean().reset_index()
                    recent_mort = recent_mort[recent_mort["year"] >= 2018]
                    fig_ann_mort = px.bar(
                        recent_mort,
                        x="year",
                        y="late_90_plus_pct",
                        color="county",
                        barmode="group",
                        labels={"late_90_plus_pct": "Avg 90+ Days Delinquent (%)", "year": "Year"},
                        template="plotly_dark"
                    )
                    fig_ann_mort.update_layout(height=380, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig_ann_mort, width="stretch")

        with tab_sources_meta:
            st.markdown("### 📚 Data Sources, Provenance & Direct Access Links")
            st.caption("Complete attribution, update cadence, methodologies, and raw download links for all macroeconomic and distress indicators tracked in this module.")

            # Fixed-height cards so both source boxes (and their buttons) align side by side
            source_card_style = (
                "background:#1e293b;border:1px solid #475569;border-radius:10px;padding:16px;"
                "margin-bottom:14px;height:250px;box-sizing:border-box;overflow:auto;"
            )

            s_col1, s_col2 = st.columns(2)

            with s_col1:
                st.markdown(f"""
                <div style="{source_card_style}">
                    <h4 style="color:#a5b4fc;margin:0 0 8px 0;">1. {DATA_SOURCES['evictions']['name']}</h4>
                    <p style="font-size:13px;color:#cbd5e1;line-height:1.5;">
                        <b>Publisher:</b> {DATA_SOURCES['evictions']['publisher']}<br>
                        <b>Geographic Scope:</b> {DATA_SOURCES['evictions']['coverage']}<br>
                        <b>Update Cadence:</b> {DATA_SOURCES['evictions']['frequency']}<br>
                        <b>Methodology Note:</b> {DATA_SOURCES['evictions']['notes']}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                st.link_button(
                    "🔗 Open Fulton County Socrata Dataset ↗",
                    DATA_SOURCES["evictions"]["page_url"],
                    width="stretch",
                    type="primary"
                )

            with s_col2:
                st.markdown(f"""
                <div style="{source_card_style}">
                    <h4 style="color:#7dd3fc;margin:0 0 8px 0;">2. {DATA_SOURCES['mortgage_delinquency']['name']}</h4>
                    <p style="font-size:13px;color:#cbd5e1;line-height:1.5;">
                        <b>Publisher:</b> {DATA_SOURCES['mortgage_delinquency']['publisher']}<br>
                        <b>Geographic Scope:</b> {DATA_SOURCES['mortgage_delinquency']['coverage']}<br>
                        <b>Update Cadence:</b> {DATA_SOURCES['mortgage_delinquency']['frequency']}<br>
                        <b>Methodology Note:</b> {DATA_SOURCES['mortgage_delinquency']['notes']}
                    </p>
                </div>
                """, unsafe_allow_html=True)
                st.link_button(
                    "🔗 Open CFPB National Mortgage Trends ↗",
                    DATA_SOURCES["mortgage_delinquency"]["page_url"],
                    width="stretch",
                    type="primary"
                )

            st.markdown("---")

            # Raw Data Inspector & Download section
            st.markdown("#### 🔍 Raw Data Inspector & CSV Export")
            data_choice = st.radio("Select Dataset to Preview:", ["Fulton County Eviction Filings", "CFPB Mortgage Delinquency Rates"], horizontal=True)

            def _format_date_cols(frame: pd.DataFrame) -> pd.DataFrame:
                """Render date-like columns as YYYY-MM-DD (drop time component)."""
                frame = frame.copy()
                for col in frame.columns:
                    if col in ("date", "monthdate") or pd.api.types.is_datetime64_any_dtype(frame[col]):
                        frame[col] = pd.to_datetime(frame[col], errors="coerce").dt.strftime("%Y-%m-%d")
                return frame

            if data_choice == "Fulton County Eviction Filings":
                if not df_ev.empty:
                    preview_ev = _format_date_cols(df_ev.sort_values("date", ascending=False).reset_index(drop=True))
                    st.dataframe(
                        preview_ev.rename(columns={
                            "monthdate": "Month Date",
                            "date": "Date",
                            "month": "Month (YYYY-MM)",
                            "filings": "Dispossessory Filings",
                            "county": "County",
                            "source": "Source Attribution"
                        }),
                        width="stretch",
                        hide_index=True
                    )
                    csv_ev = preview_ev.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "📥 Download Fulton Eviction Data (CSV)",
                        data=csv_ev,
                        file_name="fulton_county_evictions_historical.csv",
                        mime="text/csv"
                    )
            else:
                if not df_mort.empty:
                    preview_mort = _format_date_cols(df_mort.sort_values(["county", "date"], ascending=[True, False]).reset_index(drop=True))
                    st.dataframe(
                        preview_mort.rename(columns={
                            "county": "County",
                            "date": "Date",
                            "month": "Month",
                            "late_90_plus_pct": "90+ Days Late (%)",
                            "late_30_89_pct": "30-89 Days Late (%)"
                        }),
                        width="stretch",
                        hide_index=True
                    )
                    csv_mort = preview_mort.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "📥 Download CFPB Mortgage Delinquency Data (CSV)",
                        data=csv_mort,
                        file_name="cfpb_metro_atlanta_mortgage_delinquency.csv",
                        mime="text/csv"
                    )

    # ----------------------------------------------------
    # TAB 5: Price Drop Alerts & Rules (Redesigned)
    # ----------------------------------------------------
    with tab_deals:
        st.subheader("🎯 Price Drop Tracker & Deal Alerts")
        st.caption("Monitoring Metro Atlanta price cuts: **How much did sellers drop their price?** and **Within how long did they cut it?**")

        # Top Executive Explanation Banner
        st.html("""
        <div style="background: linear-gradient(90deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
                    border-left: 4px solid #ef4444; border-radius: 8px; padding: 12px 18px; margin-bottom: 20px;">
            <div style="font-size: 14px; font-weight: 700; color: #f87171; margin-bottom: 4px;">
                💡 KEY QUESTIONS ANSWERED AT A GLANCE
            </div>
            <div style="font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                • <strong>HOW MUCH:</strong> Exact dollar reduction (<code>-$XX,XXX</code>) and percentage cut (<code>-%X.X</code>) from initial list price to current price.<br>
                • <strong>WITHIN HOW LONG:</strong> The seller's urgency velocity—how many days the home sat on market before the cut took place, and how recently the drop occurred.
            </div>
        </div>
        """)

        with get_session() as session:
            drop_summary = compute_price_drop_summary(session)
            rules_list = get_alert_rules(session)
            recent_alerts = get_recent_alerts(session, limit=40)

        kpis = drop_summary["kpis"]
        all_deals = drop_summary["deals"]

        # 4 Key Scorecard Metrics
        kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
        kpi_c1.metric(
            "📉 Active Price Slashes",
            f"{kpis['total_deals']} Properties",
            help="Total active listings that have undergone seller price reductions"
        )
        kpi_c2.metric(
            "💰 Average Price Cut",
            f"-${kpis['avg_drop_amount']:,.0f}" if kpis["total_deals"] > 0 else "$0",
            f"-{kpis['avg_drop_pct']:.1f}% avg cut" if kpis["total_deals"] > 0 else "0%",
            delta_color="inverse"
        )
        kpi_c3.metric(
            "⏱️ Avg Time to Price Cut",
            f"{int(kpis['avg_days_to_drop'])} Days" if kpis["total_deals"] > 0 else "N/A",
            help="Average days on market before seller reduced price"
        )
        kpi_c4.metric(
            "⚡ Fastest Price Reduction",
            f"{kpis['fastest_cut']} Days" if kpis["total_deals"] > 0 else "N/A",
            help="Shortest time between initial listing and price cut"
        )

        st.markdown("<div style='margin-bottom: 15px;'></div>", unsafe_allow_html=True)

        # 4 Clean Sub-tabs
        subtab_deals, subtab_table, subtab_feed, subtab_rules = st.tabs([
            "🏷️ Deal Cards (How Much & How Long)",
            "📋 Price Cut Comparison Table",
            "🚨 Filtered Alert Logs",
            "⚙️ Alert Rules & Settings"
        ])

        # ----------------------------------------------------
        # SUB-TAB 1: Deal Cards (How Much & How Long)
        # ----------------------------------------------------
        with subtab_deals:
            if not all_deals:
                st.info("ℹ️ No active price drops recorded yet in the database. Use **Tab 6: Ingestion** to run scrapers or seed demo listings.")
            else:
                # Interactive filter toolbar
                fc1, fc2, fc3, fc4 = st.columns([1.5, 1.2, 1.3, 1.5])
                with fc1:
                    deal_cities = sorted(list(set(d["city"] for d in all_deals)))
                    sel_cities = st.multiselect("Filter by City", deal_cities, default=deal_cities, key="deal_city_filter")
                with fc2:
                    min_pct_opt = st.selectbox(
                        "Min Drop %",
                        ["All Drops", "> 3% Drop", "> 5% Drop", "> 10% Drop"],
                        index=0,
                        key="deal_min_pct"
                    )
                with fc3:
                    velocity_opt = st.selectbox(
                        "Seller Urgency / Speed",
                        ["All Speeds", "⚡ Fast (< 14 days)", "⏳ Steady (15–30 days)", "🐌 Stale (> 30 days)"],
                        index=0,
                        key="deal_velocity_filter"
                    )
                with fc4:
                    sort_deals_by = st.selectbox(
                        "Sort Deals By",
                        ["Largest $ Cut First", "Highest % Cut First", "Fastest Cut First (Lowest Days)", "Newest Cut First"],
                        index=0,
                        key="deal_sort_opt"
                    )

                # Apply filters
                filtered_deals = [d for d in all_deals if d["city"] in sel_cities]
                if min_pct_opt == "> 3% Drop":
                    filtered_deals = [d for d in filtered_deals if d["drop_pct"] >= 3.0]
                elif min_pct_opt == "> 5% Drop":
                    filtered_deals = [d for d in filtered_deals if d["drop_pct"] >= 5.0]
                elif min_pct_opt == "> 10% Drop":
                    filtered_deals = [d for d in filtered_deals if d["drop_pct"] >= 10.0]

                if velocity_opt == "⚡ Fast (< 14 days)":
                    filtered_deals = [d for d in filtered_deals if d["days_to_drop"] <= 14]
                elif velocity_opt == "⏳ Steady (15–30 days)":
                    filtered_deals = [d for d in filtered_deals if 15 <= d["days_to_drop"] <= 30]
                elif velocity_opt == "🐌 Stale (> 30 days)":
                    filtered_deals = [d for d in filtered_deals if d["days_to_drop"] > 30]

                # Apply sorting
                if sort_deals_by == "Largest $ Cut First":
                    filtered_deals.sort(key=lambda x: x["drop_amount"], reverse=True)
                elif sort_deals_by == "Highest % Cut First":
                    filtered_deals.sort(key=lambda x: x["drop_pct"], reverse=True)
                elif sort_deals_by == "Fastest Cut First (Lowest Days)":
                    filtered_deals.sort(key=lambda x: x["days_to_drop"], reverse=False)
                else:
                    filtered_deals.sort(key=lambda x: x["days_since_drop"], reverse=False)

                st.markdown(f"**Showing {len(filtered_deals)} of {len(all_deals)} price-dropped properties:**")

                if not filtered_deals:
                    st.warning("No price drop properties match your current filter settings. Try relaxing the filters above.")
                else:
                    for d in filtered_deals:
                        with st.container():
                            card_c1, card_c2 = st.columns([1, 2.5])
                            with card_c1:
                                st.image(d["primary_photo"], width="stretch")
                                badges = [
                                    f"<span style='background-color:#2563eb;color:#ffffff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;'>{d['city']}</span>"
                                ]
                                if d["is_foreclosure"]:
                                    badges.append("<span style='background-color:#d97706;color:#ffffff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;'>⚠️ Foreclosure / REO</span>")
                                if d["price_per_sqft"] and d["price_per_sqft"] <= 220:
                                    badges.append(f"<span style='background-color:#059669;color:#ffffff;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;'>💎 ${d['price_per_sqft']:.0f}/sqft Bargain</span>")
                                st.html(f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;'>{''.join(badges)}</div>")

                            with card_c2:
                                st.markdown(f"### {md_escape(d['formatted_address'])}")
                                sqft_disp = f"{int(d['sqft']):,} SqFt" if d['sqft'] else "N/A"
                                ppsf_disp = f"\\${d['price_per_sqft']:.0f}/sqft" if d['price_per_sqft'] else "N/A"
                                st.caption(f"📍 **{d['city']}, GA {d['zip_code']}** ({d['county']} County) | 🛏️ {int(d['beds']) if d['beds'] else '-'} Beds | 🛁 {int(d['full_baths']) if d['full_baths'] else '-'} Baths | 📐 {sqft_disp} ({ppsf_disp})")

                                # The 2 Core Callouts: HOW MUCH vs WITHIN HOW LONG
                                box_c1, box_c2 = st.columns(2)
                                with box_c1:
                                    st.html(f"""
                                    <div style="background-color: rgba(239, 68, 68, 0.12); border: 1px solid #ef4444; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                                        <div style="font-size: 11px; font-weight: 700; color: #f87171; text-transform: uppercase; letter-spacing: 0.5px;">🔻 HOW MUCH WAS CUT</div>
                                        <div style="font-size: 22px; font-weight: 800; color: #ef4444; margin: 2px 0;">-${d['drop_amount']:,.0f} <span style="font-size: 15px;">(-{d['drop_pct']:.1f}%)</span></div>
                                        <div style="font-size: 12px; color: #94a3b8;">Original: <del>${d['initial_price']:,.0f}</del> ➔ Now: <strong style="color:#ffffff;">${d['current_price']:,.0f}</strong></div>
                                    </div>
                                    """)
                                with box_c2:
                                    st.html(f"""
                                    <div style="background-color: rgba(59, 130, 246, 0.12); border: 1px solid #3b82f6; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                                        <div style="font-size: 11px; font-weight: 700; color: #60a5fa; text-transform: uppercase; letter-spacing: 0.5px;">⏱️ WITHIN HOW LONG</div>
                                        <div style="font-size: 19px; font-weight: 800; color: #3b82f6; margin: 2px 0;">Cut after {d['days_to_drop']} days <span style="font-size: 13px; font-weight: 600; color: #cbd5e1;">(DOM: {d['days_on_market']})</span></div>
                                        <div style="font-size: 12px; color: #94a3b8;"><span style="color:{d['velocity_color']}; font-weight:700;">{d['velocity_tag']}</span> • Cut {d['days_since_drop']}d ago</div>
                                    </div>
                                    """)

                                # Price history timeline
                                if len(d["timeline"]) >= 2:
                                    trail = " &nbsp;➔&nbsp; ".join([f"<code>{t['date']}</code>: <strong>{t['price_str']}</strong>" for t in d["timeline"][-3:]])
                                    st.html(f"<div style='font-size:12px;color:#94a3b8;margin-bottom:8px;'>📜 <strong>Audit Trail:</strong> {trail}</div>")

                                if d.get("property_url") and str(d["property_url"]).strip() and str(d["property_url"]) != "None":
                                    st.link_button("View External Listing ↗", d["property_url"], type="secondary")

                            st.divider()

        # ----------------------------------------------------
        # SUB-TAB 2: Price Cut Comparison Table & Matrix
        # ----------------------------------------------------
        with subtab_table:
            st.markdown("#### 📋 Price Cut Comparison Matrix")
            st.caption("Compare seller urgency, cut sizes, and velocity to spot motivated sellers.")

            if not all_deals:
                st.info("No price drop records available for comparison.")
            else:
                table_rows = []
                for d in all_deals:
                    table_rows.append({
                        "Address": d["formatted_address"],
                        "City": d["city"],
                        "Current Price ($)": f"${d['current_price']:,.0f}",
                        "Original Price ($)": f"${d['initial_price']:,.0f}",
                        "Price Cut ($)": f"-${d['drop_amount']:,.0f}",
                        "Cut %": f"-{d['drop_pct']:.1f}%",
                        "Days to Cut": d["days_to_drop"],
                        "Total DOM": d["days_on_market"],
                        "Days Ago Cut": d["days_since_drop"],
                        "Seller Urgency": d["velocity_tag"],
                        "$/SqFt": f"${d['price_per_sqft']:.0f}" if d["price_per_sqft"] else "-"
                    })

                deal_df = pd.DataFrame(table_rows)
                st.dataframe(deal_df, width="stretch", hide_index=True)

                # Scatter Plot: Urgency Matrix
                st.markdown("#### ⚡ Seller Urgency Matrix (Cut % vs. Days on Market to Cut)")
                st.caption("Top-Left Quadrant represents **Prime Deal Targets**: High discount percentage executed quickly by motivated sellers.")

                plot_df = pd.DataFrame([{
                    "Address": d["formatted_address"],
                    "City": d["city"],
                    "Days on Market to Cut": d["days_to_drop"],
                    "Price Drop %": d["drop_pct"],
                    "Price Drop ($)": d["drop_amount"],
                    "Current Price": f"${d['current_price']:,.0f}",
                    "Urgency": d["velocity_tag"]
                } for d in all_deals])

                fig_matrix = px.scatter(
                    plot_df,
                    x="Days on Market to Cut",
                    y="Price Drop %",
                    size="Price Drop ($)",
                    color="City",
                    hover_name="Address",
                    hover_data=["Current Price", "Urgency"],
                    template="plotly_dark",
                    title="Seller Urgency: Drop % vs. Days on Market Before Cut"
                )
                fig_matrix.update_layout(
                    height=450,
                    margin=dict(l=20, r=20, t=50, b=20),
                    xaxis_title="Days on Market Before Price Reduction (How Long)",
                    yaxis_title="Price Cut Percentage (%) (How Much)"
                )
                st.plotly_chart(fig_matrix, width="stretch")

        # ----------------------------------------------------
        # SUB-TAB 3: Filtered Alert Logs
        # ----------------------------------------------------
        with subtab_feed:
            st.markdown("#### 🚨 Triggered Real-Time Alerts Feed")
            alert_filter = st.radio(
                "Filter Feed By Alert Category:",
                ["🔥 Price Drop Slashes Only", "💎 Deep Value (Sub-$220/sqft)", "All Recent Alerts"],
                horizontal=True,
                key="alert_feed_filter"
            )

            with get_session() as session:
                recent_alerts = get_recent_alerts(session, limit=50)

            if not recent_alerts:
                st.success("No active alert triggers pending.")
            else:
                displayed_count = 0
                for a in recent_alerts:
                    msg = a.message or ""
                    is_drop_alert = "Price cut" in msg or "price drop" in msg.lower() or "Price Cut" in msg
                    is_bargain_alert = "Sub-$" in msg or "sub-" in msg.lower() or "Bargain" in msg

                    if alert_filter == "🔥 Price Drop Slashes Only" and not is_drop_alert:
                        continue
                    if alert_filter == "💎 Deep Value (Sub-$220/sqft)" and not is_bargain_alert:
                        continue

                    displayed_count += 1
                    time_str = a.triggered_at.strftime("%b %d, %H:%M") if a.triggered_at else "Recent"
                    icon = "🔥" if is_drop_alert else "💎"
                    border_color = "#ef4444" if is_drop_alert else "#10b981"

                    st.html(f"""
                    <div style="background-color: rgba(30, 41, 59, 0.6); border-left: 4px solid {border_color};
                                border-radius: 6px; padding: 10px 14px; margin-bottom: 8px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="font-size: 13px; font-weight: 700; color: #ffffff;">{icon} {md_escape(msg)}</span>
                            <span style="font-size: 11px; color: #94a3b8; font-weight:600;">{time_str}</span>
                        </div>
                    </div>
                    """)

                if displayed_count == 0:
                    st.info(f"No alerts matching category '{alert_filter}'.")

        # ----------------------------------------------------
        # SUB-TAB 4: Alert Rules & Settings
        # ----------------------------------------------------
        with subtab_rules:
            st.markdown("#### ⚙️ Active Strategy Rules & Trigger Thresholds")
            st.caption("The engine continuously tests newly ingested listings against these active rules.")

            r_col1, r_col2 = st.columns([3, 2])

            with r_col1:
                with get_session() as session:
                    rules = get_alert_rules(session)
                    for r in rules:
                        status_badge = "<span style='background-color:#059669;color:#ffffff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;'>🟢 ACTIVE</span>" if r.is_active else "<span style='background-color:#6b7280;color:#ffffff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;'>🔴 INACTIVE</span>"
                        conditions = []
                        if r.min_price_drop_pct:
                            conditions.append(f"Price Drop &ge; <strong>{r.min_price_drop_pct}%</strong>")
                        if r.max_price_per_sqft:
                            conditions.append(f"Cost &le; <strong>${r.max_price_per_sqft:.0f}/sqft</strong>")
                        if r.cities:
                            conditions.append(f"Submarkets: <strong>{r.cities}</strong>")
                        if r.max_price:
                            conditions.append(f"Max Budget: <strong>${r.max_price:,.0f}</strong>")

                        cond_str = " • ".join(conditions) if conditions else "Global Rule (All Listings)"

                        st.html(f"""
                        <div style="background-color: rgba(30, 41, 59, 0.5); border: 1px solid #334155;
                                    border-radius: 8px; padding: 12px 16px; margin-bottom: 10px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                <strong style="font-size:14px; color:#ffffff;">{md_escape(r.name)}</strong>
                                {status_badge}
                            </div>
                            <div style="font-size:12px; color:#94a3b8;">Trigger Criteria: {cond_str}</div>
                        </div>
                        """)

            with r_col2:
                with st.expander("➕ Add Custom Alert Rule", expanded=True):
                    with st.form("custom_rule_form"):
                        st.markdown("**New Alert Rule Definition**")
                        new_rule_name = st.text_input("Rule Name", placeholder="e.g. Alpharetta Price Cut > 5%")
                        new_drop_pct = st.number_input("Min Price Drop %", min_value=0.0, max_value=50.0, value=5.0, step=0.5)
                        new_max_ppsf = st.number_input("Max $/SqFt Cap", min_value=100.0, max_value=600.0, value=220.0, step=10.0)
                        new_cities = st.multiselect("Target Submarkets", all_cities, default=["Duluth", "Suwanee"])
                        new_max_price = st.number_input("Max Budget ($)", min_value=100_000, max_value=3_000_000, value=750_000, step=25_000)

                        save_btn = st.form_submit_button("Save & Activate Rule", type="primary")
                        if save_btn and new_rule_name:
                            with get_session() as session:
                                new_r = AlertRule(
                                    name=new_rule_name,
                                    is_active=True,
                                    min_price_drop_pct=new_drop_pct,
                                    max_price_per_sqft=new_max_ppsf,
                                    cities=",".join(new_cities) if new_cities else None,
                                    max_price=new_max_price
                                )
                                session.add(new_r)
                                session.commit()
                            st.success(f"Created rule: {new_rule_name}")
                            st.rerun()

    # ----------------------------------------------------
    # TAB 6: Ingestion & Live Scraper
    # ----------------------------------------------------

    with tab_pipeline:
        st.subheader("⚡ Multi-Source Data Ingestion & Live Scraper")
        st.caption("Ingest active MLS listings, Foreclosed/REO properties, Redfin Open Data feeds, and Georgia courthouse auction notices.")

        col_ingest_1, col_ingest_2 = st.columns(2)

        with col_ingest_1:
            st.markdown("#### Select Data Sources & Target Submarkets")
            c1, c2 = st.columns(2)
            with c1:
                src_mls = st.checkbox("🏡 MLS / Realtor Feeds", value=True, help="Scrapes live active MLS listings via HomeHarvest")
                src_fc = st.checkbox("⚠️ Foreclosed & Bank-Owned (REO)", value=True, help="Queries active pre-foreclosure, auction, and REO bank-owned listings")
            with c2:
                src_rf = st.checkbox("📊 Redfin Open Data GIS (Option 1)", value=True, help="Fetches live public Redfin GIS CSV MLS feed for Metro Atlanta")
                src_auc = st.checkbox("🏛️ Auction.com & GA Legal Notices (Option 3)", value=True, help="Scrapes Georgia legal foreclosure notices & courthouse auction properties from official trustee feeds")

            ingest_submarkets = st.multiselect("Target Submarkets", all_cities, default=["Duluth", "Suwanee", "Norcross", "Peachtree Corners"])

            if st.button("🚀 Execute Ingestion Pipeline", type="primary", width="stretch"):
                selected_sources = []
                if src_mls:
                    selected_sources.append("realtor")
                if src_fc:
                    selected_sources.append("foreclosure")
                if src_rf:
                    selected_sources.append("redfin")
                if src_auc:
                    selected_sources.append("auction")

                if not selected_sources:
                    st.error("Please select at least one data source.")
                else:
                    with st.spinner(f"Executing pipeline across {len(selected_sources)} sources ({', '.join(selected_sources)})..."):
                        res = run_pipeline(sources=selected_sources, submarkets=ingest_submarkets)
                        st.success(f"Ingestion Finished! Processed: {res['total_processed']} | Ingested: {res['inserted']} | Updated: {res['updated']} | Alerts Triggered: {res['alerts_triggered']}")
                        st.rerun()

            st.markdown("---")
            st.markdown("#### ⚖️ Historical Distress Datasets Sync")
            st.caption("Manually re-fetch and refresh Fulton County Socrata Eviction filings & CFPB Mortgage Delinquency datasets.")
            if st.button("🔄 Refresh Eviction & CFPB Macro Time-Series", width="stretch"):
                with st.spinner("Fetching latest eviction filings & CFPB mortgage performance data..."):
                    fetch_historical_eviction_filings()
                    fetch_historical_mortgage_delinquency()
                    st.success("Historical distress datasets refreshed and cached successfully!")
                    st.rerun()

        with col_ingest_2:
            st.markdown("#### Recent Ingestion Snapshots")
            with get_session() as session:
                snapshots = session.query(IngestionSnapshot).order_by(IngestionSnapshot.timestamp.desc()).limit(10).all()
                if snapshots:
                    snap_data = [s.to_dict() for s in snapshots]
                    st.dataframe(pd.DataFrame(snap_data), width="stretch", hide_index=True)
                else:
                    st.info("No snapshots recorded yet.")


if __name__ == "__main__":
    render_dashboard()

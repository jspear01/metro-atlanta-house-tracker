"""
Interactive Real Estate Analytics Dashboard for Metro Atlanta (Gwinnett & North Fulton).
Streamlined, low-noise UI with progressive disclosure.
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
from src.ingestion.pipeline import run_pipeline, run_rental_pipeline, run_official_apartment_pipeline
from src.ingestion.official_apartments import detect_apartment_brand
from src.ingestion.distress_trends import (
    fetch_historical_eviction_filings,
    fetch_historical_mortgage_delinquency,
    fetch_metro_eviction_filings,
    DATA_SOURCES,
    FETCH_STATUS
)


def md_escape(text) -> str:
    """Escape '$' so Streamlit markdown doesn't render text between dollar signs as LaTeX."""
    return str(text).replace("$", "\\$")


LISTING_SITES = {
    "realtor.com": ("Realtor.com", "#60a5fa"),
    "redfin.com": ("Redfin", "#fb7185"),
    "zillow.com": ("Zillow", "#38bdf8"),
    "auction.com": ("Auction.com", "#a78bfa"),
    "rlselaw.com": ("RLSE Law", "#c4b5fd"),
}


def get_listing_site(url, feed_name=None) -> tuple:
    """Return (site display name, badge color) based on the listing URL's domain."""
    url_str = str(url or "").lower()
    for domain, (name, color) in LISTING_SITES.items():
        if domain in url_str:
            return name, color
    return (feed_name or "MLS"), "#94a3b8"


def is_synthetic_listing(prop: dict) -> bool:
    """Synthetic seed listings use the 'FMLS-' prefix and have no real MLS detail page."""
    return str(prop.get("mls_id") or "").startswith("FMLS-")


def apply_custom_css():
    st.markdown("""
    <style>
    /* Clean page spacing */
    .block-container {
        padding-top: 1.75rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 1400px;
    }
    /* Calm Metric Cards */
    div[data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.55);
        border: 1px solid rgba(148, 163, 184, 0.16);
        padding: 14px 18px;
        border-radius: 10px;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #94a3b8 !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.55rem !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
    }
    /* Subtle Pills */
    .pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        margin-right: 6px;
        line-height: 1.4;
    }
    .pill-city {
        background: rgba(59, 130, 246, 0.15);
        color: #93c5fd;
        border: 1px solid rgba(59, 130, 246, 0.3);
    }
    .pill-drop {
        background: rgba(239, 68, 68, 0.15);
        color: #fca5a5;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .pill-bargain {
        background: rgba(16, 185, 129, 0.15);
        color: #6ee7b7;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .pill-warn {
        background: rgba(245, 158, 11, 0.15);
        color: #fcd34d;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    </style>
    """, unsafe_allow_html=True)


def _render_property_card(prop: dict, deal_info: dict = None):
    """Render a clean, low-noise property card inside a bordered container."""
    with st.container(border=True):
        c_img, c_body = st.columns([1.1, 2.4])
        with c_img:
            photo = prop.get("primary_photo") or "https://images.unsplash.com/photo-1568605117036-5fe5e7bab0b7?w=800&auto=format&fit=crop&q=60"
            st.image(photo, width="stretch")

        with c_body:
            # Up to 3 subtle pills
            pills = [f"<span class='pill pill-city'>{prop['city']} · {prop['zip_code']}</span>"]
            if prop.get("is_price_drop"):
                drop_pct = prop.get("price_drop_pct") or (deal_info.get("drop_pct") if deal_info else 0.0) or 0.0
                pills.append(f"<span class='pill pill-drop'>🔻 -{drop_pct:.1f}%</span>")
            if prop.get("price_per_sqft") and prop["price_per_sqft"] <= 220:
                pills.append(f"<span class='pill pill-bargain'>💎 ${prop['price_per_sqft']:.0f}/sf</span>")
            elif prop.get("is_foreclosure"):
                pills.append("<span class='pill pill-warn'>⚠️ Foreclosure</span>")

            st.html(f"<div style='margin-bottom:4px;'>{''.join(pills[:3])}</div>")

            # Price & Address
            price_val = prop.get("current_list_price") or prop.get("current_price") or 0
            st.markdown(f"#### \\${price_val:,.0f}")
            st.markdown(f"**{md_escape(prop.get('formatted_address', ''))}**")

            # Compact 1-line specs
            beds = int(prop["beds"]) if prop.get("beds") else "-"
            baths = int(prop["full_baths"]) if prop.get("full_baths") else "-"
            sqft = f"{int(prop['sqft']):,}" if prop.get("sqft") else "-"
            ppsf = f"\\${prop['price_per_sqft']:.0f}/sf" if prop.get("price_per_sqft") else "n/a"
            dom = prop.get("days_on_market", 0)
            st.caption(f"{beds} bd · {baths} ba · {sqft} sqft ({ppsf}) · {dom}d on market")

            # Optional concise price-cut summary line (when price dropped)
            if deal_info:
                st.html(
                    f"<div style='background:rgba(239,68,68,0.08);border-left:3px solid #ef4444;padding:6px 10px;"
                    f"border-radius:4px;font-size:12px;color:#e2e8f0;margin:4px 0 8px 0;'>"
                    f"Cut <b>-${deal_info['drop_amount']:,.0f} (-{deal_info['drop_pct']:.1f}%)</b> from ${deal_info['initial_price']:,.0f} "
                    f"· Cut after <b>{deal_info['days_to_drop']}d</b> ({deal_info['velocity_tag']})"
                    f"</div>"
                )
            elif prop.get("is_price_drop") and prop.get("price_drop_amount"):
                st.caption(f"🔻 Reduced by \\${prop['price_drop_amount']:,.0f} (-{prop.get('price_drop_pct', 0):.1f}%)")

            # Footer: Source & External Link
            site_name, _ = get_listing_site(prop.get("property_url"), prop.get("listing_source"))
            listing_url = prop.get("property_url")
            if listing_url and str(listing_url).strip() and str(listing_url) != "None":
                st.link_button(f"Open on {site_name} ↗", listing_url, width="stretch")
            else:
                st.link_button(
                    f"Search {prop['zip_code']} on Realtor ↗",
                    f"https://www.realtor.com/realestateandhomes-search/{prop['zip_code']}",
                    width="stretch"
                )


def render_dashboard():
    st.set_page_config(
        page_title="Metro Atlanta Real Estate Tracker",
        page_icon="🏡",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    apply_custom_css()
    init_db()

    # ----------------------------------------------------
    # Compact Header
    # ----------------------------------------------------
    hdr_left, hdr_right = st.columns([4, 1])
    with hdr_left:
        st.subheader("🏡 Metro Atlanta Real Estate Intelligence")
        st.caption("Gwinnett, North Fulton & Forsyth submarkets · Listings, price drops, rentals, and macro distress")
    with hdr_right:
        if st.button("🔄 Refresh View", width="stretch"):
            st.rerun()

    # ----------------------------------------------------
    # Streamlined Sidebar Filters
    # ----------------------------------------------------
    st.sidebar.markdown("### 🔍 Filters")

    all_cities = list(TARGET_SUBMARKETS.keys())
    default_selected = list(all_cities)
    selected_cities = st.sidebar.multiselect(
        "Submarkets",
        options=all_cities,
        default=default_selected
    )

    price_range = st.sidebar.slider(
        "Price Range ($)",
        min_value=200_000,
        max_value=1_600_000,
        value=(250_000, 1_300_000),
        step=25_000,
        format="$%d"
    )

    property_types = ["All", "Single Family", "Townhouse", "Condo"]
    selected_prop_type = st.sidebar.selectbox("Property Type", property_types, index=0)

    st.sidebar.markdown("##### Quick Focus")
    price_drops_only = st.sidebar.checkbox("🔥 Price Drops Only", value=False)
    bargains_only = st.sidebar.checkbox("💎 Value Deals (≤ $220/sqft)", value=False)
    foreclosures_only = st.sidebar.checkbox("⚠️ Foreclosures Only", value=False)

    # Progressive disclosure for secondary filters
    available_zips = sorted(list({z for c in selected_cities for z in TARGET_SUBMARKETS[c]["zip_codes"]}))
    with st.sidebar.expander("⚙️ Advanced (ZIP & Source)", expanded=False):
        selected_zips = st.multiselect("ZIP Codes", options=available_zips, default=[])
        source_filter = st.selectbox(
            "Listing Source",
            ["All", "MLS/Realtor", "Foreclosure/REO", "Redfin Open Data", "Auction / Legal Notice"],
            index=0
        )

    # ----------------------------------------------------
    # Query & Filter Data
    # ----------------------------------------------------
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

    kpis = compute_executive_kpis(df)

    # ----------------------------------------------------
    # 4 Spacious Executive KPI Cards (Replaces 7 cramped boxes)
    # ----------------------------------------------------
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Active Inventory",
        f"{kpis['total_inventory']:,} homes",
        f"Median {kpis['median_dom']}d on market",
        delta_color="off"
    )
    k2.metric(
        "Median List Price",
        f"${kpis['median_price']:,.0f}" if kpis["median_price"] else "$0",
        f"${kpis['median_sqft_price']:.0f} / sqft" if kpis["median_sqft_price"] else "$0 / sqft",
        delta_color="off"
    )
    k3.metric(
        "Price Reductions",
        f"{kpis['price_drop_count']} listings",
        f"{kpis['price_drop_pct_inventory']}% of inventory (-{kpis['avg_price_drop_rate']}% avg)",
        delta_color="inverse"
    )
    k4.metric(
        "Bargains & Distress",
        f"{kpis['sub_220_count']} ≤ $220/sf",
        f"{kpis.get('foreclosure_count', 0)} Foreclosures / REO",
        delta_color="off"
    )

    # ----------------------------------------------------
    # 5 Focused Top-Level Tabs (Down from 7 + 8 nested tabs)
    # ----------------------------------------------------
    tab_listings, tab_analytics, tab_rentals, tab_distress, tab_ops = st.tabs([
        "🏡 Listings & Price Drops",
        "📊 Market Analytics",
        "🏢 Rentals",
        "⚖️ Macro Distress",
        "⚙️ Alerts & Data Sync"
    ])

    # ====================================================
    # TAB 1: Listings & Price Drops (Unified & Scannable)
    # ====================================================
    with tab_listings:
        ctrl_1, ctrl_2, ctrl_3 = st.columns([1.8, 1.4, 0.8])
        with ctrl_1:
            view_mode = st.radio(
                "View Mode",
                ["All Matching Listings", "🔥 Price Cuts (How Much & How Long)", "📋 Compact Table"],
                horizontal=True,
                label_visibility="collapsed"
            )
        with ctrl_2:
            sort_option = st.selectbox(
                "Sort By",
                [
                    "Lowest $/SqFt (Best Value)",
                    "Highest Price Drop %",
                    "Newest / Lowest DOM",
                    "Price: Low to High",
                    "Price: High to Low"
                ],
                label_visibility="collapsed"
            )
        with ctrl_3:
            page_size = st.selectbox(
                "Per Page",
                [12, 24, 48],
                index=0,
                label_visibility="collapsed"
            )

        if view_mode == "🔥 Price Cuts (How Much & How Long)":
            with get_session() as session:
                drop_summary = compute_price_drop_summary(
                    session,
                    cities=selected_cities if selected_cities else None
                )
            deals = drop_summary["deals"]
            dk = drop_summary["kpis"]

            if not deals:
                st.info("No price-dropped properties found for the selected submarkets.")
            else:
                st.caption(
                    f"**{dk['total_deals']} active price cuts** · Average cut **-\\${dk['avg_drop_amount']:,.0f} (-{dk['avg_drop_pct']:.1f}%)** "
                    f"· Average seller wait before cut: **{int(dk['avg_days_to_drop'])} days** (fastest: {dk['fastest_cut']}d)"
                )
                for i in range(0, len(deals), 2):
                    row_cols = st.columns(2)
                    for j, col in enumerate(row_cols):
                        if i + j < len(deals):
                            d = deals[i + j]
                            with col:
                                _render_property_card(d, deal_info=d)

        elif df.empty:
            st.info("No properties match your current sidebar filters. Try widening the price range or submarkets.")
        else:
            if sort_option == "Lowest $/SqFt (Best Value)":
                sorted_df = df.sort_values(by="price_per_sqft", ascending=True, na_position="last")
            elif sort_option == "Highest Price Drop %":
                sorted_df = df.sort_values(by="price_drop_pct", ascending=False)
            elif sort_option == "Newest / Lowest DOM":
                sorted_df = df.sort_values(by="days_on_market", ascending=True)
            elif sort_option == "Price: Low to High":
                sorted_df = df.sort_values(by="current_list_price", ascending=True)
            else:
                sorted_df = df.sort_values(by="current_list_price", ascending=False)

            if view_mode == "📋 Compact Table":
                display_cols = [
                    "formatted_address", "city", "zip_code", "current_list_price",
                    "price_per_sqft", "beds", "full_baths", "sqft",
                    "days_on_market", "is_price_drop", "price_drop_pct", "listing_source"
                ]
                avail_cols = [c for c in display_cols if c in sorted_df.columns]
                st.dataframe(
                    sorted_df[avail_cols].rename(columns={
                        "formatted_address": "Address",
                        "city": "City",
                        "zip_code": "ZIP",
                        "current_list_price": "Price ($)",
                        "price_per_sqft": "$/SqFt",
                        "beds": "Beds",
                        "full_baths": "Baths",
                        "sqft": "SqFt",
                        "days_on_market": "DOM",
                        "is_price_drop": "Price Cut",
                        "price_drop_pct": "Cut %",
                        "listing_source": "Source"
                    }),
                    width="stretch",
                    hide_index=True,
                    height=520
                )
            else:
                total_listings = len(sorted_df)
                total_pages = max(1, -(-total_listings // page_size))
                page_num = min(max(1, int(st.session_state.get("listings_page_num", 1))), total_pages)
                start_idx = (page_num - 1) * page_size
                end_idx = min(start_idx + page_size, total_listings)

                records = sorted_df.iloc[start_idx:end_idx].to_dict(orient="records")
                for i in range(0, len(records), 2):
                    row_cols = st.columns(2)
                    for j, col in enumerate(row_cols):
                        if i + j < len(records):
                            with col:
                                _render_property_card(records[i + j])

                # Compact Pagination Footer
                if total_pages > 1:
                    p_left, p_mid, p_right = st.columns([1, 2, 1])
                    with p_left:
                        if st.button("‹ Previous", disabled=page_num <= 1, width="stretch"):
                            st.session_state["listings_page_num"] = page_num - 1
                            st.rerun()
                    with p_mid:
                        st.markdown(
                            f"<div style='text-align:center;padding-top:8px;color:#94a3b8;font-size:13px;'>"
                            f"Page <b>{page_num}</b> of <b>{total_pages}</b> · Showing {start_idx + 1}–{end_idx} of {total_listings}"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                    with p_right:
                        if st.button("Next ›", disabled=page_num >= total_pages, width="stretch"):
                            st.session_state["listings_page_num"] = page_num + 1
                            st.rerun()

    # ====================================================
    # TAB 2: Market Analytics (Charts + Collapsible Tables)
    # ====================================================
    with tab_analytics:
        if df.empty:
            st.info("No listings available for analytics.")
        else:
            ch_col1, ch_col2 = st.columns(2)

            with ch_col1:
                st.markdown("##### Submarket Median Price & $/SqFt")
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
                        marker=dict(color="#10b981", size=9),
                        yaxis="y2"
                    ))
                    fig_sub.update_layout(
                        yaxis=dict(title="Median Price ($)", tickformat="$,.0f"),
                        yaxis2=dict(title="$/SqFt ($)", overlaying="y", side="right", tickformat="$.0f"),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        margin=dict(l=15, r=15, t=30, b=15),
                        template="plotly_dark",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(15,23,42,0.4)",
                        height=380
                    )
                    st.plotly_chart(fig_sub, width="stretch")

            with ch_col2:
                st.markdown("##### Valuation Scatter: List Price vs. SqFt")
                fig_scatter = px.scatter(
                    df,
                    x="sqft",
                    y="current_list_price",
                    color="city",
                    symbol="is_price_drop",
                    hover_name="formatted_address",
                    hover_data={
                        "current_list_price": ":$,.0f",
                        "price_per_sqft": ":$.1f",
                        "days_on_market": True,
                        "beds": True,
                        "full_baths": True
                    },
                    labels={
                        "sqft": "Living Area (SqFt)",
                        "current_list_price": "List Price ($)",
                        "city": "City",
                        "is_price_drop": "Price Cut"
                    },
                    template="plotly_dark",
                    height=380
                )
                max_sqft = df["sqft"].max() or 5000
                x_line = np.linspace(800, max_sqft, 40)
                fig_scatter.add_trace(go.Scatter(
                    x=x_line,
                    y=x_line * 220.0,
                    mode="lines",
                    name="$220/sqft Line",
                    line=dict(color="#10b981", dash="dash", width=1.5)
                ))
                fig_scatter.update_layout(
                    margin=dict(l=15, r=15, t=30, b=15),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,23,42,0.4)"
                )
                st.plotly_chart(fig_scatter, width="stretch")

            # Progressive disclosure for detailed tables & cohorts
            with st.expander("📍 ZIP Code Breakdown & DOM Distribution", expanded=True):
                z_col1, z_col2 = st.columns([1.3, 1])
                with z_col1:
                    zip_df = compute_zip_code_breakdown(df)
                    if not zip_df.empty:
                        st.dataframe(
                            zip_df.rename(columns={
                                "city": "City",
                                "zip_code": "ZIP",
                                "inventory_count": "Listings",
                                "median_price": "Median ($)",
                                "median_sqft_price": "$/SqFt",
                                "median_dom": "DOM",
                                "price_drop_count": "Cuts",
                                "price_drop_rate": "Cut %"
                            }),
                            width="stretch",
                            hide_index=True
                        )
                with z_col2:
                    fig_dom = px.histogram(
                        df,
                        x="days_on_market",
                        nbins=18,
                        color="city",
                        labels={"days_on_market": "Days on Market (DOM)"},
                        template="plotly_dark",
                        height=300
                    )
                    fig_dom.update_layout(
                        margin=dict(l=10, r=10, t=20, b=10),
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(15,23,42,0.4)",
                        showlegend=False
                    )
                    st.plotly_chart(fig_dom, width="stretch")

            with st.expander("⚡ DuckDB Quartiles (p25 / Median / p75) & DOM Cohorts", expanded=False):
                adv = compute_duckdb_advanced_analytics()
                d_col1, d_col2 = st.columns(2)
                with d_col1:
                    st.caption("Submarket Price Quartiles")
                    if adv.get("city_quantiles"):
                        st.dataframe(pd.DataFrame(adv["city_quantiles"]), width="stretch", hide_index=True)
                with d_col2:
                    st.caption("Days on Market Cohort Pricing")
                    if adv.get("dom_cohorts"):
                        st.dataframe(pd.DataFrame(adv["dom_cohorts"]), width="stretch", hide_index=True)

    # ====================================================
    # TAB 3: Rentals (Official Apartment Websites Only)
    # ====================================================
    with tab_rentals:
        r_f0, r_f1, r_f2, r_f3, r_f4 = st.columns([1.15, 1.0, 1.2, 1.3, 1.15])
        with r_f0:
            rent_brand_filter = st.selectbox(
                "Apartment Brand",
                ["All Brands", "Camden", "Cortland", "AMLI", "Equity Residential", "MAA"],
                index=0
            )
        with r_f1:
            rent_beds_filter = st.selectbox(
                "Minimum Beds",
                ["All Bedrooms", "1+ Beds", "2+ Beds", "3+ Beds", "4+ Beds"],
                index=0
            )
        with r_f2:
            rent_max_slider = st.slider(
                "Max Monthly Rent ($)",
                min_value=800,
                max_value=6000,
                value=4500,
                step=100,
                format="$%d/mo"
            )
        with r_f3:
            rent_sort_option = st.selectbox(
                "Sort Official Floorplans",
                ["Featured Mix (All Brands)", "Rent: Low to High", "Rent: High to Low", "Lowest $/SqFt"]
            )
        with r_f4:
            st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
            if st.button("🏢 Sync Official Websites", type="primary", width="stretch"):
                with st.spinner("Scraping live floorplan pricing from official apartment websites..."):
                    res = run_official_apartment_pipeline(
                        submarkets=selected_cities if selected_cities else all_cities
                    )
                    st.success(f"Official websites synced: {res.get('inserted', 0)} added, {res.get('updated', 0)} updated.")
                    st.rerun()

        with st.expander("➕ Track Another Apartment's Official Website URL", expanded=False):
            u_c1, u_c2, u_c3, u_c4, u_c5 = st.columns([1.4, 2.2, 1.1, 0.9, 1.0])
            with u_c1:
                custom_apt_name = st.text_input("Apartment Name", placeholder="e.g. Cortland Brookhaven")
            with u_c2:
                custom_apt_url = st.text_input("Official Website or SightMap URL", placeholder="https://...")
            with u_c3:
                custom_apt_city = st.selectbox("Submarket", all_cities)
            with u_c4:
                custom_apt_zip = st.selectbox("ZIP", TARGET_SUBMARKETS[custom_apt_city]["zip_codes"], index=0)
            with u_c5:
                st.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
                if st.button("Scrape URL", width="stretch") and custom_apt_url:
                    with st.spinner("Scraping official floorplans..."):
                        res = run_official_apartment_pipeline(
                            custom_url=custom_apt_url.strip(),
                            custom_name=custom_apt_name.strip() or None,
                            custom_city=custom_apt_city,
                            custom_zip=custom_apt_zip
                        )
                        if res.get("total_processed", 0) > 0:
                            st.success(f"Scraped {res['total_processed']} official floorplan(s)!")
                            st.rerun()
                        else:
                            st.warning("Could not extract floorplan prices from that URL. Try pasting its floorplans or SightMap URL.")

        min_beds_map = {"1+ Beds": 1, "2+ Beds": 2, "3+ Beds": 3, "4+ Beds": 4}
        raw_rentals_df = get_rentals_dataframe(
            cities=selected_cities if selected_cities else None,
            zip_codes=selected_zips if selected_zips else None,
            min_beds=min_beds_map.get(rent_beds_filter),
            max_rent=rent_max_slider
        )

        if not raw_rentals_df.empty:
            raw_rentals_df = raw_rentals_df.copy()
            raw_rentals_df["brand"] = raw_rentals_df.apply(
                lambda r: detect_apartment_brand(r.get("property_url", ""), r.get("formatted_address", "")),
                axis=1
            )
            if rent_brand_filter != "All Brands":
                raw_rentals_df = raw_rentals_df[raw_rentals_df["brand"] == rent_brand_filter]

        if raw_rentals_df.empty:
            st.info("No official apartment floorplans match current filters. Click '🏢 Sync Official Websites' or widen your filter range.")
        else:
            total_rentals = len(raw_rentals_df)
            num_brands = raw_rentals_df["brand"].nunique()
            num_communities = raw_rentals_df["property_url"].nunique()
            median_rent = raw_rentals_df["monthly_rent"].median()
            sqft_mask = raw_rentals_df["rent_per_sqft"].notna() & (raw_rentals_df["rent_per_sqft"] > 0)
            median_rent_sqft = raw_rentals_df.loc[sqft_mask, "rent_per_sqft"].median() if sqft_mask.any() else 0.0

            rk1, rk2, rk3 = st.columns(3)
            rk1.metric(
                "Official Floorplans",
                f"{total_rentals:,} plans",
                f"{num_communities} communities · {num_brands} brands",
                delta_color="off"
            )
            rk2.metric("Median Monthly Rent", f"${median_rent:,.0f} / mo" if median_rent > 0 else "N/A")
            rk3.metric("Median Rent / SqFt", f"${median_rent_sqft:.2f} / sf" if median_rent_sqft > 0 else "N/A")

            with st.expander("📊 Rental Market Charts (By Submarket & Brand)", expanded=False):
                rc1, rc2 = st.columns(2)
                with rc1:
                    city_rent_stats = (
                        raw_rentals_df.groupby("city")
                        .agg(median_rent=("monthly_rent", "median"), count=("id", "count"))
                        .reset_index()
                        .sort_values(by="median_rent", ascending=False)
                    )
                    fig_rent_city = px.bar(
                        city_rent_stats,
                        x="city",
                        y="median_rent",
                        text="median_rent",
                        labels={"city": "Submarket", "median_rent": "Median Rent ($/mo)"},
                        template="plotly_dark",
                        color_discrete_sequence=["#3b82f6"]
                    )
                    fig_rent_city.update_traces(texttemplate="$%{y:,.0f}", textposition="outside")
                    fig_rent_city.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_rent_city, width="stretch")

                with rc2:
                    brand_rent_stats = (
                        raw_rentals_df.groupby("brand")
                        .agg(median_rent=("monthly_rent", "median"), count=("id", "count"))
                        .reset_index()
                        .sort_values(by="count", ascending=False)
                    )
                    fig_brand = px.bar(
                        brand_rent_stats,
                        x="brand",
                        y="count",
                        text="median_rent",
                        labels={"brand": "Management Brand", "count": "Official Floorplans"},
                        template="plotly_dark",
                        color_discrete_sequence=["#10b981"]
                    )
                    fig_brand.update_traces(texttemplate="$%{text:,.0f}/mo med", textposition="outside")
                    fig_brand.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=20), paper_bgcolor="rgba(0,0,0,0)")
                    st.plotly_chart(fig_brand, width="stretch")

            sorted_rentals = raw_rentals_df.copy()
            if rent_sort_option == "Featured Mix (All Brands)":
                sorted_rentals = sorted_rentals.sort_values(by="monthly_rent", ascending=True)
                sorted_rentals["_brand_rank"] = sorted_rentals.groupby("brand").cumcount()
                sorted_rentals = sorted_rentals.sort_values(by=["_brand_rank", "monthly_rent"], ascending=[True, True])
            elif rent_sort_option == "Rent: Low to High":
                sorted_rentals = sorted_rentals.sort_values(by="monthly_rent", ascending=True)
            elif rent_sort_option == "Rent: High to Low":
                sorted_rentals = sorted_rentals.sort_values(by="monthly_rent", ascending=False)
            elif rent_sort_option == "Lowest $/SqFt":
                sorted_rentals = sorted_rentals.sort_values(by="rent_per_sqft", ascending=True, na_position="last")
            else:
                sorted_rentals = sorted_rentals.sort_values(by="days_on_market", ascending=True)

            r_page_size = 20
            r_total = len(sorted_rentals)
            r_total_pages = max(1, -(-r_total // r_page_size))
            r_page = min(max(1, int(st.session_state.get("rentals_page_num", 1))), r_total_pages)
            r_start = (r_page - 1) * r_page_size
            r_end = min(r_start + r_page_size, r_total)

            rental_records = sorted_rentals.iloc[r_start:r_end].to_dict(orient="records")
            for i in range(0, len(rental_records), 2):
                r_cols = st.columns(2)
                for j, col in enumerate(r_cols):
                    if i + j < len(rental_records):
                        rent = rental_records[i + j]
                        with col:
                            with st.container(border=True):
                                rc_img, rc_body = st.columns([1.1, 2.4])
                                with rc_img:
                                    r_photo = rent.get("primary_photo") or "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800&auto=format&fit=crop&q=60"
                                    st.image(r_photo, width="stretch")
                                with rc_body:
                                    brand_label = rent.get("brand") or detect_apartment_brand(rent.get("property_url", ""))
                                    r_pills = [
                                        f"<span class='pill pill-city'>{rent['city']} · {rent['zip_code']}</span>",
                                        f"<span class='pill pill-bargain'>🏢 {brand_label} · Official</span>"
                                    ]
                                    if rent.get("rent_per_sqft") and rent["rent_per_sqft"] > 0:
                                        r_pills.append(f"<span class='pill pill-warn'>${rent['rent_per_sqft']:.2f}/sf</span>")
                                    st.html(f"<div style='margin-bottom:4px;'>{''.join(r_pills[:3])}</div>")

                                    m_rent = rent.get("monthly_rent")
                                    r_min = rent.get("rent_min")
                                    r_max = rent.get("rent_max")
                                    if r_min and r_max and r_min != r_max:
                                        st.markdown(f"#### \\${r_min:,.0f} – \\${r_max:,.0f} / mo")
                                    elif m_rent:
                                        st.markdown(f"#### \\${m_rent:,.0f} / mo")
                                    else:
                                        st.markdown("#### Contact for Rent")
                                    st.markdown(f"**{md_escape(rent.get('formatted_address', 'Address not disclosed'))}**")

                                    r_beds = int(rent["beds"]) if pd.notna(rent.get("beds")) else "-"
                                    r_baths = int(rent["full_baths"]) if pd.notna(rent.get("full_baths")) else "-"
                                    r_sqft = f"{int(rent['sqft']):,}" if pd.notna(rent.get("sqft")) and rent["sqft"] > 0 else "-"
                                    unit_note = f" · {rent['unit']}" if rent.get("unit") else ""
                                    st.caption(f"{r_beds} bd · {r_baths} ba · {r_sqft} sqft{unit_note}")

                                    r_url = rent.get("property_url")
                                    if r_url and str(r_url).strip() and str(r_url) != "None":
                                        st.link_button("Open Official Website ↗", r_url, width="stretch")

            if r_total_pages > 1:
                rp_left, rp_mid, rp_right = st.columns([1, 2, 1])
                with rp_left:
                    if st.button("‹ Previous", key="rent_prev", disabled=r_page <= 1, width="stretch"):
                        st.session_state["rentals_page_num"] = r_page - 1
                        st.rerun()
                with rp_mid:
                    st.markdown(
                        f"<div style='text-align:center;padding-top:8px;color:#94a3b8;font-size:13px;'>"
                        f"Page <b>{r_page}</b> of <b>{r_total_pages}</b> · Showing {r_start + 1}–{r_end} of {r_total} official floorplans"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                with rp_right:
                    if st.button("Next ›", key="rent_next", disabled=r_page >= r_total_pages, width="stretch"):
                        st.session_state["rentals_page_num"] = r_page + 1
                        st.rerun()

    # ====================================================
    # TAB 4: Macro Distress (Evictions & Delinquency)
    # ====================================================
    with tab_distress:
        df_ev = fetch_historical_eviction_filings()
        df_mort = fetch_historical_mortgage_delinquency()
        df_ev_metro = fetch_metro_eviction_filings()
        ev_metrics = compute_eviction_metrics(df_ev)
        mort_metrics = compute_mortgage_delinquency_metrics(df_mort)

        # 4 Clean Macro KPIs
        dm1, dm2, dm3, dm4 = st.columns(4)
        dm1.metric(
            "Fulton Evictions (Latest Mo)",
            f"{ev_metrics.get('latest_month_filings', 0):,}",
            f"{ev_metrics.get('month_over_month_diff', 0):+} vs prior mo",
            delta_color="inverse"
        )
        dm2.metric(
            "Fulton Evictions (12-Mo Total)",
            f"{ev_metrics.get('recent_12m_filings', 0):,}",
            f"Source: Socrata ({FETCH_STATUS.get('evictions', 'cache')})",
            delta_color="off"
        )
        gw_delinq = mort_metrics.get("Gwinnett County", {})
        dm3.metric(
            "Gwinnett 90+ Days Late",
            f"{gw_delinq.get('current_90_plus_late_pct', 0.0):.1f}%",
            f"+{gw_delinq.get('pct_increase_from_trough', 0.0):.0f}% vs 2021 trough",
            delta_color="inverse"
        )
        fu_delinq = mort_metrics.get("Fulton County", {})
        dm4.metric(
            "Fulton 90+ Days Late",
            f"{fu_delinq.get('current_90_plus_late_pct', 0.0):.1f}%",
            f"+{fu_delinq.get('pct_increase_from_trough', 0.0):.0f}% vs 2021 trough",
            delta_color="inverse"
        )

        # Concise 2-Column Executive Takeaway (Replaces wall of HTML text)
        sum_c1, sum_c2 = st.columns(2)
        with sum_c1:
            with st.container(border=True):
                st.markdown("##### 🔴 Eviction Filings: High Plateau (~3,100–3,500/mo)")
                st.caption(
                    f"Fulton County filings remain ~580% above 2016 baselines (~500/mo), driven by institutional serial filings. "
                    f"*Counts court filings, not completed evictions.* · [Fulton Socrata Dataset ↗]({DATA_SOURCES['evictions']['page_url']})"
                )
        with sum_c2:
            with st.container(border=True):
                st.markdown("##### 🟡 Serious Mortgage Delinquency: Climbing From 2021 Trough")
                st.caption(
                    f"90+ day delinquency doubled in Gwinnett (0.6% → 1.2%) and tripled in Fulton (0.4% → 1.4%), though still ~75% below 2008 peaks. "
                    f"· [CFPB Mortgage Trends ↗]({DATA_SOURCES['mortgage_delinquency']['page_url']})"
                )

        # Single Clean Chart Selector
        distress_view = st.radio(
            "Select Indicator View",
            [
                "📈 Monthly Eviction Filings (2016–2026)",
                "🗺️ Evictions by County (Metro, 2020–2026)",
                "🏛️ Mortgage 90+ Day Delinquency by County (2008–2025)",
                "📊 Annual Multi-Year Comparison"
            ],
            horizontal=True,
            label_visibility="collapsed"
        )

        if distress_view == "🗺️ Evictions by County (Metro, 2020–2026)":
            if df_ev_metro.empty:
                st.info("Metro county eviction data is unavailable right now. Try '🔄 Refresh Eviction & CFPB Macro Datasets' in ⚙️ Alerts & Data Sync.")
            else:
                metro_counties = sorted(df_ev_metro["county"].unique())
                ctl_c1, ctl_c2 = st.columns([3, 1])
                with ctl_c1:
                    sel_ev_counties = st.multiselect(
                        "Counties",
                        options=metro_counties,
                        default=metro_counties,
                        key="metro_ev_counties"
                    )
                with ctl_c2:
                    ev_smooth = st.toggle("3-month average", value=True, key="metro_ev_smooth")

                plot_df = df_ev_metro[df_ev_metro["county"].isin(sel_ev_counties)].copy()
                plot_df = plot_df.sort_values(["county", "date"])
                if ev_smooth:
                    plot_df["value"] = plot_df.groupby("county")["filings"].transform(
                        lambda s: s.rolling(3, min_periods=1).mean()
                    )
                else:
                    plot_df["value"] = plot_df["filings"]

                # Flagged reporting-gap months are left out of the trend line so they don't look like real drops
                line_df = plot_df.copy()
                line_df.loc[line_df["possible_gap"], "value"] = np.nan

                fig_metro = px.line(
                    line_df,
                    x="date",
                    y="value",
                    color="county",
                    labels={"value": "Filings / month", "date": "Date", "county": "County"},
                    template="plotly_dark"
                )
                gap_df = plot_df[plot_df["possible_gap"]]
                if not gap_df.empty:
                    fig_metro.add_trace(go.Scatter(
                        x=gap_df["date"],
                        y=gap_df["filings"],
                        mode="markers",
                        name="Likely reporting gap",
                        marker=dict(symbol="x", size=9, color="#f59e0b"),
                        hovertext=gap_df["county"] + ": " + gap_df["filings"].map("{:,}".format) + " filings (incomplete?)",
                        hoverinfo="text"
                    ))
                fig_metro.add_vrect(
                    x0="2020-03-01", x1="2021-08-31",
                    fillcolor="#38bdf8", opacity=0.1, line_width=0,
                    annotation_text="CDC Moratorium", annotation_position="top left"
                )
                fig_metro.update_layout(
                    yaxis=dict(title="Eviction filings / month", tickformat=","),
                    height=400,
                    margin=dict(l=15, r=15, t=25, b=15),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,23,42,0.4)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_metro, width="stretch")

                # Compact county summary table
                latest_date = df_ev_metro["date"].max()
                last_full_year = latest_date.year - 1
                summary_rows = []
                for county in sel_ev_counties:
                    cdf = df_ev_metro[df_ev_metro["county"] == county]
                    latest = cdf[cdf["date"] == latest_date]
                    yr_now = cdf[cdf["year"] == last_full_year]["filings"].sum()
                    yr_prev = cdf[cdf["year"] == last_full_year - 1]["filings"].sum()
                    summary_rows.append({
                        "County": county,
                        f"Latest ({latest_date:%b %Y})": int(latest["filings"].sum()) if not latest.empty else 0,
                        f"{last_full_year} Total": int(yr_now),
                        f"vs {last_full_year - 1}": f"{((yr_now - yr_prev) / yr_prev * 100):+.1f}%" if yr_prev else "n/a",
                        "Data Flag": "⚠️ Likely incomplete" if (not latest.empty and bool(latest["possible_gap"].any())) else "",
                    })
                st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

                flagged = df_ev_metro[df_ev_metro["possible_gap"] & df_ev_metro["county"].isin(sel_ev_counties)]
                if not flagged.empty:
                    flag_desc = ", ".join(
                        f"{c} ({', '.join(g['date'].dt.strftime('%b %Y'))})"
                        for c, g in flagged.groupby("county")
                    )
                    st.caption(
                        f"⚠️ Likely reporting gaps (one county drops below half its recent level while the others hold steady): {flag_desc}. "
                        "These months are marked ✕ and left out of the trend line."
                    )
                st.caption(
                    f"Source: {DATA_SOURCES['evictions_metro']['publisher']} ({FETCH_STATUS.get('evictions_metro', 'cache')}) · "
                    "Counts court filings, not completed evictions · Published with a ~4–5 month lag · Forsyth not covered."
                )

        elif distress_view == "📈 Monthly Eviction Filings (2016–2026)" and not df_ev.empty:
            df_ev_plot = df_ev.copy()
            df_ev_plot["rolling_3m"] = df_ev_plot["filings"].rolling(3, min_periods=1).mean()
            fig_ev = go.Figure()
            fig_ev.add_trace(go.Bar(
                x=df_ev_plot["date"],
                y=df_ev_plot["filings"],
                name="Monthly Filings",
                marker_color="#6366f1",
                opacity=0.6
            ))
            fig_ev.add_trace(go.Scatter(
                x=df_ev_plot["date"],
                y=df_ev_plot["rolling_3m"],
                name="3-Month Avg",
                mode="lines",
                line=dict(color="#f43f5e", width=2.5)
            ))
            fig_ev.add_vrect(
                x0="2020-03-01", x1="2021-08-31",
                fillcolor="#38bdf8", opacity=0.1, line_width=0,
                annotation_text="CDC Moratorium", annotation_position="top left"
            )
            fig_ev.update_layout(
                yaxis=dict(title="Dispossessory Filings", tickformat=","),
                xaxis=dict(title="Date"),
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.4)",
                height=400,
                margin=dict(l=15, r=15, t=25, b=15),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_ev, width="stretch")

        elif distress_view == "🏛️ Mortgage 90+ Day Delinquency by County (2008–2025)" and not df_mort.empty:
            selected_mort_counties = st.multiselect(
                "Counties",
                options=sorted(df_mort["county"].unique()),
                default=["Gwinnett County", "Fulton County", "DeKalb County", "Cobb County"]
            )
            df_mort_filtered = df_mort[df_mort["county"].isin(selected_mort_counties)]
            fig_mort = px.line(
                df_mort_filtered,
                x="date",
                y="late_90_plus_pct",
                color="county",
                labels={"late_90_plus_pct": "90+ Days Late (%)", "date": "Date"},
                template="plotly_dark"
            )
            fig_mort.update_layout(
                yaxis=dict(title="90+ Days Delinquent (%)", tickformat=".1f"),
                height=400,
                margin=dict(l=15, r=15, t=25, b=15),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,23,42,0.4)",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_mort, width="stretch")

        elif distress_view == "📊 Annual Multi-Year Comparison":
            ann_c1, ann_c2 = st.columns(2)
            with ann_c1:
                if not df_ev.empty:
                    df_annual = df_ev.groupby("year")["filings"].sum().reset_index()
                    fig_ann_ev = px.bar(
                        df_annual, x="year", y="filings", text="filings",
                        title="Annual Eviction Filings (Fulton County)",
                        template="plotly_dark", color_discrete_sequence=["#6366f1"]
                    )
                    fig_ann_ev.update_traces(texttemplate="%{text:,.0f}", textposition="outside")
                    fig_ann_ev.update_layout(height=360, paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=15, r=15, t=40, b=15))
                    st.plotly_chart(fig_ann_ev, width="stretch")
            with ann_c2:
                if not df_mort.empty:
                    recent_mort = (
                        df_mort[df_mort["county"].isin(["Gwinnett County", "Fulton County"])]
                        .groupby(["county", "year"])[["late_90_plus_pct"]]
                        .mean()
                        .reset_index()
                    )
                    recent_mort = recent_mort[recent_mort["year"] >= 2018]
                    fig_ann_mort = px.bar(
                        recent_mort, x="year", y="late_90_plus_pct", color="county", barmode="group",
                        title="Avg 90+ Day Delinquency % (2018–2025)",
                        template="plotly_dark"
                    )
                    fig_ann_mort.update_layout(height=360, paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=15, r=15, t=40, b=15))
                    st.plotly_chart(fig_ann_mort, width="stretch")

        with st.expander("📚 Data Sources, Methodology & Raw CSV Download", expanded=False):
            sc1, sc_m, sc2, sc3 = st.columns(4)
            with sc_m:
                st.markdown(f"**{DATA_SOURCES['evictions_metro']['name']}**")
                st.caption(f"{DATA_SOURCES['evictions_metro']['publisher']} · {DATA_SOURCES['evictions_metro']['notes']}")
                st.link_button("Open Eviction Lab Data ↗", DATA_SOURCES["evictions_metro"]["page_url"], width="stretch")
                if not df_ev_metro.empty:
                    st.download_button(
                        "📥 Download Metro County Evictions CSV",
                        data=df_ev_metro.to_csv(index=False).encode("utf-8"),
                        file_name="metro_atlanta_county_evictions.csv",
                        mime="text/csv",
                        width="stretch"
                    )
            with sc1:
                st.markdown(f"**{DATA_SOURCES['evictions']['name']}**")
                st.caption(f"{DATA_SOURCES['evictions']['publisher']} · {DATA_SOURCES['evictions']['notes']}")
                st.link_button("Open Fulton Socrata Portal ↗", DATA_SOURCES["evictions"]["page_url"], width="stretch")
                if not df_ev.empty:
                    st.download_button(
                        "📥 Download Evictions CSV",
                        data=df_ev.to_csv(index=False).encode("utf-8"),
                        file_name="fulton_county_evictions.csv",
                        mime="text/csv",
                        width="stretch"
                    )
            with sc2:
                st.markdown(f"**{DATA_SOURCES['mortgage_delinquency']['name']}**")
                st.caption(f"{DATA_SOURCES['mortgage_delinquency']['publisher']} · {DATA_SOURCES['mortgage_delinquency']['notes']}")
                st.link_button("Open CFPB Portal ↗", DATA_SOURCES["mortgage_delinquency"]["page_url"], width="stretch")
                if not df_mort.empty:
                    st.download_button(
                        "📥 Download CFPB Delinquency CSV",
                        data=df_mort.to_csv(index=False).encode("utf-8"),
                        file_name="cfpb_metro_atlanta_delinquency.csv",
                        mime="text/csv",
                        width="stretch"
                    )
            with sc3:
                st.markdown(f"**{DATA_SOURCES['ga_legal_notices']['name']}**")
                st.caption(f"{DATA_SOURCES['ga_legal_notices']['publisher']} · {DATA_SOURCES['ga_legal_notices']['notes']}")
                st.link_button("Open GA Trustee Notices ↗", DATA_SOURCES["ga_legal_notices"]["page_url"], width="stretch")

    # ====================================================
    # TAB 5: Alerts & Data Sync (Combined Operations View)
    # ====================================================
    with tab_ops:
        ops_left, ops_right = st.columns([1.15, 1])

        # Left Column: Triggered Alerts & Rules
        with ops_left:
            st.markdown("##### 🚨 Recent Deal Alerts")
            alert_filter = st.radio(
                "Alert Category",
                ["All Alerts", "🔥 Price Drops", "💎 Sub-$220/sf Bargains"],
                horizontal=True,
                label_visibility="collapsed"
            )

            with get_session() as session:
                recent_alerts = get_recent_alerts(session, limit=25)
                rules = get_alert_rules(session)

            if not recent_alerts:
                st.info("No triggered alerts yet.")
            else:
                shown = 0
                for a in recent_alerts:
                    msg = a.message or ""
                    is_drop = "price cut" in msg.lower() or "price drop" in msg.lower()
                    is_bargain = "sub-$" in msg.lower() or "bargain" in msg.lower()
                    if alert_filter == "🔥 Price Drops" and not is_drop:
                        continue
                    if alert_filter == "💎 Sub-$220/sf Bargains" and not is_bargain:
                        continue
                    shown += 1
                    time_str = a.triggered_at.strftime("%b %d, %H:%M") if a.triggered_at else ""
                    border_col = "#ef4444" if is_drop else "#10b981"
                    st.html(
                        f"<div style='background:rgba(30,41,59,0.5);border-left:3px solid {border_col};"
                        f"padding:8px 12px;border-radius:6px;margin-bottom:6px;display:flex;justify-content:space-between;'>"
                        f"<span style='font-size:12.5px;color:#f1f5f9;'>{md_escape(msg)}</span>"
                        f"<span style='font-size:11px;color:#94a3b8;white-space:nowrap;margin-left:8px;'>{time_str}</span>"
                        f"</div>"
                    )
                if shown == 0:
                    st.info("No alerts in this category.")

            with st.expander("⚙️ Manage & Create Alert Rules", expanded=False):
                for r in rules:
                    conds = []
                    if r.min_price_drop_pct:
                        conds.append(f"Drop ≥ {r.min_price_drop_pct}%")
                    if r.max_price_per_sqft:
                        conds.append(f"≤ ${r.max_price_per_sqft:.0f}/sf")
                    if r.cities:
                        conds.append(r.cities)
                    st.caption(f"{'🟢' if r.is_active else '⚪'} **{md_escape(r.name)}** — {' · '.join(conds) or 'All listings'}")

                with st.form("custom_rule_form"):
                    st.markdown("**New Rule**")
                    new_rule_name = st.text_input("Rule Name", placeholder="e.g. Suwanee Price Cut > 5%")
                    fc1, fc2 = st.columns(2)
                    with fc1:
                        new_drop_pct = st.number_input("Min Drop %", 0.0, 50.0, 5.0, 0.5)
                        new_max_ppsf = st.number_input("Max $/SqFt", 100.0, 600.0, 220.0, 10.0)
                    with fc2:
                        new_max_price = st.number_input("Max Budget ($)", 100_000, 3_000_000, 750_000, 25_000)
                        new_cities = st.multiselect("Cities", all_cities, default=["Duluth", "Suwanee"])
                    if st.form_submit_button("Save Rule", type="primary", width="stretch") and new_rule_name:
                        with get_session() as session:
                            session.add(AlertRule(
                                name=new_rule_name,
                                is_active=True,
                                min_price_drop_pct=new_drop_pct,
                                max_price_per_sqft=new_max_ppsf,
                                cities=",".join(new_cities) if new_cities else None,
                                max_price=new_max_price
                            ))
                            session.commit()
                        st.success(f"Saved rule: {new_rule_name}")
                        st.rerun()

        # Right Column: Live Ingestion & Snapshots
        with ops_right:
            with st.container(border=True):
                st.markdown("##### ⚡ Run Data Ingestion Pipeline")
                st.caption("Scrape active listings, foreclosures, Redfin GIS feeds, and GA auction notices.")

                sc_a, sc_b = st.columns(2)
                with sc_a:
                    src_mls = st.checkbox("🏡 MLS / Realtor", value=True)
                    src_fc = st.checkbox("⚠️ Foreclosures / REO", value=True)
                with sc_b:
                    src_rf = st.checkbox("📊 Redfin Open Data", value=True)
                    src_auc = st.checkbox("🏛️ GA Legal Notices", value=True)

                ingest_submarkets = st.multiselect(
                    "Target Submarkets",
                    all_cities,
                    default=["Duluth", "Suwanee", "Norcross", "Peachtree Corners"]
                )

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
                        st.error("Select at least one data source.")
                    else:
                        with st.spinner(f"Running ingestion ({', '.join(selected_sources)})..."):
                            res = run_pipeline(sources=selected_sources, submarkets=ingest_submarkets)
                            st.success(
                                f"Done! Processed {res['total_processed']} · Inserted {res['inserted']} "
                                f"· Updated {res['updated']} · Alerts {res['alerts_triggered']}"
                            )
                            st.rerun()

                if st.button("🔄 Refresh Eviction & CFPB Macro Datasets", width="stretch"):
                    with st.spinner("Refreshing Fulton Socrata, Eviction Lab & CFPB datasets..."):
                        fetch_historical_eviction_filings()
                        fetch_metro_eviction_filings(force_refresh=True)
                        fetch_historical_mortgage_delinquency()
                        st.success("Macro distress datasets updated.")
                        st.rerun()

            with st.expander("🕓 Recent Ingestion Snapshots", expanded=False):
                with get_session() as session:
                    snapshots = (
                        session.query(IngestionSnapshot)
                        .order_by(IngestionSnapshot.timestamp.desc())
                        .limit(10)
                        .all()
                    )
                    if snapshots:
                        st.dataframe(pd.DataFrame([s.to_dict() for s in snapshots]), width="stretch", hide_index=True)
                    else:
                        st.info("No snapshots recorded yet.")


if __name__ == "__main__":
    render_dashboard()

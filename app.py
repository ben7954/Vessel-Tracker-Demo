import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime
import pydeck as pdk

st.set_page_config(page_title="Maritime Tracking & Dead Reckoning Dashboard", layout="wide")

st.title("🚢 European Corridor Vessel Tracker & Predictive Dashboard")
st.markdown("Tracking container vessels with customizable color-coded tracking, speed telemetry, and rich hover tooltips.")

CSV_FILE = "vessel_historyv1.csv"
STATIC_CSV_FILE = "vessel_metadata.csv"

@st.cache_data(ttl=10)
def load_data():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(), pd.DataFrame()
    
    df = pd.read_csv(CSV_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    
    meta_df = pd.DataFrame(columns=["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute", "timestamp"])
    if os.path.exists(STATIC_CSV_FILE):
        meta_df = pd.read_csv(STATIC_CSV_FILE)
        meta_df["timestamp"] = pd.to_datetime(meta_df["timestamp"], errors="coerce")
        meta_df = meta_df.sort_values("timestamp").drop_duplicates(subset=["mmsi"], keep="last")
        
    return df, meta_df

df, meta_df = load_data()

if df.empty:
    st.warning("⚠️ No vessel position data found in `vessel_history.csv` yet. Make sure your `logger.py` is running.")
else:
    df["mmsi"] = df["mmsi"].astype(str)
    
    # Ensure speed column is numeric
    if "speed_over_ground" in df.columns:
        df["speed_over_ground"] = pd.to_numeric(df["speed_over_ground"], errors="coerce").fillna(0.0)
    else:
        df["speed_over_ground"] = 0.0

    # Merge destination metadata if available
    if not meta_df.empty:
        meta_df["mmsi"] = meta_df["mmsi"].astype(str)
        df = pd.merge(df, meta_df[["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute"]], on="mmsi", how="left")
    else:
        df["destination"] = "Unknown"
        df["eta_month"] = 0
        df["eta_day"] = 0
        df["eta_hour"] = 24
        df["eta_minute"] = 60

    df["destination"] = df["destination"].fillna("Unknown")

    # --- Sidebar Controls & Custom Color Pickers ---
    st.sidebar.header("Dashboard Controls")
    
    search_query = st.sidebar.text_input("🔍 Search Name or MMSI", "").strip().lower()

    liner_filter = st.sidebar.multiselect(
        "🚢 Filter by Shipping Line",
        ["MAERSK", "MSC", "CMA CGM", "HAPAG-LLOYD", "ONE", "EVERGREEN"],
        default=[]
    )

    cargo_only = st.sidebar.checkbox("📦 Show Container / Cargo Vessels Only", value=False)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎨 Map Color Customizer")
    live_color_hex = st.sidebar.color_picker("Live Signal Color", "#00C864")
    pred_color_hex = st.sidebar.color_picker("Dead Reckoning Color", "#FF8C00")

    # Helper to convert hex to RGB list for PyDeck
    def hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip('#')
        return [int(hex_str[i:i+2], 16) for i in (0, 2, 4)] + [220]

    live_rgb = hex_to_rgb(live_color_hex)
    pred_rgb = hex_to_rgb(pred_color_hex)

    filtered_df = df.copy()
    if search_query:
        filtered_df = filtered_df[
            filtered_df["ship_name"].str.lower().str.contains(search_query, na=False) | 
            filtered_df["mmsi"].str.lower().str.contains(search_query, na=False)
        ]
    
    if liner_filter:
        pattern = "|".join([liner.lower() for liner in liner_filter])
        filtered_df = filtered_df[filtered_df["ship_name"].str.lower().str.contains(pattern, na=False)]

    if cargo_only:
        container_keywords = ["maersk", "msc", "cma", "hapag", "evergreen", "express", "container", "feeder", "spirit", "leader"]
        pattern = "|".join(container_keywords)
        filtered_df = filtered_df[filtered_df["ship_name"].str.lower().str.contains(pattern, na=False)]

    # --- Dead Reckoning, Speed & ETA Calculation ---
    now = datetime.now()
    projected_rows = []

    for mmsi, group in df.groupby("mmsi"):
        latest = group.sort_values("timestamp").iloc[-1].copy()
        
        hours_elapsed = (now - latest["timestamp"]).total_seconds() / 3600.0
        
        # Dead Reckoning & Color Assignment
        if hours_elapsed > 0.1 and pd.notnull(latest["cog"]) and pd.notnull(latest["speed_over_ground"]) and latest["speed_over_ground"] > 0:
            distance_nm = latest["speed_over_ground"] * hours_elapsed
            distance_deg = distance_nm / 60.0
            angle_rad = np.radians(latest["cog"])
            
            latest["latitude"] += distance_deg * np.cos(angle_rad)
            latest["longitude"] += (distance_deg * np.sin(angle_rad)) / np.cos(np.radians(latest["latitude"]))
            latest.loc["tracking_status"] = f"Predicted (+{hours_elapsed:.1f}h)"
            latest.loc["status_color"] = pred_rgb
            latest.loc["marker_size"] = 8000  # Scaled down to prevent giant shapes
        else:
            latest.loc["tracking_status"] = "Live / Recent"
            latest.loc["status_color"] = live_rgb
            latest.loc["marker_size"] = 6000
            
        # Strict ETA Validation
        eta_str = "Not Available"
        try:
            m_val = int(latest.get("eta_month", 0))
            d_val = int(latest.get("eta_day", 0))
            h_val = int(latest.get("eta_hour", 24))
            min_val = int(latest.get("eta_minute", 60))
            
            if 1 <= m_val <= 12 and 1 <= d_val <= 31:
                current_year = now.year
                eta_dt = datetime(current_year, m_val, d_val, h_val if h_val < 24 else 0, min_val if min_val < 60 else 0)
                if eta_dt < now:
                    eta_dt = datetime(current_year + 1, m_val, d_val, h_val if h_val < 24 else 0, min_val if min_val < 60 else 0)
                
                remaining = eta_dt - now
                days = remaining.days
                hours = remaining.seconds // 3600
                if days <= 30:
                    eta_str = f"{days}d {hours}h ({eta_dt.strftime('%b %d %H:%M')})"
        except Exception:
            eta_str = "Not Available"
            
        latest["eta_countdown"] = eta_str
        projected_rows.append(latest)

    proj_df = pd.DataFrame(projected_rows)

    # Apply filters to projected table
    proj_filtered = proj_df.copy()
    if search_query:
        proj_filtered = proj_filtered[
            proj_filtered["ship_name"].str.lower().str.contains(search_query, na=False) | 
            proj_filtered["mmsi"].str.lower().str.contains(search_query, na=False)
        ]
    if liner_filter:
        pattern = "|".join([liner.lower() for liner in liner_filter])
        proj_filtered = proj_filtered[proj_filtered["ship_name"].str.lower().str.contains(pattern, na=False)]
    if cargo_only:
        container_keywords = ["maersk", "msc", "cma", "hapag", "evergreen", "express", "container", "feeder", "spirit", "leader"]
        pattern = "|".join(container_keywords)
        proj_filtered = proj_filtered[proj_filtered["ship_name"].str.lower().str.contains(pattern, na=False)]

    # --- Watchlist Session State ---
    if "saved_vessels" not in st.session_state:
        st.session_state.saved_vessels = []

    st.sidebar.markdown("---")
    st.sidebar.subheader("⭐ Saved Watchlist")
    if st.session_state.saved_vessels:
        for saved_mmsi in st.session_state.saved_vessels:
            ship_match = df[df["mmsi"] == saved_mmsi]
            s_name = ship_match["ship_name"].iloc[-1] if not ship_match.empty else saved_mmsi
            st.sidebar.text(f"• {s_name}")
        if st.sidebar.button("Clear Watchlist"):
            st.session_state.saved_vessels = []
    else:
        st.sidebar.info("No vessels saved yet. Click 'Save' in the table below.")

    # --- Summary Metrics ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Unique Vessels Tracked", df["mmsi"].nunique())
    col2.metric("Filtered Vessels Shown", len(proj_filtered))
    col3.metric("Active Corridors", "Gibraltar -> Finisterre -> Biscay -> Channel")

    # --- PyDeck Interactive Map with Scaled Markers & Hover Tooltips ---
    st.subheader("🗺️ Interactive Vessel Map")
    
    if not proj_filtered.empty:
        mid_lat = proj_filtered["latitude"].mean()
        mid_lon = proj_filtered["longitude"].mean()

        layer = pdk.Layer(
            "ScatterplotLayer",
            data=proj_filtered,
            get_position=["longitude", "latitude"],
            get_color="status_color",
            get_radius="marker_size",
            pickable=True,
            auto_highlight=True,
        )

        tooltip_config = {
            "html": "<b>Vessel:</b> {ship_name}<br/><b>MMSI:</b> {mmsi}<br/><b>Destination:</b> {destination}<br/><b>ETA:</b> {eta_countdown}<br/><b>Speed:</b> {speed_over_ground} knots<br/><b>Status:</b> {tracking_status}",
            "style": {"backgroundColor": "#1E1E1E", "color": "white", "zIndex": "9999"}
        }

        view_state = pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=5, pitch=0)
        
        r = pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip=tooltip_config)
        st.pydeck_chart(r)
    else:
        st.info("No vessels match your active filters on the map.")

    # --- Active Vessel Status Table ---
    st.subheader("📋 Current Vessel Status, Speed & Watchlist")
    if not proj_filtered.empty:
        for idx, row in proj_filtered.iterrows():
            cols = st.columns([3, 2, 2, 2, 2, 1])
            cols[0].write(f"**{row['ship_name']}** (MMSI: {row['mmsi']})")
            cols[1].write(f"Dest: {row['destination']}")
            cols[2].write(f"ETA: {row['eta_countdown']}")
            cols[3].write(f"Speed: {row['speed_over_ground']} kn")
            cols[4].write(f"Status: {row['tracking_status']}")
            
            mmsi_val = str(row['mmsi'])
            is_saved = mmsi_val in st.session_state.saved_vessels
            btn_label = "★ Saved" if is_saved else "☆ Save"
            if cols[5].button(btn_label, key=f"save_{mmsi_val}_{idx}"):
                if is_saved:
                    st.session_state.saved_vessels.remove(mmsi_val)
                else:
                    st.session_state.saved_vessels.append(mmsi_val)
                st.rerun()
    else:
        st.info("No vessel records found matching your filters.")

    # --- Raw Logged Data Expander ---
    with st.expander("🔍 View Full Raw Historical Logs"):
        st.dataframe(filtered_df.sort_values("timestamp", ascending=False))

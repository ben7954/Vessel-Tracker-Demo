import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime

st.set_page_config(page_title="Maritime Tracking & Dead Reckoning Dashboard", layout="wide")

st.title("🚢 European Corridor Vessel Tracker & Predictive Dashboard")
st.markdown("Tracking vessels across Gibraltar, Bay of Biscay, and Northern Europe with dead-reckoning trajectory estimation, destination mapping, and ETA countdowns.")

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
    # Ensure mmsi is string for clean matching
    df["mmsi"] = df["mmsi"].astype(str)
    
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

    # --- Sidebar Search Controls ---
    st.sidebar.header("Dashboard Controls")
    search_query = st.sidebar.text_input("🔍 Search Vessel Name or MMSI", "").strip().lower()

    # Filter DataFrame based on search input
    if search_query:
        filtered_df = df[
            df["ship_name"].str.lower().str.contains(search_query, na=False) | 
            df["mmsi"].str.lower().str.contains(search_query, na=False)
        ]
    else:
        filtered_df = df

    # --- Dead Reckoning & ETA Countdown Calculation ---
    now = datetime.now()
    projected_rows = []

    for mmsi, group in df.groupby("mmsi"):
        latest = group.sort_values("timestamp").iloc[-1].copy()
        
        # Dead Reckoning projection based on elapsed time since last ping
        hours_elapsed = (now - latest["timestamp"]).total_seconds() / 3600.0
        
        if hours_elapsed > 0.1 and pd.notnull(latest["cog"]) and pd.notnull(latest["speed_over_ground"]):
            distance_nm = latest["speed_over_ground"] * hours_elapsed
            distance_deg = distance_nm / 60.0
            angle_rad = np.radians(latest["cog"])
            
            latest["latitude"] += distance_deg * np.cos(angle_rad)
            latest["longitude"] += (distance_deg * np.sin(angle_rad)) / np.cos(np.radians(latest["latitude"]))
            latest.loc["tracking_status"] = f"Predicted (+{hours_elapsed:.1f}h est.)"
        else:
            latest.loc["tracking_status"] = "Live / Recent"
            
        # Calculate ETA countdown
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
                eta_str = f"{days}d {hours}h remaining ({eta_dt.strftime('%b %d %H:%M')})"
        except Exception:
            eta_str = "Unknown"
            
        latest["eta_countdown"] = eta_str
        projected_rows.append(latest)

    proj_df = pd.DataFrame(projected_rows)

    # Filter projected table based on search query as well
    if search_query and not proj_df.empty:
        proj_filtered = proj_df[
            proj_df["ship_name"].str.lower().str.contains(search_query, na=False) | 
            proj_df["mmsi"].str.lower().str.contains(search_query, na=False)
        ]
    else:
        proj_filtered = proj_df

    # --- Summary Metrics ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Unique Vessels Tracked", df["mmsi"].nunique())
    col2.metric("Total Position Logs", len(df))
    col3.metric("Active Corridors", "Gibraltar -> Biscay -> Channel")

    # --- Native Interactive Map View ---
    st.subheader("🗺️ Native Live Vessel Map")
    if not proj_filtered.empty:
        # Streamlit's built-in map uses 'latitude' and 'longitude' columns automatically
        st.map(proj_filtered, latitude="latitude", longitude="longitude", size=30, color="#ff4b4b")
    else:
        st.info("No vessels match your search query on the map.")

    # --- Active Vessel Status Table ---
    st.subheader("📋 Current Vessel Status, Destinations & ETAs")
    if not proj_filtered.empty:
        display_table = proj_filtered[["ship_name", "mmsi", "destination", "eta_countdown", "speed_over_ground", "tracking_status", "timestamp"]].copy()
        display_table.columns = ["Ship Name", "MMSI", "Destination", "ETA Countdown", "Speed (knots)", "Status", "Last Ping"]
        st.dataframe(display_table, use_container_width=True)
    else:
        st.info("No vessel records found matching your search.")

    # --- Raw Logged Data Expander ---
    with st.expander("🔍 View Full Raw Historical Logs"):
        st.dataframe(filtered_df.sort_values("timestamp", ascending=False))

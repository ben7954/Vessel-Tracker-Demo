import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import numpy as np
import os

st.set_page_config(page_title="Maritime Tracking & Dead Reckoning Dashboard", layout="wide")

st.title("🚢 European Corridor Vessel Tracker & Predictive Dashboard")
st.markdown("Tracking vessels across Gibraltar, Bay of Biscay, and Northern Europe with dead-reckoning trajectory estimation, destination mapping, and ETA countdowns.")

CSV_FILE = "vessel_history.csv"
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
        meta_df = meta_df.sort_values("timestamp").drop_duplicates(subset=["mmsi"], keep="last")
        
    return df, meta_df

df, meta_df = load_data()

if df.empty:
    st.warning("⚠️ No vessel position data found in `vessel_history.csv` yet. Make sure your `logger.py` is running.")
else:
    # Merge destination metadata if available
    if not meta_df.empty:
        df = pd.merge(df, meta_df[["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute"]], on="mmsi", how="left")
    else:
        df["destination"] = "Unknown"
        df["eta_month"] = 0
        df["eta_day"] = 0
        df["eta_hour"] = 24
        df["eta_minute"] = 60

    df["destination"] = df["destination"].fillna("Unknown")

    st.sidebar.header("Dashboard Controls")
    selected_ship = st.sidebar.selectbox("Filter Vessel", ["All Vessels"] + list(df["ship_name"].unique()))

    if selected_ship != "All Vessels":
        filtered_df = df[df["ship_name"] == selected_ship]
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

    # --- Summary Metrics ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Unique Vessels Tracked", df["mmsi"].nunique())
    col2.metric("Total Position Logs", len(df))
    col3.metric("Active Corridors", "Gibraltar -> Biscay -> Channel")

    # --- Plotly Visualization (Grid View) ---
    st.subheader("Vessel Route Trails & Dead-Reckoning Estimates")
    
    fig = px.scatter(
        filtered_df,
        x="longitude",
        y="latitude",
        color="ship_name",
        hover_data=["mmsi", "speed_over_ground", "timestamp", "cog", "destination"],
        title="Historical Tracks & Corridor Positions",
        labels={"longitude": "Longitude (°)", "latitude": "Latitude (°)"}
    )

    # Add projected dead reckoning markers with Destination & ETA tooltips
    if not proj_df.empty:
        fig.add_scatter(
            x=proj_df["longitude"],
            y=proj_df["latitude"],
            mode="markers+text",
            text=proj_df["ship_name"],
            textposition="top center",
            marker=dict(size=14, symbol="x", color="red"),
            customdata=np.stack((proj_df["destination"], proj_df["eta_countdown"], proj_df["tracking_status"]), axis=-1),
            hovertemplate="<b>%{text}</b><br>Destination: %{customdata[0]}<br>ETA: %{customdata[1]}<br>Status: %{customdata[2]}<br>Lat/Lon: (%{y:.2f}, %{x:.2f})<extra></extra>",
            name="Estimated Position (Dead Reckoning)"
        )

    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    fig.update_layout(height=650, margin={"r": 20, "t": 40, "l": 20, "b": 20})
    
    st.plotly_chart(fig, use_container_width=True)

    # --- Active Vessel Status Table ---
    st.subheader("Current Vessel Status, Destinations & ETAs")
    display_table = proj_df[["ship_name", "mmsi", "destination", "eta_countdown", "speed_over_ground", "tracking_status", "timestamp"]].copy()
    display_table.columns = ["Ship Name", "MMSI", "Destination", "ETA Countdown", "Speed (knots)", "Status", "Last Ping"]
    st.dataframe(display_table, use_container_width=True)

    # --- Raw Logged Data Expander ---
    with st.expander("View Full Raw Historical Logs"):
        st.dataframe(filtered_df.sort_values("timestamp", ascending=False))


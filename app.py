import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime
import pydeck as pdk

st.set_page_config(page_title="Maritime Tracking & Dead Reckoning Dashboard", layout="wide")

st.title("🚢 European Corridor Vessel Tracker & Predictive Dashboard")
st.markdown("Tracking container vessels with scaled rectangular ship hulls, historical track paths, dead-reckoning projection vectors, speed telemetry, and rich hover tooltips.")

CSV_FILE = "vessel_historyv1.csv"
STATIC_CSV_FILE = "vessel_metadata.csv"


@st.cache_data(ttl=10)
def load_data():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(), pd.DataFrame()

    df = pd.read_csv(CSV_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["timestamp", "latitude", "longitude"])

    meta_df = pd.DataFrame(columns=["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute", "timestamp"])
    if os.path.exists(STATIC_CSV_FILE):
        meta_df = pd.read_csv(STATIC_CSV_FILE)
        meta_df["timestamp"] = pd.to_datetime(meta_df["timestamp"], errors="coerce")
        meta_df = meta_df.sort_values("timestamp").drop_duplicates(subset=["mmsi"], keep="last")

    return df, meta_df


df, meta_df = load_data()

if df.empty:
    st.warning("⚠️ No vessel position data found in `vessel_historyv1.csv` yet. Make sure your `logger.py` is running.")
else:
    df["mmsi"] = df["mmsi"].astype(str).str.strip()
    df["ship_name"] = df["ship_name"].fillna("Unknown").astype(str).str.strip()

    # Ensure speed and course columns are numeric
    if "speed_over_ground" in df.columns:
        df["speed_over_ground"] = pd.to_numeric(df["speed_over_ground"], errors="coerce").fillna(0.0)
    else:
        df["speed_over_ground"] = 0.0

    if "cog" in df.columns:
        df["cog"] = pd.to_numeric(df["cog"], errors="coerce")
    else:
        df["cog"] = np.nan

    # Merge destination metadata if available
    if not meta_df.empty:
        meta_df["mmsi"] = meta_df["mmsi"].astype(str).str.strip()
        df = pd.merge(
            df,
            meta_df[["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute"]],
            on="mmsi",
            how="left",
        )
    else:
        df["destination"] = "Unknown"
        df["eta_month"] = 0
        df["eta_day"] = 0
        df["eta_hour"] = 24
        df["eta_minute"] = 60

    df["destination"] = (
        df["destination"]
        .astype(str)
        .str.strip()
        .replace({"": "Unknown", "nan": "Unknown", "None": "Unknown"})
    )

    # --- Sidebar Controls & Custom Color Pickers ---
    st.sidebar.header("Dashboard Controls")

    search_query = st.sidebar.text_input("🔍 Search Name or MMSI", "").strip().lower()

    liner_filter = st.sidebar.multiselect(
        "🚢 Filter by Shipping Line",
        ["MAERSK", "MSC", "CMA CGM", "HAPAG-LLOYD", "ONE", "EVERGREEN", "OOCL", "COSCO", "ZIM", "YANG MING"],
        default=[],
    )

    cargo_only = st.sidebar.checkbox("📦 Show Container / Cargo Vessels Only", value=False)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🛤️ Track & Route Overlays")
    show_history_tracks = st.sidebar.checkbox("Show Historical Track Lines", value=True)
    show_dr_vectors = st.sidebar.checkbox("Show Dead-Reckoning Vectors", value=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎨 Map Color Customizer")
    live_color_hex = st.sidebar.color_picker("Live Signal Color", "#00C864")
    pred_color_hex = st.sidebar.color_picker("Dead Reckoning Color", "#FF8C00")
    track_color_hex = st.sidebar.color_picker("Historical Track Color", "#38BDF8")

    def hex_to_rgb(hex_str, alpha=220):
        hex_str = hex_str.lstrip("#")
        return [int(hex_str[i : i + 2], 16) for i in (0, 2, 4)] + [alpha]

    live_rgb = hex_to_rgb(live_color_hex, alpha=220)
    pred_rgb = hex_to_rgb(pred_color_hex, alpha=220)
    track_rgb = hex_to_rgb(track_color_hex, alpha=190)

    container_keywords = [
        "maersk",
        "msc",
        "cma",
        "hapag",
        "evergreen",
        "oocl",
        "cosco",
        "zim",
        "yang ming",
        "ym ",
        "sealand",
        "express",
        "container",
        "feeder",
        "cargo",
        "bulk",
        "box",
        "spirit",
        "leader",
        "bridge",
        "bay",
        "stream",
    ]

    def apply_vessel_filters(frame):
        out = frame.copy()
        names_lower = out["ship_name"].str.lower()
        mmsi_lower = out["mmsi"].str.lower()

        if search_query:
            out = out[
                names_lower.str.contains(search_query, regex=False, na=False)
                | mmsi_lower.str.contains(search_query, regex=False, na=False)
            ]
            names_lower = out["ship_name"].str.lower()

        if liner_filter:
            pattern = "|".join([liner.lower() for liner in liner_filter])
            out = out[names_lower.str.contains(pattern, regex=True, na=False)]
            names_lower = out["ship_name"].str.lower()

        if cargo_only:
            pattern = "|".join(container_keywords)
            out = out[names_lower.str.contains(pattern, regex=True, na=False)]

        return out

    filtered_df = apply_vessel_filters(df)

    # --- Dead Reckoning, Speed & ETA Calculation ---
    now = datetime.now()
    projected_rows = []
    dr_vector_rows = []

    for mmsi, group in df.groupby("mmsi"):
        latest = group.sort_values("timestamp").iloc[-1].copy()

        raw_lat = float(latest["latitude"])
        raw_lon = float(latest["longitude"])
        proj_lat = raw_lat
        proj_lon = raw_lon

        hours_elapsed = max(0.0, (now - latest["timestamp"]).total_seconds() / 3600.0)
        is_predicted = False

        if (
            hours_elapsed > 0.1
            and pd.notnull(latest["cog"])
            and pd.notnull(latest["speed_over_ground"])
            and latest["speed_over_ground"] > 0
        ):
            distance_nm = latest["speed_over_ground"] * hours_elapsed
            distance_deg = distance_nm / 60.0
            angle_rad = np.radians(latest["cog"])

            proj_lat = raw_lat + distance_deg * np.cos(angle_rad)
            cos_lat = np.cos(np.radians(proj_lat))
            if abs(cos_lat) > 1e-6:
                proj_lon = raw_lon + (distance_deg * np.sin(angle_rad)) / cos_lat

            latest["latitude"] = proj_lat
            latest["longitude"] = proj_lon
            latest.loc["tracking_status"] = f"Predicted (+{hours_elapsed:.1f}h)"
            latest.loc["status_color"] = pred_rgb
            is_predicted = True
        else:
            latest.loc["tracking_status"] = "Live / Recent"
            latest.loc["status_color"] = live_rgb

        # Strict ETA Validation
        eta_str = "Not Available"
        try:
            m_val = int(latest.get("eta_month", 0))
            d_val = int(latest.get("eta_day", 0))
            h_val = int(latest.get("eta_hour", 24))
            min_val = int(latest.get("eta_minute", 60))

            if 1 <= m_val <= 12 and 1 <= d_val <= 31:
                current_year = now.year
                eta_dt = datetime(
                    current_year,
                    m_val,
                    d_val,
                    h_val if h_val < 24 else 0,
                    min_val if min_val < 60 else 0,
                )
                if eta_dt < now:
                    eta_dt = datetime(
                        current_year + 1,
                        m_val,
                        d_val,
                        h_val if h_val < 24 else 0,
                        min_val if min_val < 60 else 0,
                    )

                remaining = eta_dt - now
                days = remaining.days
                hours = remaining.seconds // 3600
                if days <= 30:
                    eta_str = f"{days}d {hours}h ({eta_dt.strftime('%b %d %H:%M')})"
        except Exception:
            eta_str = "Not Available"

        latest["eta_countdown"] = eta_str
        projected_rows.append(latest)

        if is_predicted:
            dr_vector_rows.append(
                {
                    "mmsi": str(mmsi),
                    "ship_name": latest["ship_name"],
                    "line_type": "Dead-Reckoning Projection",
                    "detail": f"+{hours_elapsed:.1f}h @ {latest['speed_over_ground']:.1f} kn",
                    "path": [[raw_lon, raw_lat], [proj_lon, proj_lat]],
                    "color": pred_rgb,
                }
            )

    proj_df = pd.DataFrame(projected_rows)
    proj_filtered = apply_vessel_filters(proj_df)

    # Filter dead-reckoning vectors to match currently filtered vessels
    active_mmsis = set(proj_filtered["mmsi"].astype(str)) if not proj_filtered.empty else set()
    dr_vectors_filtered = [v for v in dr_vector_rows if v["mmsi"] in active_mmsis]

    # Build historical track paths from filtered_df (requires >= 2 distinct points per vessel)
    history_track_rows = []
    if not filtered_df.empty:
        for mmsi, grp in filtered_df.sort_values("timestamp").groupby("mmsi"):
            coords = grp[["longitude", "latitude"]].drop_duplicates().values.tolist()
            if len(coords) >= 2:
                history_track_rows.append(
                    {
                        "mmsi": str(mmsi),
                        "ship_name": grp["ship_name"].iloc[-1],
                        "line_type": "Historical Track",
                        "detail": f"{len(coords)} logged fixes",
                        "path": coords,
                        "color": track_rgb,
                    }
                )

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
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Unique Vessels Tracked", df["mmsi"].nunique())
    col2.metric("Filtered Vessels Shown", len(proj_filtered))
    col3.metric("Historical Tracks (2+ pts)", len(history_track_rows))
    col4.metric("Active DR Vectors (>6m)", len(dr_vectors_filtered))

    # --- PyDeck Interactive Map with Hulls, Historical Tracks & DR Vectors ---
    st.subheader("🗺️ Interactive Vessel Map (Hulls, Tracks & Dead-Reckoning Vectors)")

    if not proj_filtered.empty:
        mid_lat = proj_filtered["latitude"].mean()
        mid_lon = proj_filtered["longitude"].mean()

        layers = []

        if show_history_tracks and history_track_rows:
            history_layer = pdk.Layer(
                "PathLayer",
                data=pd.DataFrame(history_track_rows),
                get_path="path",
                get_color="color",
                width_min_pixels=2,
                width_max_pixels=5,
                pickable=True,
                auto_highlight=True,
            )
            layers.append(history_layer)

        if show_dr_vectors and dr_vectors_filtered:
            dr_layer = pdk.Layer(
                "PathLayer",
                data=pd.DataFrame(dr_vectors_filtered),
                get_path="path",
                get_color="color",
                width_min_pixels=3,
                width_max_pixels=6,
                pickable=True,
                auto_highlight=True,
            )
            layers.append(dr_layer)

        rect_rows = []
        for _, row in proj_filtered.iterrows():
            lat = row["latitude"]
            lon = row["longitude"]

            # Tighter port-scale dimensions to prevent massive overlapping when zoomed in
            lat_size = 0.0025  # ~0.15 nautical miles length
            lon_size = 0.005   # ~0.15 nautical miles width

            polygon = [
                [lon - lon_size / 2, lat - lat_size / 2],
                [lon + lon_size / 2, lat - lat_size / 2],
                [lon + lon_size / 2, lat + lat_size / 2],
                [lon - lon_size / 2, lat + lat_size / 2],
            ]

            r_data = row.to_dict()
            r_data["polygon"] = polygon
            rect_rows.append(r_data)

        poly_df = pd.DataFrame(rect_rows)

        hull_layer = pdk.Layer(
            "PolygonLayer",
            data=poly_df,
            get_polygon="polygon",
            get_fill_color="status_color",
            get_line_color=[255, 255, 255],
            line_width_min_pixels=1,
            pickable=True,
            auto_highlight=True,
        )
        layers.append(hull_layer)

        tooltip_config = {
            "html": (
                "<b>Vessel:</b> {ship_name}<br/>"
                "<b>MMSI:</b> {mmsi}<br/>"
                "<b>Destination:</b> {destination}<br/>"
                "<b>ETA:</b> {eta_countdown}<br/>"
                "<b>Speed:</b> {speed_over_ground} knots<br/>"
                "<b>Status:</b> {tracking_status}<br/>"
                "<b>Track/Vector:</b> {line_type} ({detail})"
            ),
            "style": {"backgroundColor": "#1E1E1E", "color": "white", "zIndex": "9999"},
        }

        view_state = pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=7, pitch=0)

        r = pdk.Deck(layers=layers, initial_view_state=view_state, tooltip=tooltip_config)
        map_key = f"vessel_map_hist_{show_history_tracks}_dr_{show_dr_vectors}"
        st.pydeck_chart(r, key=map_key, use_container_width=True)
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

            mmsi_val = str(row["mmsi"])
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

import json
import websocket
import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

# Page Configuration
st.set_page_config(page_title="Vessel Diversion Predictor", layout="wide")

st.title("🚢 Port-to-Port Vessel Tracker & Diversion Risk")
st.caption("Live AIS Tracking vs. Pro-Forma Schedule Delay Calculator")

# Sidebar Configuration
st.sidebar.header("Vessel Query & Credentials")
API_KEY = st.sidebar.text_input("Aisstream API Key", type="password", value="59b1c83a8504a344ffb4b008fc007b761c00131a")
target_mmsi = st.sidebar.text_input("Vessel MMSI Number", value="255805678")
carrier = st.sidebar.selectbox("Carrier", ["MSC", "Maersk", "CMA CGM", "Hapag-Lloyd"])
scheduled_delay_hrs = st.sidebar.number_input("Current Known Delay (Hours)", min_value=0, max_value=120, value=38)

# Function to fetch live AIS data on demand
def get_live_vessel_data(mmsi_target, api_key):
    latest_data = None
    
    def on_open(ws):
        sub_msg = {
            "APIKey": api_key,
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FiltersShipMMSI": [str(mmsi_target)],
            "FilterMessageTypes": ["PositionReport"]
        }
        ws.send(json.dumps(sub_msg))

    def on_message(ws, message):
        nonlocal latest_data
        data = json.loads(message)
        if data.get("MessageType") == "PositionReport":
            pos = data.get("Message", {}).get("PositionReport", {})
            meta = data.get("MetaData", {})
            
            latest_data = {
                "ship_name": meta.get("ShipName", "Unknown").strip(),
                "lat": pos.get("Latitude"),
                "lon": pos.get("Longitude"),
                "sog": pos.get("SOG")
            }
            ws.close()

    try:
        ws = websocket.WebSocketApp(
            "wss://stream.aisstream.io/v0/stream",
            on_open=on_open,
            on_message=on_message
        )
        ws.run_forever(timeout=5)
    except Exception as e:
        st.error(f"Connection error: {e}")
        
    return latest_data

# Initialize session state to remember the last known position across clicks
if "vessel_cache" not in st.session_state:
    st.session_state.vessel_cache = {
        "lat": 51.45,
        "lon": 0.50,
        "ship_name": "No vessel loaded yet",
        "sog": "0.0"
    }

# Historical Baseline Lookup Data
historical_data = {
    "MSC": {"delay_threshold": 36, "base_omission_rate": 0.65, "barge_delay_days": 3.5},
    "Maersk": {"delay_threshold": 24, "base_omission_rate": 0.35, "barge_delay_days": 2.0},
    "CMA CGM": {"delay_threshold": 30, "base_omission_rate": 0.50, "barge_delay_days": 3.0},
    "Hapag-Lloyd": {"delay_threshold": 28, "base_omission_rate": 0.40, "barge_delay_days": 2.5},
}

carrier_stats = historical_data.get(carrier)

# Probability Calculation Engine
def calculate_risk(delay, stats):
    threshold = stats["delay_threshold"]
    base_rate = stats["base_omission_rate"]
    if delay < 12:
        return 5.0
    calculated_prob = min(95.0, (delay / threshold) * (base_rate * 100))
    return round(calculated_prob, 1)

diversion_prob = calculate_risk(scheduled_delay_hrs, carrier_stats)

# Trigger Live Fetch via Button
if st.sidebar.button("Fetch Last Known / Live Position"):
    if API_KEY == "59b1c83a8504a344ffb4b008fc007b761c00131a" or not API_KEY:
        st.warning("Please enter a valid Aisstream API key in the sidebar.")
    else:
        with st.spinner("Querying AIS stream for latest position report..."):
            live_result = get_live_vessel_data(target_mmsi, API_KEY)
            if live_result and live_result.get('lat'):
                st.session_state.vessel_cache = live_result
                st.success(f"Updated position for: {live_result['ship_name']}")
            else:
                st.info("Live ping timed out. Holding onto the last known position from cache.")

# Use cached coordinates so the map never breaks
vessel_lat = st.session_state.vessel_cache['lat']
vessel_lon = st.session_state.vessel_cache['lon']
vessel_name_display = st.session_state.vessel_cache['ship_name']
current_speed = f"{st.session_state.vessel_cache.get('sog', '0')} knots"

# Dashboard Metrics Display
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(label="Calculated Delay", value=f"{scheduled_delay_hrs} Hours")

with col2:
    st.metric(
        label="London Gateway Omission Risk", 
        value=f"{diversion_prob}%",
        delta="HIGH RISK" if diversion_prob > 50 else "LOW RISK",
        delta_color="inverse"
    )

with col3:
    est_added_days = carrier_stats["barge_delay_days"] if diversion_prob > 50 else 0
    st.metric(label="Est. Added Supply Chain Delay", value=f"+{est_added_days} Days (Barge/Feeder)")

# Visual Status & Map Integration
st.subheader(f"Vessel Status: {vessel_name_display}")
st.text(f"Current Speed Over Ground: {current_speed}")

if diversion_prob > 50:
    st.error(f"⚠️ **High Probability of Diversion:** {carrier} historically skips London Gateway when delayed over {carrier_stats['delay_threshold']} hours.")
else:
    st.success("✅ **Normal Schedule Expected:** Delay is within operational buffer limits for London Gateway call.")

# Interactive Map Rendering
m = folium.Map(location=[51.2, 1.5], zoom_start=7)
folium.Marker([51.505, 0.465], popup="London Gateway", icon=folium.Icon(color="blue", icon="anchor")).add_to(m)
folium.Marker([51.95, 4.12], popup="Port of Rotterdam", icon=folium.Icon(color="green", icon="anchor")).add_to(m)
folium.Marker([vessel_lat, vessel_lon], popup=vessel_name_display, icon=folium.Icon(color="red", icon="ship")).add_to(m)

st_folium(m, width=900, height=400)


import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

# Page Configuration
st.set_page_config(page_title="Vessel Diversion Predictor", layout="wide")

st.title("🚢 Port-to-Port Vessel Tracker & Diversion Risk")
st.caption("Live ETA vs. Pro-Forma Schedule Delay Calculator")

# 1. Sidebar Inputs
st.sidebar.header("Vessel Query")
vessel_imo = st.sidebar.text_input("Vessel IMO Number", value="9839192") # Example MSC Vessel
carrier = st.sidebar.selectbox("Carrier", ["MSC", "Maersk", "CMA CGM", "Hapag-Lloyd"])
scheduled_delay_hrs = st.sidebar.number_input("Current Known Delay (Hours)", min_value=0, max_value=120, value=38)

# 2. Historical Baseline (Simulated CSV Lookup)
# In production, load this via: pd.read_csv('historical_routes.csv')
historical_data = {
    "MSC": {"delay_threshold": 36, "base_omission_rate": 0.65, "barge_delay_days": 3.5},
    "Maersk": {"delay_threshold": 24, "base_omission_rate": 0.35, "barge_delay_days": 2.0},
    "CMA CGM": {"delay_threshold": 30, "base_omission_rate": 0.50, "barge_delay_days": 3.0},
    "Hapag-Lloyd": {"delay_threshold": 28, "base_omission_rate": 0.40, "barge_delay_days": 2.5},
}

carrier_stats = historical_data.get(carrier)

# 3. Probability Calculation Engine
def calculate_risk(delay, stats):
    threshold = stats["delay_threshold"]
    base_rate = stats["base_omission_rate"]
    
    if delay < 12:
        return 5.0  # Very low risk of skipping port
    
    # Calculate scaled probability based on historical carrier behavior
    calculated_prob = min(95.0, (delay / threshold) * (base_rate * 100))
    return round(calculated_prob, 1)

diversion_prob = calculate_risk(scheduled_delay_hrs, carrier_stats)

# 4. Dashboard Metrics Display
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

# 5. Visual Status & Map Integration
st.subheader("Route Status & Vessel Location")

if diversion_prob > 50:
    st.error(f"⚠️ **High Probability of Diversion:** {carrier} is historically prone to skipping London Gateway when delayed over {carrier_stats['delay_threshold']} hours. Vessel is likely to sail directly to Rotterdam.")
else:
    st.success("✅ **Normal Schedule Expected:** Delay is within operational buffer limits for London Gateway call.")

# Interactive Map (Mock coordinates near English Channel)
vessel_lat, vessel_lon = 50.123, -0.456  # English Channel
m = folium.Map(location=[51.2, 1.5], zoom_start=7)

# Add Markers for Ports and Ship
folium.Marker([51.505, 0.465], popup="London Gateway", icon=folium.Icon(color="blue", icon="anchor")).add_to(m)
folium.Marker([51.95, 4.12], popup="Port of Rotterdam", icon=folium.Icon(color="green", icon="anchor")).add_to(m)
folium.Marker([vessel_lat, vessel_lon], popup=f"IMO: {vessel_imo} ({carrier})", icon=folium.Icon(color="red", icon="ship")).add_to(m)

st_folium(m, width=900, height=400)

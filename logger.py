import json
import websocket
import csv
import os
from datetime import datetime

# Replace with your free API key from aisstream.io
API_KEY = "YOUR_AISSTREAM_API_KEY_HERE"

# List of specific MMSI numbers you want to continuously track
TARGET_MMSIS = ["255805678", "9839192"] # Add your target container ships here

CSV_FILE = "vessel_history.csv"

def init_csv():
    """Ensure the CSV file exists with proper headers."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "mmsi", "ship_name", "latitude", "longitude", "speed_over_ground"])

def log_position(mmsi, ship_name, lat, lon, sog):
    """Append a new position record with a timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CSV_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, mmsi, ship_name, lat, lon, sog])
    print(f"[{timestamp}] Logged: {ship_name} (MMSI: {mmsi}) -> Lat: {lat}, Lon: {lon}, Speed: {sog} knots")

def on_open(ws):
    print("🔌 Background Logger connected to Aisstream.io. Listening for target vessels...")
    sub_msg = {
        "APIKey": API_KEY,
        "BoundingBoxes": [[[-90, -180], [90, 180]]], # Global scope
        "FiltersShipMMSI": TARGET_MMSIS,
        "FilterMessageTypes": ["PositionReport"]
    }
    ws.send(json.dumps(sub_msg))

def on_message(ws, message):
    try:
        data = json.loads(message)
        if data.get("MessageType") == "PositionReport":
            pos = data.get("Message", {}).get("PositionReport", {})
            meta = data.get("MetaData", {})
            
            mmsi = str(meta.get("MMSI"))
            ship_name = meta.get("ShipName", "Unknown").strip()
            lat = pos.get("Latitude")
            lon = pos.get("Longitude")
            sog = pos.get("SOG")
            
            # Log to CSV immediately upon receiving a ping
            log_position(mmsi, ship_name, lat, lon, sog)
            
    except Exception as e:
        print(f"Error parsing message: {e}")

def on_error(ws, error):
    print(f"❌ WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Connection closed. Attempting to reconnect in 5 seconds...")

if __name__ == "__main__":
    init_csv()
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://stream.aisstream.io/v0/stream",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever()
        except Exception as e:
            print(f"Connection dropped: {e}. Reconnecting...")

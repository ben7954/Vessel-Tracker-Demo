import json
import websocket
import csv
import os
from datetime import datetime
import time

# Replace with your free API key from aisstream.io
API_KEY = "59b1c83a8504a344ffb4b008fc007b761c00131a"

CSV_FILE = "vessel_historyv1.csv"
STATIC_CSV_FILE = "vessel_metadata.csv"

def init_csvs():
    """Ensure the CSV files exist with proper headers."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "mmsi", "ship_name", "latitude", "longitude", "speed_over_ground", "cog"])
            
    if not os.path.exists(STATIC_CSV_FILE):
        with open(STATIC_CSV_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["mmsi", "destination", "eta_month", "eta_day", "eta_hour", "eta_minute", "timestamp"])

def on_open(ws):
    print("🔌 Background Logger connected. Listening to ALL vessels in European corridor boxes...")
    sub_msg = {
        "APIKey": API_KEY,
        "BoundingBoxes": [
            [[35.5, -6.0], [37.2, -4.8]],    # Gibraltar / Southern Spain
            [[42.0, -10.0], [44.0, -8.0]],   # Cape Finisterre (Portugal/Spain approach)
            [[43.5, -5.5], [47.5, -1.0]],    # Bay of Biscay
            [[49.5, -5.0], [52.5, 5.0]]      # English Channel / LGW / Rotterdam
        ],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
    }
    ws.send(json.dumps(sub_msg))

def on_message(ws, message):
    try:
        data = json.loads(message)
        msg_type = data.get("MessageType")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta = data.get("MetaData", {})
        mmsi = str(meta.get("MMSI"))
        ship_name = meta.get("ShipName", "Unknown").strip()

        if msg_type == "PositionReport":
            pos = data.get("Message", {}).get("PositionReport", {})
            lat = pos.get("Latitude")
            lon = pos.get("Longitude")
            sog = pos.get("SOG", 0.0)
            cog = pos.get("COG", 0.0)

            # Handle missing or invalid AIS speed flags (1023 means speed not available)
            if sog is None or sog == 1023:
                sog = 0.0

            with open(CSV_FILE, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, mmsi, ship_name, lat, lon, sog, cog])
            
            # Updated print statement to explicitly show speed in the terminal
            print(f"[{timestamp}] Position Logged: {ship_name} (MMSI: {mmsi}) -> Lat: {lat}, Lon: {lon} | Speed: {sog} kn")

        elif msg_type == "ShipStaticData":
            static = data.get("Message", {}).get("ShipStaticData", {})
            destination = static.get("Destination", "Unknown").strip()
            eta = static.get("Eta", {})
            month = eta.get("Month", 0)
            day = eta.get("Day", 0)
            hour = eta.get("Hour", 24)
            minute = eta.get("Minute", 60)

            with open(STATIC_CSV_FILE, mode="a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([mmsi, destination, month, day, hour, minute, timestamp])
            print(f"[{timestamp}] Static Data Logged: {ship_name} (MMSI: {mmsi}) -> Destination: {destination}")

    except Exception as e:
        print(f"Error parsing message: {e}")

def on_error(ws, error):
    print(f"❌ WebSocket Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Connection closed. Attempting to reconnect in 5 seconds...")

if __name__ == "__main__":
    init_csvs()
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://stream.aisstream.io/v0/stream",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print(f"Connection dropped: {e}. Reconnecting...")
            time.sleep(5)

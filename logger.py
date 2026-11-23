import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
import websockets

API_KEY = os.getenv("AISSTREAM_API_KEY", "59b1c83a8504a344ffb4b008fc007b761c00131a")
TXT_LOG_FILE = "ais_pilot_log.txt"

# Bounding boxes: [min_lat, min_lon, max_lat, max_lon]
CORRIDORS = {
    "gibraltar": [[35.5, -6.5, 36.5, -4.5]],
    "finisterre": [[42.0, -10.5, 44.0, -8.0]],
    "bay_of_biscay": [[43.5, -8.0, 48.5, -1.0]],
    "english_channel": [[48.5, -5.5, 51.5, 2.0]],
}

ALL_BOUNDING_BOXES = [box for boxes in CORRIDORS.values() for box in boxes]


def identify_corridor(lat, lon):
    if lat is None or lon is None:
        return "unknown"
    for name, boxes in CORRIDORS.items():
        for min_lat, min_lon, max_lat, max_lon in boxes:
            if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                return name
    return "outside_corridor"


def append_txt_record(record: dict, filepath: str = TXT_LOG_FILE):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def listen_ais():
    if not API_KEY or API_KEY == "YOUR_AISSTREAM_API_KEY":
        print("[WARN] API_KEY is still set to the placeholder value.")
    else:
        print("[OK] API_KEY loaded.")

    subscribe_message = {
        "APIKey": API_KEY,
        "BoundingBoxes": ALL_BOUNDING_BOXES,
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }

    uri = "wss://stream.aisstream.io/v0/stream"
    backoff = 5.0
    max_backoff = 60.0
    total_logged = 0

    print(f"[START] Logging live AIS data to {TXT_LOG_FILE} (UTC). Press Ctrl+C to stop.")

    while True:
        connected_at = None
        session_msgs = 0
        try:
            print("[CONNECTING] Opening WebSocket connection to aisstream.io...")
            async with websockets.connect(
                uri,
                open_timeout=30,
                ping_interval=30,
                ping_timeout=30,
                close_timeout=10,
            ) as ws:
                connected_at = time.monotonic()
                print("[CONNECTED] WebSocket open. Sending corridor subscription...")
                await ws.send(json.dumps(subscribe_message))
                print("[SUBSCRIBED] Waiting for incoming AIS messages...")

                async for raw_msg in ws:
                    if isinstance(raw_msg, bytes):
                        raw_msg = raw_msg.decode("utf-8", errors="replace")

                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        print("[WARN] Skipped non-JSON message frame.")
                        continue

                    if "error" in msg:
                        print(f"[STREAM ERROR] {msg['error']}")

                    session_msgs += 1
                    if session_msgs == 1:
                        print("[STREAM LIVE] First message received from aisstream.io.")
                    if session_msgs == 1 or (time.monotonic() - connected_at >= 30):
                        backoff = 5.0

                    msg_type = msg.get("MessageType")
                    meta = msg.get("MetaData", {})
                    now_utc = datetime.now(timezone.utc).isoformat()

                    mmsi = str(meta.get("MMSI", "")).strip()
                    ship_name = (meta.get("ShipName") or "Unknown").strip()
                    lat = meta.get("latitude")
                    lon = meta.get("longitude")

                    if msg_type == "PositionReport":
                        pos = msg.get("Message", {}).get("PositionReport", {})
                        sog = pos.get("Sog")
                        cog = pos.get("Cog")
                        heading = pos.get("TrueHeading")
                        lat = pos.get("Latitude", lat)
                        lon = pos.get("Longitude", lon)
                        corridor = identify_corridor(lat, lon)

                        record = {
                            "logged_at_utc": now_utc,
                            "ais_time_utc": meta.get("time_utc"),
                            "message_type": "PositionReport",
                            "corridor": corridor,
                            "mmsi": mmsi,
                            "imo": meta.get("IMO"),
                            "ship_name": ship_name,
                            "latitude": lat,
                            "longitude": lon,
                            "speed_over_ground": sog,
                            "cog": cog,
                            "heading": heading,
                        }
                        append_txt_record(record)
                        total_logged += 1

                    elif msg_type == "ShipStaticData":
                        static = msg.get("Message", {}).get("ShipStaticData", {})
                        dest = (static.get("Destination") or "").strip()
                        eta = static.get("Eta", {})
                        corridor = identify_corridor(lat, lon)

                        record = {
                            "logged_at_utc": now_utc,
                            "ais_time_utc": meta.get("time_utc"),
                            "message_type": "ShipStaticData",
                            "corridor": corridor,
                            "mmsi": mmsi,
                            "imo": static.get("ImoNumber") or meta.get("IMO"),
                            "ship_name": (static.get("Name") or ship_name).strip(),
                            "callsign": (static.get("CallSign") or "").strip(),
                            "destination": dest if dest else "Unknown",
                            "eta_month": eta.get("Month"),
                            "eta_day": eta.get("Day"),
                            "eta_hour": eta.get("Hour"),
                            "eta_minute": eta.get("Minute"),
                            "draught": static.get("MaximumStaticDraught"),
                        }
                        append_txt_record(record)
                        total_logged += 1

                    if total_logged % 25 == 0 and total_logged > 0:
                        print(
                            f"[SAVED] {total_logged} total records written to {TXT_LOG_FILE} "
                            f"(latest: {ship_name} [{mmsi}] in {corridor})"
                        )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            duration = round(time.monotonic() - connected_at, 1) if connected_at else 0.0
            wait_time = round(backoff + random.uniform(0, 2.0), 1)
            print(
                f"[DISCONNECTED] After {duration}s ({session_msgs} msgs; {exc}). "
                f"Reconnecting in {wait_time}s..."
            )
            await asyncio.sleep(wait_time)
            backoff = min(backoff * 2, max_backoff)


def main():
    try:
        asyncio.run(listen_ais())
    except KeyboardInterrupt:
        print(f"\n[STOPPED] Session ended. Data saved in {TXT_LOG_FILE}.")


if __name__ == "__main__":
    main()

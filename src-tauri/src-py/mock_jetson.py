import time
import json
import urllib.request
from datetime import datetime, timezone

API_URL = "http://127.0.0.1:5001/api/v1/detection/ingest"

def send_mock_detection():
    payload = {
        "detection_id": f"DET-{int(time.time())}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "drone_id": "BENGAWAN-UAV-01",
        "reconstructed_location": {
            "latitude": -7.558412,
            "longitude": 110.856210,
            "estimated_margin_error_m": 1.2
        },
        "detection_data": {
            "class": "person",
            "count": 3,
            "confidence_avg": 0.89,
            "image_snapshot_url": "https://storage.local/snapshots/det_001.jpg"
        }
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(API_URL, data=data, headers={'Content-Type': 'application/json'})
    
    print(f"Sending mock detection payload to {API_URL}...")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                print("\nSuccess! AI Agent Orchestrator Response:")
                resp_body = response.read().decode('utf-8')
                print(json.dumps(json.loads(resp_body), indent=2))
            else:
                print(f"Error {response.status}: {response.reason}")
    except Exception as e:
        print(f"Connection failed: {e}. Is the Flask backend running?")

if __name__ == "__main__":
    print("Mock Jetson Simulator started.")
    send_mock_detection()

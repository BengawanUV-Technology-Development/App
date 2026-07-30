import os
import json
import urllib.request
import urllib.error
import ssl

def send_telegram_alert(ai_decision: dict, cv_payload: dict):
    """
    Sends an emergency alert to a Telegram Chat/Group based on the AI's decision.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("[TelegramDispatcher] Token or Chat ID not configured. Skipping alert.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Extract data safely
    level = ai_decision.get("priority_level", "UNKNOWN")
    score = ai_decision.get("priority_score", 0)
    action = ai_decision.get("suggested_action", "")
    justification = ai_decision.get("justification", "")
    
    # Format emoji based on level
    emoji = "🚨" if level == "CRITICAL" else "⚠️" if level == "HIGH" else "ℹ️"
    
    lat = cv_payload.get("reconstructed_location", {}).get("latitude", "Unknown")
    lng = cv_payload.get("reconstructed_location", {}).get("longitude", "Unknown")
    maps_link = f"https://www.google.com/maps?q={lat},{lng}" if lat != "Unknown" else "N/A"
    
    # Construct message
    message = (
        f"{emoji} *{level} SAR ALERT* {emoji}\n\n"
        f"*Target ID:* `{cv_payload.get('detection_id')}`\n"
        f"*Priority Score:* {score}/100\n\n"
        f"*Coordinates:* [{lat}, {lng}]({maps_link})\n\n"
        f"*AI Analysis:*\n_{justification}_\n\n"
        f"*Recommended Action:*\n{action}\n"
    )
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    # Bypass SSL Verification
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            if response.status == 200:
                print(f"[TelegramDispatcher] ✅ Successfully sent {level} alert to Telegram!")
                return True
    except urllib.error.URLError as e:
        print(f"[TelegramDispatcher] ❌ Error sending telegram message: {e}")
        return False

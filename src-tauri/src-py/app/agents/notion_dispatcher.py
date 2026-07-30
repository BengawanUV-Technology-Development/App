import os
import json
import urllib.request
import urllib.error
import ssl

def send_notion_task(ai_decision: dict, cv_payload: dict):
    """
    Creates a new entry in the Notion Operations Database based on the AI's decision.
    """
    token = os.getenv("NOTION_API_KEY")
    db_id = os.getenv("NOTION_DATABASE_ID")
    
    if not token or not db_id:
        print("[NotionDispatcher] Token or DB ID missing. Skipping Notion.")
        return False
        
    url = "https://api.notion.com/v1/pages"
    
    # Safely extract data
    target_id = cv_payload.get("detection_id", "Unknown ID")
    level = ai_decision.get("priority_level", "UNKNOWN")
    score = ai_decision.get("priority_score", 0)
    justification = ai_decision.get("justification", "")
    lat = cv_payload.get("reconstructed_location", {}).get("latitude", "Unknown")
    lng = cv_payload.get("reconstructed_location", {}).get("longitude", "Unknown")
    maps_link = f"https://www.google.com/maps?q={lat},{lng}" if lat != "Unknown" else None
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "Target ID": {
                "title": [{"text": {"content": target_id}}]
            },
            "Status": {
                "status": {"name": "Rescued"}
            },
            "Priority Level": {
                "select": {"name": level}
            },
            "Score": {
                "number": float(score)
            },
            "Notes": {
                "rich_text": [{"text": {"content": justification}}]
            }
        }
    }
    
    if maps_link:
        payload["properties"]["Coordinates"] = {
            "url": maps_link
        }
        
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers)
    
    # Bypass SSL Verification
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            if response.status == 200:
                print(f"[NotionDispatcher] ✅ Successfully created Notion task for {target_id}")
                return True
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        print(f"[NotionDispatcher] ❌ Error from Notion API: {e.code} {err_msg}")
        return False
    except urllib.error.URLError as e:
        print(f"[NotionDispatcher] ❌ Connection error to Notion API: {e}")
        return False

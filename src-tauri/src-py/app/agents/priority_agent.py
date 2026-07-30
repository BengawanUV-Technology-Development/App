import os
import json
from google import genai
from google.genai import types

def evaluate_detection(ingested_data: dict) -> dict:
    """
    Evaluates the ingested CV and telemetry data using Gemini to determine
    the priority score and recommended actions.
    """
    # Load API key dynamically
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        print("[PriorityAgent] GEMINI_API_KEY is not configured. Skipping AI evaluation.")
        return {"error": "API key not configured"}
        
    try:
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        You are the Autonomous AI Agent Orchestrator for the Bengawan UAV Search and Rescue (SAR) system.
        Analyze the following real-time data containing CV Object Detection and UAV Telemetry:
        
        {json.dumps(ingested_data, indent=2)}
        
        Based on this data, output a JSON response matching this schema precisely:
        {{
            "detection_id": "<the ID from the input>",
            "priority_score": <float from 0 to 100 based on urgency (e.g. battery, count)>,
            "priority_level": "<CRITICAL, HIGH, MEDIUM, or LOW>",
            "justification": "<Short explanation of why this score was given>",
            "suggested_action": "<Dispatch command or flight command recommendation>"
        }}
        
        Considerations:
        - If 'count' (number of people) is high, priority increases.
        - If drone battery is low (e.g., < 20%), suggest an RTL or relay flight.
        - If GPS hdop is bad (> 2.0) or valid=false, mark data as unreliable.
        """
        
        print("[PriorityAgent] Sending data to Gemini for evaluation...")
        
        # Use gemini-3.5-flash for sustained frontier performance
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            ),
        )
        
        # response.text may be Optional[str]; ensure it's not None before parsing
        resp_text = getattr(response, "text", None)
        if resp_text is None:
            print("[PriorityAgent] Empty response from Gemini")
            return {"error": "empty response from model"}

        try:
            assert response.text is not None
            raw_text = response.text.strip()
            # Bersihkan format markdown jika model menambahkannya
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            raw_text = raw_text.strip()
            
            # Ambil hanya dari { pertama sampai } terakhir
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1:
                raw_text = raw_text[start:end+1]
                
            result = json.loads(raw_text)
        except ValueError as ve:
            print(f"[PriorityAgent] Failed to parse JSON response: {ve}")
            return {"error": "invalid json from model", "raw": resp_text}
        print("\n" + "="*50)
        print("[PriorityAgent] 🧠 AI EVALUATION COMPLETE:")
        print(json.dumps(result, indent=2))
        print("="*50 + "\n")
        
        return result
        
    except Exception as e:
        print(f"[PriorityAgent] Error during evaluation: {e}")
        return {"error": str(e)}

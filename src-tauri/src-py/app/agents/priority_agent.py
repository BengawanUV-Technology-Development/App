import os
import json
import urllib.request
import urllib.error
import ssl
from pydantic import BaseModel, Field

class AIDecisionSchema(BaseModel):
    detection_id: str
    priority_score: float = Field(description="Float from 0 to 100 based on urgency")
    priority_level: str = Field(description="CRITICAL, HIGH, MEDIUM, or LOW")
    justification: str = Field(description="Short explanation of why this score was given")
    suggested_action: str = Field(description="Dispatch command or flight command recommendation")

def _evaluate_with_groq(prompt: str) -> str:
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key or groq_api_key == "your_groq_api_key_here" or not groq_api_key.startswith("gsk_"):
        raise ValueError(
            "GROQ_API_KEY belum diset atau masih menggunakan placeholder di .env! "
            "Dapatkan API key dari https://console.groq.com/ (diawali dengan 'gsk_') dan masukkan ke GROQ_API_KEY di file .env"
        )

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    url = "https://api.groq.com/openai/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are the Autonomous AI Agent Orchestrator for the Bengawan UAV Search and Rescue (SAR) system. Always respond with valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    print(f"[PriorityAgent] Sending data to Groq ({model}) for evaluation...")
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            if response.status == 200:
                res_body = response.read().decode('utf-8')
                parsed_res = json.loads(res_body)
                return parsed_res["choices"][0]["message"]["content"]
            else:
                raise RuntimeError(f"Groq API returned HTTP status {response.status}")
    except urllib.error.HTTPError as err:
        err_detail = err.read().decode('utf-8', errors='ignore')
        print(f"[PriorityAgent] ❌ Groq API HTTP Error {err.code}: {err_detail}")
        raise RuntimeError(f"Groq API HTTP Error {err.code}: {err_detail}")

def _evaluate_with_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError("GEMINI_API_KEY is not configured in .env")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    client = genai.Client(api_key=api_key)
    print(f"[PriorityAgent] Sending data to Gemini ({model}) for evaluation...")

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AIDecisionSchema,
            temperature=0.2
        ),
    )

    resp_text = getattr(response, "text", None)
    if resp_text is None:
        raise ValueError("Empty response from Gemini model")
    return resp_text

def evaluate_detection(ingested_data: dict) -> dict:
    """
    Evaluates the ingested CV and telemetry data using the configured AI Provider (Groq or Gemini).
    """
    from dotenv import load_dotenv
    load_dotenv(override=True)

    provider = os.getenv("AI_PROVIDER", "").lower()

    # Auto-detect provider if not explicitly specified
    if not provider:
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key and groq_key != "your_groq_api_key_here":
            provider = "groq"
        else:
            provider = "gemini"

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
    - Ensure all string values in JSON are single-line or properly escaped.
    """

    try:
        if provider == "groq":
            raw_text = _evaluate_with_groq(prompt)
        else:
            raw_text = _evaluate_with_gemini(prompt)

        raw_text = raw_text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        raw_text = raw_text.strip()
        start = raw_text.find('{')
        end = raw_text.rfind('}')
        if start != -1 and end != -1:
            raw_text = raw_text[start:end+1]

        try:
            result = json.loads(raw_text, strict=False)
        except ValueError:
            cleaned_text = raw_text.replace('\r\n', '\\n').replace('\n', '\\n')
            result = json.loads(cleaned_text, strict=False)

        print("\n" + "="*50)
        print(f"[PriorityAgent] 🧠 AI EVALUATION COMPLETE (Provider: {provider.upper()}):")
        print(json.dumps(result, indent=2))
        print("="*50 + "\n")

        return result

    except Exception as e:
        print(f"[PriorityAgent] Error during AI evaluation ({provider}): {e}")
        return {"error": str(e)}

import json
import os
import time
import requests
from dotenv import load_dotenv
import config

# ======================================================
# LOAD ENVIRONMENT
# ======================================================
load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "codestral-latest")
MISTRAL_ENDPOINT = "https://codestral.mistral.ai/v1/chat/completions"

if not MISTRAL_API_KEY:
    raise ValueError("❌ MISTRAL_API_KEY not found in .env file!")

# ======================================================
# LLM CALL (ROBUST + RETRY)
# ======================================================
def _call_llm(prompt: str, debug=False):
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MISTRAL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0
    }

    max_attempts = 3
    backoff = 2

    for attempt in range(1, max_attempts + 1):
        try:
            if debug:
                print(f"📤 Attempt {attempt}/{max_attempts} to LLM")

            response = requests.post(
                MISTRAL_ENDPOINT,
                headers=headers,
                json=payload,
                timeout=180
            )

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text[:300]}")

            result = response.json()
            if debug:
                usage = result.get("usage", {})
                print(f"✅ Success | Tokens used: {usage}")

            return result["choices"][0]["message"]["content"]

        except Exception as e:
            if debug:
                print(f"⚠️ Attempt {attempt} failed: {str(e)[:200]}")
            if attempt < max_attempts:
                time.sleep(backoff ** attempt)
            else:
                raise RuntimeError("❌ LLM request failed after retries")

# ======================================================
# KEYWORD FILTERING
# ======================================================
def extract_relevant_lines(text, max_lines=5000, debug=False):
    if not text:
        return ""

    lines = text.splitlines()
    relevant_indices = set()
    EXCLUDE_KEYWORDS = {
        "hydrogen fluoride", "sodium hydroxide", "emission", "limit",
        "concentration", "mg/nm3", "regulation", "decree", "permit",
        "compliance", "monitoring", "sampling", "standard", "requirement"
    }

    matched_count = 0
    excluded_count = 0

    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower:
            continue

        if any(excl in line_lower for excl in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue

        # Match ASSET_KEYWORDS OR common unit/industrial terms
        matched = False
        for keyword in config.ASSET_KEYWORDS:
            if keyword in line_lower:
                matched = True
                break

        # If line contains unit values like m3, l, kW, kWh, etc.
        units = ["m3", "l", "kw", "kva", "mwh", "kwh", "t/d", "t/day"]
        if any(u in line_lower for u in units):
            matched = True

        if matched:
            for j in range(i, min(i + 3, len(lines))):
                relevant_indices.add(j)
            matched_count += 1

    sorted_indices = sorted(relevant_indices)
    relevant_lines = [lines[i] for i in sorted_indices]
    result = "\n".join(relevant_lines[:max_lines])

    if debug:
        print("\n📊 FILTERING STATS")
        print(f"Total lines: {len(lines)}")
        print(f"Matched lines: {matched_count}")
        print(f"Excluded lines: {excluded_count}")
        print(f"Output lines: {len(sorted_indices)}")
        if len(text) > 0:
            compression = (len(result) / len(text)) * 100
            print(f"Compression ratio: {compression:.2f}%")

    return result

# ======================================================
# MAIN EXTRACTION PIPELINE
# ======================================================
def extract_assets_from_text(text, debug=False):
    if not text or not text.strip():
        return {"assets": []}

    if debug:
        print("\n" + "="*70)
        print("🚀 INDUSTRIAL ASSET EXTRACTION")
        print("="*70)

    relevant_text = extract_relevant_lines(text, debug=debug)
    if not relevant_text.strip():
        if debug:
            print("⚠️ No relevant content found")
        return {"assets": []}

    # Prompt: allow partial extraction, do not invent assets
    prompt = f"""
You are an Industrial Energy Auditor.

RULES:
1. DO NOT use outside knowledge.
2. DO NOT provide URLs, links, or image paths.
3. If no assets are found, return an empty list [].
4. If not asset_type found, do not include the entry.
5. Return ONLY valid JSON.

{{
  "assets": [
    {{
      "asset_type": "...",
      "capacity_value": "...",
      "capacity_unit": "...",
      "count_of_units": "..."
    }}
  ]
}}

TEXT:
{relevant_text}
"""

    try:
        raw_response = _call_llm(prompt, debug=debug)
        if not raw_response.strip():
            return {"assets": []}

        # Robust JSON parse: sometimes LLM adds whitespace/newlines
        raw_response = raw_response.strip()
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError:
            # try to find JSON object in text
            start = raw_response.find("{")
            end = raw_response.rfind("}") + 1
            if start != -1 and end != -1:
                data = json.loads(raw_response[start:end])
            else:
                if debug:
                    print("❌ Could not parse JSON from LLM response")
                return {"assets": []}

        assets = data.get("assets", [])
        if not isinstance(assets, list):
            assets = []

        # POST-VALIDATION: keep assets with allowed keywords OR unknown (don't discard unknown)
        ALLOWED_CORE_TERMS = {
            # Generation
            "generator", "genset", "turbine", "engine",
            "power plant", "cogeneration", "chp",
            "biomass plant", "steam unit",

            # Thermal
            "boiler", "furnace", "kiln", "oven",
            "incinerator", "incineration",

            # Electrical
            "transformer", "substation", "switchgear",
            "circuit breaker", "ups",

            # Storage
            "battery", "bess", "energy storage",

            # Mechanical
            "compressor", "pump", "motor", "fan",

            # Cooling
            "chiller", "cooling tower", "heat pump",

            # Tanks & Water
            "tank", "well",

            # Hydrogen / Gas
            "electrolyser", "reformer"
        }


        validated = []
        unknown = []
        for a in assets:
            if not isinstance(a, dict) or not a.get("asset_type"):
                continue
            asset_type = a["asset_type"].lower()
            if any(term in asset_type for term in ALLOWED_CORE_TERMS):
                validated.append(a)
            else:
                unknown.append(a)

        if debug and unknown:
            print("\n⚠️ Unknown asset types detected (kept for review):")
            for u in unknown:
                print(" -", u.get("asset_type"))
            validated += unknown  # keep unknown instead of discarding

        if debug:
            print(f"\n✅ Total assets extracted: {len(validated)}")

        return {"assets": validated}

    except Exception as e:
        if debug:
            print(f"❌ Extraction error: {e}")
        return {"assets": []}

# ======================================================
# DEBUG FUNCTION
# ======================================================
def debug_extract_relevant_lines(text):
    return extract_relevant_lines(text, debug=True)

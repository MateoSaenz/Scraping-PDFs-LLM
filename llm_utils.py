import json
import os
from ollama import Client
from dotenv import load_dotenv
import config
import time

# Load environment variables from .env file
load_dotenv()

# ======================================================
# LLM CLIENTS - LAZY INITIALIZATION FOR WORKERS
# ======================================================

# Get API key and models from environment
OLLAMA_API_KEY = os.getenv('OLLAMA_API_KEY')
CLOUD_MODEL = os.getenv('OLLAMA_CLOUD_MODEL', 'gpt-oss:120b')
LOCAL_MODEL = os.getenv('OLLAMA_LOCAL_MODEL', 'deepseek-r1:8b')
CLOUD_REQUEST_DELAY = float(os.getenv("CLOUD_REQUEST_DELAY", "0"))



if not OLLAMA_API_KEY:
    raise ValueError("❌ OLLAMA_API_KEY not found in .env file!")

# ✅ LAZY INITIALIZATION - clients created on demand
_cloud_client = None
_local_client = None

def get_cloud_client():
    """Get or create cloud client (safe for multiprocessing workers)"""
    global _cloud_client
    if _cloud_client is None:
        _cloud_client = Client(
            host="https://ollama.com",
            headers={
                "Authorization": f"Bearer {OLLAMA_API_KEY}"
            }
        )
        print("   🔧 Cloud client initialized")
    return _cloud_client

def get_local_client():
    """Get or create local client"""
    global _local_client
    if _local_client is None:
        _local_client = Client()
        print("   🔧 Local client initialized")
    return _local_client

# ======================================================
# INTERNAL LLM ROUTER (DO NOT EXPORT)
# ======================================================

def _call_llm(prompt: str, debug=False):
    """
    Try cloud LLM first (gpt-oss:120b) with retry logic.
    If it fails or hits rate limits, fallback to local (deepseek-r1:8b).
    
    Args:
        prompt: The extraction prompt
        debug: Enable verbose output
    
    Returns:
        LLM response dict
    """

    # --- Try cloud first (max 3 attempts) ---
    max_attempts = 3
    
    for attempt in range(1, max_attempts + 1):
        try:
            if debug:
                print(f"   📤 Cloud LLM attempt {attempt}/{max_attempts}: {CLOUD_MODEL}")

            if attempt == 1 and CLOUD_REQUEST_DELAY > 0:
            time.sleep(CLOUD_REQUEST_DELAY)
            
            cloud_client = get_cloud_client()
            
            response = cloud_client.chat(
                model=CLOUD_MODEL,
                format="json",
                messages=[{"role": "user", "content": prompt}],
                options={
                    "reasoning": "low"  # ✅ Force minimal thinking for faster extraction
                }
            )
            
            if debug:
                print(f"   ✅ Cloud LLM succeeded on attempt {attempt}")
            
            return response
            
        except Exception as e:
            error_msg = str(e)[:100]
            
            if debug:
                print(f"   ⚠️  Attempt {attempt} failed: {error_msg}")
            
            # Wait before retry (except on last attempt)
            if attempt < max_attempts:
                import time
                time.sleep(1)
                continue
            else:
                if debug:
                    print(f"   ❌ Cloud exhausted ({max_attempts} attempts)")
                break

    # --- Fallback to local ---
    if debug:
        print(f"   📦 Falling back to local model: {LOCAL_MODEL}")
    
    try:
        local_client = get_local_client()
        return local_client.chat(
            model=LOCAL_MODEL,
            format="json",
            messages=[{"role": "user", "content": prompt}],
            options={
                "reasoning": "low"  # ✅ Force minimal thinking for faster extraction
            }
        )
    except Exception as e:
        if debug:
            print(f"   ❌ Local model also failed: {str(e)[:100]}")
        raise

# ======================================================
# 1. SMART KEYWORD EXTRACTION (NO REGEX NOISE)
# ======================================================

def extract_relevant_lines(text, max_lines=5000, debug=False):
    """
    Extract ONLY lines with real asset keywords.
    Filters out regulatory noise automatically.
    
    Args:
        text: Raw document text
        max_lines: Maximum lines to return
        debug: Enable verbose output
    
    Returns:
        Filtered text with relevant lines only
    """

    lines = text.splitlines()
    relevant_indices = set()

    EXCLUDE_KEYWORDS = [
        "hydrogen fluoride", "sodium hydroxide", "emission", "limit",
        "concentration", "mg/nm3", "regulation", "decree", "permit",
        "compliance", "monitoring", "sampling", "standard", "requirement"
    ]

    excluded_count = 0
    matched_count = 0
    keyword_matches = {}

    for i, line in enumerate(lines):
        line_lower = line.lower()

        # Skip regulatory noise
        if any(excl in line_lower for excl in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue

        # Keep asset-related lines + context (current + next 2 lines)
        for keyword in config.ASSET_KEYWORDS:
            if keyword in line_lower:
                for j in range(i, min(i + 3, len(lines))):
                    relevant_indices.add(j)
                
                matched_count += 1
                if keyword not in keyword_matches:
                    keyword_matches[keyword] = 0
                keyword_matches[keyword] += 1
                break  # Count once per line

    if debug:
        print(f"\n📋 KEYWORD FILTERING STATS:")
        print(f"   - Total input lines: {len(lines)}")
        print(f"   - Excluded (regulatory): {excluded_count}")
        print(f"   - Matched with keywords: {matched_count}")
        print(f"   - Output lines (with context): {len(relevant_indices)}")
        
        if keyword_matches:
            print(f"   - Top 5 keywords found:")
            for kw, count in sorted(keyword_matches.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"      • {kw:30s} → {count:3d} occurrences")

    sorted_indices = sorted(relevant_indices)
    relevant = [lines[idx] for idx in sorted_indices]
    result = "\n".join(relevant[:max_lines])

    if debug:
        print(f"   - Final output: {len(result)} characters\n")

    return result

# ======================================================
# 2. DIRECT LLM EXTRACTION (PRODUCTION)
# ======================================================

def extract_assets_from_text(text, debug=False):
    """
    Extract industrial assets from text using LLM.
    
    Cloud-first with automatic local fallback.
    Safe for multiprocessing workers.
    
    Args:
        text: Raw document text to analyze
        debug: Enable verbose output for troubleshooting
    
    Returns:
        dict: {"assets": [{"asset_type": ..., "capacity_value": ..., ...}, ...]}
    """

    if not text or not text.strip():
        return {"assets": []}

    # Step 1: Filter text to relevant lines only
    if debug:
        print("\n" + "="*70)
        print("🚀 EXTRACTION PIPELINE")
        print("="*70)
        print("\nSTEP 1️⃣: FILTERING RELEVANT LINES")
    
    relevant = extract_relevant_lines(text, debug=debug)

    if not relevant.strip():
        if debug:
            print("⚠️  No relevant lines found - skipping LLM call")
        return {"assets": []}

    # Step 2: Build extraction prompt
    if debug:
        print("STEP 2️⃣: BUILDING PROMPT")
    
    prompt = f"""You are a strict Industrial Energy Auditor.
Your task: Extract physical assets from the provided TEXT only.

RULES:
1. DO NOT use outside knowledge.
2. DO NOT provide URLs, links, or image paths.
3. If no assets are found, return an empty list [].
4. If not asset_type found, do not include the entry.
5. Return ONLY valid JSON.

Fields:
- asset_type
- capacity_value
- capacity_unit
- count_of_units

TEXT:
{relevant}
"""

    if debug:
        print(f"   - Prompt size: {len(prompt)} characters")
        print(f"   - Input text size: {len(relevant)} characters")

    try:
        # Step 3: Call LLM with retry + fallback
        if debug:
            print("\nSTEP 3️⃣: CALLING LLM")
        
        response = _call_llm(prompt, debug=debug)
        raw_text = response["message"]["content"].strip()

        if debug:
            print(f"   - Response size: {len(raw_text)} characters")

        # Handle empty response
        if not raw_text or raw_text == "{}":
            if debug:
                print("⚠️  Empty LLM response")
            return {"assets": []}

        # Step 4: Parse JSON
        if debug:
            print("\nSTEP 4️⃣: PARSING JSON RESPONSE")
        
        data = json.loads(raw_text)

        if debug:
            print(f"   - Response type: {type(data).__name__}")
            if isinstance(data, dict):
                print(f"   - Keys: {list(data.keys())}")
            elif isinstance(data, list):
                print(f"   - Items: {len(data)}")

        # Normalize response (handle different formats)
        if isinstance(data, dict):
            if "assets" in data:
                assets = data["assets"]
                if debug:
                    print(f"   - Found 'assets' key with {len(assets)} items")
            elif "asset_type" in data:
                # Single asset object
                assets = [data]
                if debug:
                    print(f"   - Single asset detected, wrapping in list")
            else:
                assets = []
                if debug:
                    print(f"   - No 'assets' or 'asset_type' found")
        elif isinstance(data, list):
            assets = data
            if debug:
                print(f"   - Response is already a list: {len(assets)} items")
        else:
            assets = []
            if debug:
                print(f"   - Unexpected type: {type(data).__name__}")

        # Step 5: Validate assets
        if debug:
            print("\nSTEP 5️⃣: VALIDATING ASSETS")
        
        invalid_count = 0
        for idx, a in enumerate(assets):
            if not isinstance(a, dict):
                invalid_count += 1
                if debug and idx < 3:  # Show first 3 errors
                    print(f"   ⚠️  Item {idx}: Not a dict (type: {type(a).__name__})")
            elif not a.get("asset_type"):
                invalid_count += 1
                if debug and idx < 3:
                    print(f"   ⚠️  Item {idx}: Missing 'asset_type'")

        validated = [
            a for a in assets
            if isinstance(a, dict) and a.get("asset_type")
        ]

        if debug:
            print(f"   - Total items: {len(assets)}")
            print(f"   - Invalid: {invalid_count}")
            print(f"   - Valid: {len(validated)}")
            
            if validated:
                print(f"\n   ✅ EXTRACTED ASSETS:")
                for idx, asset in enumerate(validated[:5], 1):
                    asset_type = asset.get("asset_type", "N/A")
                    capacity = asset.get("capacity_value", "N/A")
                    unit = asset.get("capacity_unit", "N/A")
                    count = asset.get("count_of_units", "N/A")
                    print(f"      {idx}. {str(asset_type):30s} | {capacity:10s} {unit:10s} | Count: {count}")
                
                if len(validated) > 5:
                    print(f"      ... and {len(validated) - 5} more")

        if debug:
            print("\n" + "="*70 + "\n")

        return {"assets": validated}

    except json.JSONDecodeError as e:
        if debug:
            print(f"\n❌ JSON PARSE ERROR: {e}")
            print(f"   Raw response (first 200 chars): {raw_text[:200]}")
        return {"assets": []}
    
    except Exception as e:
        if debug:
            print(f"\n❌ EXTRACTION ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
        return {"assets": []}

# ======================================================
# 3. DEBUG FUNCTION
# ======================================================

def debug_extract_relevant_lines(text):
    """
    Debug version with comprehensive analysis.
    Use this to troubleshoot filtering issues.
    """

    lines = text.splitlines()
    relevant_indices = set()

    EXCLUDE_KEYWORDS = [
        "hydrogen fluoride", "sodium hydroxide", "emission", "limit",
        "concentration", "mg/nm3", "regulation", "decree", "permit",
        "compliance", "monitoring", "sampling", "standard", "requirement"
    ]

    keyword_matches = {}
    excluded_count = 0

    for i, line in enumerate(lines):
        line_lower = line.lower()

        if any(excl in line_lower for excl in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue

        for keyword in config.ASSET_KEYWORDS:
            if keyword in line_lower:
                relevant_indices.add(i)
                keyword_matches.setdefault(keyword, []).append((i + 1, line[:80]))
                if i + 1 < len(lines):
                    relevant_indices.add(i + 1)
                if i + 2 < len(lines):
                    relevant_indices.add(i + 2)
                break

    sorted_indices = sorted(relevant_indices)
    relevant = [f"[L.{idx+1:04d}] {lines[idx]}" for idx in sorted_indices]

    print("\n" + "="*70)
    print("🐛 DEBUG: KEYWORD EXTRACTION ANALYSIS")
    print("="*70)
    print(f"\n📊 INPUT STATISTICS:")
    print(f"   - Total lines: {len(lines)}")
    print(f"   - Total chars: {len(text)}")
    print(f"   - Excluded lines: {excluded_count}")
    
    print(f"\n🔍 KEYWORDS FOUND (top 10):")
    for kw, occurrences in sorted(keyword_matches.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        print(f"   • {kw:35s} → {len(occurrences):3d} occurrences")
        for line_num, preview in occurrences[:2]:
            print(f"      [L.{line_num:04d}] {preview}...")
    
    print(f"\n📄 OUTPUT STATISTICS:")
    print(f"   - Relevant lines: {len(sorted_indices)}")
    print(f"   - Output chars: {len(relevant)}")
    print(f"   - Compression: {len(relevant)/len(text)*100:.1f}% of original")
    print("="*70 + "\n")

    return "\n".join(relevant[:5000])

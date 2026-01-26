#================================================================
import re
import json
from ollama import Client
import config

client = Client()

# ======================================================
# 1. SMART KEYWORD EXTRACTION (NO REGEX NOISE)
# ======================================================
def extract_relevant_lines(text, max_lines=5000):
    """
    Extract ONLY lines with real asset keywords.
    NO regex pre-extraction - let LLM decide what's an asset.
    """
    print("\n" + "="*70)
    print("FUNCTION: extract_relevant_lines()")
    print("="*70)
    
    lines = text.splitlines()
    print(f"Total lines in text: {len(lines)}")
    print(f"Text length: {len(text)} characters")
    
    relevant_indices = set()
    
    EXCLUDE_KEYWORDS = [
        "hydrogen fluoride", "sodium hydroxide", "emission", "limit",
        "concentration", "mg/nm3", "regulation", "decree", "permit",
        "compliance", "monitoring", "sampling", "standard", "requirement"
    ]
    
    print(f"Exclude keywords: {len(EXCLUDE_KEYWORDS)} patterns")
    print(f"Asset keywords to search: {len(config.ASSET_KEYWORDS)} patterns\n")

    excluded_count = 0
    matched_count = 0
    keyword_matches = {}

    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # SKIP regulatory noise
        if any(excl in line_lower for excl in EXCLUDE_KEYWORDS):
            excluded_count += 1
            continue
        
        # ONLY include if asset keyword present
        for keyword in config.ASSET_KEYWORDS:
            if keyword in line_lower:
                # Grab context: this line + next 2 lines
                for j in range(i, min(i + 3, len(lines))):
                    relevant_indices.add(j)
                
                matched_count += 1
                if keyword not in keyword_matches:
                    keyword_matches[keyword] = 0
                keyword_matches[keyword] += 1
                break  # Don't count same line twice

    print(f"Lines excluded (regulatory/noise): {excluded_count}")
    print(f"Lines matched with asset keywords: {matched_count}")
    print(f"Unique context lines extracted: {len(relevant_indices)}\n")
    
    # Show top keywords found
    if keyword_matches:
        print("Top 10 keywords found:")
        for kw, count in sorted(keyword_matches.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   • {kw:30s} → {count:3d} occurrences")
        print()

    sorted_indices = sorted(relevant_indices)
    relevant = [lines[idx] for idx in sorted_indices]
    result = "\n".join(relevant[:max_lines])
    
    print(f"Final extracted text length: {len(result)} characters")
    print(f"Lines in output: {len(relevant)}")
    print(f"Capped at max_lines: {max_lines}")
    print("="*70 + "\n")
    
    return result

# ======================================================
# 2. DIRECT LLM EXTRACTION (NO REGEX PREPROCESSING)
# ======================================================
def extract_assets_from_text(text, debug=False):
    """
    Extract assets directly with the proven prompt.
    NO regex pre-extraction step.
    """
    print("\n" + "="*70)
    print("FUNCTION: extract_assets_from_text()")
    print("="*70)
    print(f"Timestamp: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Debug mode: {debug}\n")
    
    # Step 1: Filter relevant lines
    print("STEP 1️: Extracting relevant lines...")
    relevant = extract_relevant_lines(text)
    
    if debug:
        print(f"Relevant text extracted: {len(relevant)} chars")
    
    if not relevant.strip():
        print("No relevant lines found - returning empty assets")
        print("="*70 + "\n")
        return {"assets": []}

    print("STEP 2️: Preparing LLM prompt...")
    
    # Step 2: Direct LLM call with YOUR PROVEN PROMPT
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
    
    print(f"Prompt length: {len(prompt)} characters")
    print(f"Prompt preview (first 200 chars):\n{prompt[:200]}...\n")

    try:
        print("STEP 3️: Sending request to Ollama LLM...")
        print(f"Model: {config.OLLAMA_MODEL}")
        print(f"Input text length: {len(relevant)} chars")
        
        import time
        start_time = time.time()
        
        response = client.chat(
            model=config.OLLAMA_MODEL,
            format="json",
            messages=[{"role": "user", "content": prompt}]
        )
        
        elapsed_time = time.time() - start_time
        print(f"⏱LLM processing time: {elapsed_time:.2f} seconds")
        
        raw_text = response["message"]["content"].strip()
        
        print(f"\nSTEP 4️: Processing LLM response...")
        print(f"Response length: {len(raw_text)} characters")
        print(f"Response preview (first 300 chars):\n{raw_text[:300]}\n")
        
        # Handle empty response
        if not raw_text or raw_text == "{}":
            print("LLM returned empty response: '{}'")
            print("="*70 + "\n")
            return {"assets": []}
        
        # Parse JSON
        print("Parsing JSON response...")
        data = json.loads(raw_text)
        print(f"JSON parsed successfully")
        print(f"Root type: {type(data).__name__}")
        
        # Normalize response format
        print("\nNormalizing response format...")
        if isinstance(data, dict):
            print(f"   - Response is dict with keys: {list(data.keys())}")
            if "assets" in data:
                assets = data.get("assets", [])
                print(f"   - Found 'assets' key with {len(assets)} items")
            else:
                # Single asset object - wrap it
                if "asset_type" in data:
                    assets = [data]
                    print(f"   - Single asset detected, wrapping in list")
                else:
                    assets = []
                    print(f"   - No 'asset_type' found, returning empty")
        elif isinstance(data, list):
            assets = data
            print(f"   - Response is list with {len(assets)} items")
        else:
            assets = []
            print(f"   - Response is {type(data).__name__}, cannot process")
        
        # Validate: only keep items with asset_type
        print("\nValidating assets...")
        print(f"Total items to validate: {len(assets)}")
        
        invalid_count = 0
        for idx, a in enumerate(assets):
            if not isinstance(a, dict):
                print(f"Item {idx}: Not a dict (type: {type(a).__name__})")
                invalid_count += 1
            elif not a.get("asset_type"):
                print(f" Item {idx}: Missing 'asset_type'")
                invalid_count += 1
        
        validated = [
            a for a in assets 
            if isinstance(a, dict) and a.get("asset_type")
        ]
        
        print(f"Invalid items removed: {invalid_count}")
        print(f"Valid assets extracted: {len(validated)}")
        
        if validated:
            print("\n🎯 Extracted Assets:")
            for idx, asset in enumerate(validated, 1):
                asset_type = asset.get("asset_type", "N/A")
                capacity = asset.get("capacity_value", "N/A")
                unit = asset.get("capacity_unit", "N/A")
                count = asset.get("count_of_units", "N/A")
                print(f"   {idx}. {asset_type:30s} | {capacity:10s} {unit:10s} | Count: {count}")
        
        print("\n" + "="*70 + "\n")
        return {"assets": validated}
        
    except json.JSONDecodeError as e:
        print(f"\nJSON PARSING ERROR")
        print(f" Error: {e}")
        print(f"   Raw response (first 500 chars):\n{raw_text[:500]}")
        print("="*70 + "\n")
        return {"assets": []}
    except Exception as e:
        print(f"\n UNEXPECTED ERROR")
        print(f"   Error type: {type(e).__name__}")
        print(f"   Error message: {e}")
        import traceback
        print(f"   Traceback:\n{traceback.format_exc()}")
        print("="*70 + "\n")
        return {"assets": []}


# ======================================================
# 3. DEBUG FUNCTION (VERBOSE OUTPUT)
# ======================================================
def debug_extract_relevant_lines(text):
    """DEBUG version with extra logging"""
    print("\n" + "="*70)
    print(" DEBUG FUNCTION: debug_extract_relevant_lines()")
    print("="*70 + "\n")
    
    lines = text.splitlines()
    relevant_indices = set()
    
    EXCLUDE_KEYWORDS = [
        "hydrogen fluoride", "sodium hydroxide", "emission", "limit", 
        "concentration", "mg/nm3", "regulation", "decree", "permit",
        "compliance", "monitoring", "sampling", "standard", "requirement"
    ]
    
    print(f" -> Input Statistics:")
    print(f"   - Total lines: {len(lines)}")
    print(f"   - Total characters: {len(text)}")
    print(f"   - Average line length: {len(text)//len(lines) if lines else 0} chars")
    print(f"   - Exclude patterns: {len(EXCLUDE_KEYWORDS)}")
    print(f"   - Asset keywords: {len(config.ASSET_KEYWORDS)}\n")
    
    excluded_count = 0
    keyword_matches = {}
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Check if excluded
        is_excluded = False
        for excl in EXCLUDE_KEYWORDS:
            if excl in line_lower:
                excluded_count += 1
                is_excluded = True
                break
        
        if is_excluded:
            continue
        
        # Check if included
        for keyword in config.ASSET_KEYWORDS:
            if keyword in line_lower:
                relevant_indices.add(i)
                
                if keyword not in keyword_matches:
                    keyword_matches[keyword] = []
                keyword_matches[keyword].append((i+1, line[:70]))
                
                # Grab next 2 lines for context
                if i + 1 < len(lines):
                    relevant_indices.add(i + 1)
                if i + 2 < len(lines):
                    relevant_indices.add(i + 2)
                break
    
    sorted_indices = sorted(list(relevant_indices))
    
    print(f"Processing Results:")
    print(f"   - Lines excluded (regulatory): {excluded_count}")
    print(f"   - Lines matched with keywords: {len(keyword_matches)}")
    print(f"   - Total relevant lines (with context): {len(sorted_indices)}\n")
    
    if keyword_matches:
        print(f"Keywords Found (top 15):")
        for kw, occurrences in sorted(keyword_matches.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
            print(f"   • {kw:35s} → {len(occurrences):3d} occurrences")
            for line_num, preview in occurrences[:2]:  # Show first 2 occurrences
                print(f"      [L.{line_num:04d}] {preview}...")
        print()
    
    relevant = [f"[L.{idx+1:04d}] {lines[idx]}" for idx in sorted_indices]
    result = "\n".join(relevant[:5000])
    
    print(f" Output Statistics:")
    print(f"   - Output length: {len(result)} characters")
    print(f"   - Output lines: {len(relevant)}")
    print(f"   - Compression ratio: {len(result)/len(text)*100:.1f}% of original")
    print("\n" + "="*70 + "\n")
    
    return result
import pandas as pd
import geopandas as gpd
import fiona
import requests
import os
import json  
from bs4 import BeautifulSoup
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import config
import worker_utils
import llm_utils

def get_pdf_links(url):
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        return list(set([a["href"] for a in soup.select("div.jumbotron a[href]") if a.get_text(strip=True).lower().endswith(".pdf")]))
    except:
        return []

def main():
    print("\n" + "="*70)
    print("🚀 PIPELINE WITH FULL RESUME & CHECKPOINT LOGIC")
    print("="*70 + "\n")
    
    # =====================================================
    # STEP 1: Load Data
    # =====================================================
    print("📂 Step 1: Loading Data...")
    layers = fiona.listlayers(config.GPKG_FILE)
    gdf = gpd.read_file(config.GPKG_FILE, layer=layers[0])
    
    gdf = gdf.head(2) 
    print(f"   ✅ TEST MODE: Processing {len(gdf)} sites\n")
    

    # Initialize txt_link column
    gdf["txt_link"] = None

    # =====================================================
    # STEP 2: Scrape PDF Links
    # =====================================================
    print("🔗 Step 2: Scraping PDF Links...")
    gdf["pdf_links"] = gdf["url_fiche"].apply(get_pdf_links)
    gdf = gdf.explode("pdf_links").dropna(subset=["pdf_links"])
    print(f"   ✅ Found {len(gdf)} PDF links\n")
    
    # =====================================================
    # STEP 3: Download PDFs (WITH CHECKPOINT)
    # =====================================================
    print("📥 Step 3: Downloading PDFs...")
    print(f"   📁 Destination: {config.PDF_DIR}\n")
    
    def download_pdf(row):
        suffix = str(row['pdf_links'])[-5:].replace('/', '_')
        filename = f"{row['id']}_{row['nummer']}_{suffix}.pdf"
        path = config.PDF_DIR / filename
        
        # ✅ CHECKPOINT: Skip if already downloaded
        if path.exists():
            print(f"      ⏭️  Already exists: {filename}")
            return str(path)
        
        try:
            r = requests.get(row['pdf_links'], timeout=30)
            with open(path, "wb") as f:
                f.write(r.content)
            print(f"      ✅ Downloaded: {filename}")
        except Exception as e:
            print(f"      ❌ Failed: {filename} ({e})")
        
        return str(path)
    
    gdf['pdf_path'] = gdf.apply(download_pdf, axis=1)
    print(f"   ✅ All PDFs ready\n")
    
    # =====================================================
    # STEP 4: PDF → TXT Conversion (WITH CHECKPOINT)
    # =====================================================
    print("🔄 Step 4: Converting PDF to TXT...")
    print(f"   📁 Source: {config.PDF_DIR}")
    print(f"   📁 Destination: {config.TXT_DIR}\n")
    
    items = [{"idx": i, "pdf_path": row["pdf_path"]} for i, row in gdf.iterrows()]
    
    # ⚠️ NEW: Track which files need processing
    items_to_process = []
    for item in items:
        pdf_name = os.path.basename(item["pdf_path"])
        txt_name = pdf_name.replace(".pdf", ".txt")
        txt_path = config.TXT_DIR / txt_name
        
        # ✅ CHECKPOINT: Skip if TXT already exists
        if txt_path.exists():
            print(f"   ⏭️  Already converted: {txt_name}")
            idx = item["idx"]
            gdf.at[idx, "txt_link"] = str(txt_path)
        else:
            items_to_process.append(item)
    
    print(f"   📊 To process: {len(items_to_process)} | Skipping: {len(items) - len(items_to_process)}\n")
    
    # Process only new files
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(worker_utils.process_document_task, it, str(config.PDF_DIR), str(config.TXT_DIR), config.SHAREPOINT_BASE_URL) 
            for it in items_to_process
        ]
        
        for future in tqdm(as_completed(futures), total=len(futures), desc="   "):
            try:
                idx, txt_link = future.result()
                if idx is not None:
                    gdf.at[idx, "txt_link"] = txt_link
                    print(f"   ✅ Converted: {os.path.basename(txt_link)}")
            except Exception as e:
                print(f" Error: {e}")
    
    print(f"\n  PDF→TXT complete\n")
    
    

    # =====================================================
    # STEP 5: TXT → LLM Asset Extraction (WITH CHECKPOINT)
    # =====================================================
    print("🤖 Step 5: LLM Asset Extraction...")
    print(f"   📁 Source: {config.TXT_DIR}")
    print(f"   📁 Destination: {config.JSON_DIR}\n")

    # ✅ SIMPLE: Just scan TXT_DIR directly
    txt_files = list(config.TXT_DIR.glob("*.txt"))
    print(f"   📊 Found {len(txt_files)} TXT files\n")
    
    llm_processed = 0
    llm_skipped = 0

    for txt_path in tqdm(txt_files, desc="   "):
        base_name = txt_path.stem  # filename WITHOUT .txt
        json_path = config.JSON_DIR / f"{base_name}.json"
        
        # ✅ CHECKPOINT: Skip if JSON already exists
        if json_path.exists():
            print(f"      ⏭️  Already processed: {base_name}.json")
            llm_skipped += 1
            continue
        
        # Process TXT → JSON
        try:
            with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            
            # Call LLM
            llm_data = llm_utils.extract_assets_from_text(text, debug=False)
            
            # Save JSON checkpoint
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "source": base_name,
                        "assets": llm_data.get("assets", [])
                    },
                    f,
                    indent=2
                )
            
            asset_count = len(llm_data.get("assets", []))
            if asset_count > 0:
                llm_processed += 1
                print(f"      ✅ {base_name}.json ({asset_count} assets)")
            else:
                llm_skipped += 1
                print(f"      ⚠️  {base_name}.json (no assets)")
                
        except Exception as e:
            print(f"      ❌ {base_name}: {str(e)[:50]}")
            # Save empty JSON to avoid reprocessing
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"source": base_name, "assets": []}, f, indent=2)
            llm_skipped += 1

    print(f"\n   📊 Processed: {llm_processed} | Skipped: {llm_skipped}\n")



    # =====================================================
    # STEP 6: Flatten & Export to Excel (WITH APPEND MODE)
    # =====================================================
    print("📊 Step 6: Flattening to Excel...")
    print(f"   📁 Destination: {config.FINAL_EXCEL}\n")
    
    final_rows = []
    json_count = 0
    
    for idx, row in gdf.iterrows():
        if pd.isna(row.get("txt_link")):
            continue
            
        base_name = os.path.splitext(os.path.basename(row["txt_link"]))[0]
        json_path = config.JSON_DIR / f"{base_name}.json"
        
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    stored_data = json.load(f)
                    assets = stored_data.get("assets", [])
                    json_count += 1
                    
                    if assets:
                        for asset in assets:
                            combined = row.to_dict()
                            combined.update(asset)
                            final_rows.append(combined)
                    else:
                        # Include row even if no assets
                        combined = row.to_dict()
                        combined["asset_type"] = "NO_ASSETS"
                        final_rows.append(combined)
            except Exception as e:
                print(f"   ⚠️  Error reading {json_path}: {e}")
    
    # Export to Excel
    if final_rows:
        df_final = pd.DataFrame(final_rows)
        df_final.to_excel(config.FINAL_EXCEL, index=False)
        print(f"   ✅ Exported {len(final_rows)} rows from {json_count} JSON files")
        print(f"   📁 Saved to: {config.FINAL_EXCEL}")
    else:
        print(f"   ⚠️  No assets found")
    
    print("\n" + "="*70)
    print("✅ PIPELINE COMPLETE - All data saved locally with resume capability")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
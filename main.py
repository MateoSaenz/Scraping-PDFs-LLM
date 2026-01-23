import pandas as pd
import geopandas as gpd
import fiona
import requests
import os
import json  
from bs4 import BeautifulSoup
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

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
    print("Step 1: Loading Data...")
    layers = fiona.listlayers(config.GPKG_FILE)
    gdf = gpd.read_file(config.GPKG_FILE, layer=layers[0])

    # --- ADD THIS LINE FOR TESTING ---
    gdf = gdf.head(2) 
    print(f"TEST MODE: Processing only {len(gdf)} sites.")
    # ---------------------------------

    print("Step 2: Scraping URLs...")
    gdf["pdf_links"] = gdf["url_fiche"].apply(get_pdf_links)
    gdf = gdf.explode("pdf_links").dropna(subset=["pdf_links"])

    print("Step 3: Downloading...")
    def download_pdf(row):
        suffix = str(row['pdf_links'])[-5:].replace('/', '_')
        filename = f"{row['id']}_{row['nummer']}_{suffix}.pdf"
        path = config.PDF_DIR / filename
        if not path.exists():
            try:
                r = requests.get(row['pdf_links'], timeout=30)
                with open(path, "wb") as f: f.write(r.content)
            except: pass
        return str(path)
    gdf['pdf_path'] = gdf.apply(download_pdf, axis=1)

    print("⚙️ Step 4: Parallel Extraction & Translation...")
    items = [{"idx": i, "pdf_path": row["pdf_path"]} for i, row in gdf.iterrows()]
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker_utils.process_document_task, it, str(config.PDF_DIR), str(config.TXT_DIR), config.SHAREPOINT_BASE_URL) for it in items]
        for future in tqdm(as_completed(futures), total=len(futures)):
            idx, txt_link = future.result()
            if idx is not None:
                gdf.at[idx, "txt_link"] = txt_link

    # 🧠 Step 5: LLM Asset Extraction with JSON Checkpoint
    print("🧠 Running LLM Asset Extraction...")
    
    for idx, row in tqdm(gdf.iterrows(), total=len(gdf)):
        if pd.isna(row["txt_link"]): continue
        
        # Determine filenames
        base_name = os.path.splitext(os.path.basename(row["txt_link"]))[0]
        json_path = config.JSON_DIR / f"{base_name}.json"
        txt_path = config.TXT_DIR / f"{base_name}.txt"

        # 1. Skip if JSON already exists (Resume logic)
        if json_path.exists():
            continue

        # 2. Process with LLM if TXT exists
        if txt_path.exists():
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read()
            
            relevant = llm_utils.extract_relevant_lines(text)
            if relevant:
                llm_data = llm_utils.extract_assets_with_llm(relevant)
                
                # Save the raw JSON result for audit/checkpoint
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump({"source": base_name, "assets": llm_data.get("assets", [])}, f, indent=2)

    # 📊 Step 6: Final Flattening (The "Explode" logic)
    print("📊 Flattening JSON results to Excel...")
    final_rows = []
    
    for idx, row in gdf.iterrows():
        base_name = os.path.splitext(os.path.basename(str(row["txt_link"])))[0]
        json_path = config.JSON_DIR / f"{base_name}.json"
        
        if json_path.exists():
            with open(json_path, "r") as f:
                stored_data = json.load(f)
                assets = stored_data.get("assets", [])
                
                for asset in assets:
                    combined = row.to_dict()
                    combined.update(asset)
                    final_rows.append(combined)

    pd.DataFrame(final_rows).to_excel(config.FINAL_EXCEL, index=False)

if __name__ == "__main__":
    main()
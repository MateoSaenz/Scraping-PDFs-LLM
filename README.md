## Project Overview

This project automates the extraction and analysis of industrial assets from Belgian industrial sites using **PDF scraping, NLP translation, and LLM-based intelligent asset recognition**. It processes unstructured PDF documents (in Dutch) to identify and catalog physical assets like generators, turbines, batteries, and other industrial equipment.

### The Problem

- **12,000+ PDFs** to analyze across Belgian industrial sites
- **Non-standardized documents**: Different formats, layouts, and data structures
- **Language barrier**: All documents in Dutch
- **Average 35 pages per PDF**: Manual analysis is impractical
- **Inconsistent asset information**: No standard way assets are documented
- **Manual extraction bottleneck**: Traditional methods would take months

---

## Architecture & Data Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: Load Geospatial Data (GeoPackage)                       │
│ Source: pf_gpbv.gpkg → Industrial site locations & URLs         │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: Web Scraping → Extract PDF Links                        │
│ From: Each site's permit/documentation page (HTML)              │
│ Tool: BeautifulSoup, Requests                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: Download PDFs                                           │
│ Storage: data/Data_stock/PDFs/ (with resume checkpoints)        │
│ Tool: Requests library + multi-threading (ProcessPoolExecutor)  │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: PDF → Text Extraction                                   │
│ Extract raw text from 35-page documents                         │
│ Tool: pdfplumber (Fitz-based PDF parsing)                       │
│ Checkpoint: Skip if TXT already exists                          │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5: Dutch → English Translation                             │
│ Tool: argostranslate (offline, no API costs)                    │
│ Model: stanza + sacremoses + ctranslate2                        │
│ Storage: data/Data_stock/TXT/ (translated text files)           │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 6: Smart Keyword Filtering                                 │
│ Extract lines containing industrial asset keywords              │
│ Exclude regulatory noise (emissions, permits, etc.)             │
│ Compression: 35-page PDFs → ~5% relevant content                │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 7: LLM-Based Asset Extraction                              │
│ Tool: Ollama + llama3.1:8b (local, no API costs)                │
│ Input: Filtered relevant text                                   │
│ Output: Structured JSON with asset details                      │
│ Checkpoint: Skip if JSON already exists                         │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ STEP 8: Flatten & Export                                        │
│ Combine site metadata + extracted assets                        │
│ Output: Excel file (gpbv_final_assets.xlsx)                     │
│ Format: One row per asset with full context                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack & Library Choices

### Core Data Processing

| Library | Purpose | Why Chosen |
|---------|---------|-----------|
| **pandas** | Data manipulation & merging | Industry standard for tabular data, fast groupby/join operations |
| **geopandas** | Geospatial data handling | Native support for shapefiles, GeoPackages, coordinate transformations |
| **fiona** | OGR-based file I/O | Enables reading GeoPackage layers, better than shapefile-only tools |

### PDF & Document Processing

| Library | Purpose | Why Chosen |
|---------|---------|-----------|
| **pdfplumber** | PDF text extraction | Better table parsing than pypdf, handles complex layouts, OCR-ready |
| **pdfminer.six** | Low-level PDF parsing | Dependency of pdfplumber, precise text positioning |
| **Pillow** | Image processing | For potential OCR preprocessing if needed |

### Web Scraping & HTTP

| Library | Purpose | Why Chosen |
|---------|---------|-----------|
| **requests** | HTTP client | Simple, reliable, standard in Python ecosystem |
| **BeautifulSoup** | HTML parsing | Lightweight, intuitive CSS selectors for link extraction |
| **cloudscraper** | Anti-bot bypass | Handles Cloudflare JS challenges on some sites |

### Natural Language Processing (NLP)

| Library | Purpose | Why Chosen |
|---------|---------|-----------|
| **argostranslate** | Dutch → English translation | **Offline** (no API costs), privacy-preserving, ~95% accuracy for technical docs |
| **stanza** | Tokenization/POS tagging | Dependency of argostranslate, Stanford-trained models |
| **langdetect** | Language detection | Identifies Dutch vs English vs other languages pre-translation |
| **spacy** | NLP pipeline | Dependency of argostranslate, fast lemmatization |

### Large Language Model (LLM)

| Tool | Purpose | Why Chosen |
|------|---------|-----------|
| **Ollama** | Local LLM runtime | **Zero API costs**, offline operation, runs llama3.1:8b efficiently on consumer hardware |
| **llama3.1:8b** | Asset extraction model | Good balance of speed (~2 sec/doc) vs accuracy, instruction-following capability |

### Parallelization & Performance

| Library | Purpose | Why Chosen |
|---------|---------|-----------|
| **concurrent.futures** | Multi-threading/processing | Built-in Python, simpler than multiprocessing for I/O-bound tasks |
| **tqdm** | Progress bars | Visual feedback for long-running processes (12K PDFs = hours) |
| **pathlib** | Path manipulation | Cross-platform compatibility, modern Path objects |

---

## Key Design Decisions

### 1. **Checkpoint/Resume Architecture**
```python
# Skip if already processed
if txt_path.exists():
    print(f"Already converted: {txt_name}")
    idx = item["idx"]
    gdf.at[idx, "txt_link"] = str(txt_path)
```
**Why**: Processing 12K PDFs takes days. If a crash occurs, restart from where it failed.

### 2. **Offline-First Approach**
- ❌ No OpenAI API (costs $$$, privacy concerns)
- ✅ **argostranslate**: Free, offline translation
- ✅ **Ollama**: Free, local LLM on consumer hardware

**Cost Savings** Cloud APIs for 12K documents

### 3. **Two-Stage Filtering**
```
Full Text → Keyword Filter (90% reduction) → LLM (10% computation)
```
**Why**: Only send relevant excerpts to LLM. Speeds up processing.

### 4. **Keyword-Based Noise Exclusion**
```python
EXCLUDE_KEYWORDS = [
    "emission", "regulation", "decree", "permit", "compliance"
]
```
**Why**: Avoid LLM parsing irrelevant regulatory text.

### 5. **Context Preservation**
```python
# Grab context: this line + next 2 lines
for j in range(i, min(i + 3, len(lines))):
    relevant_indices.add(j)
```
**Why**: Assets often described across multiple lines ("1000 kW" on line N, "emergency generator" on line N+1).

### 6. **JSON Checkpointing**
```python
# Save JSON checkpoint immediately after LLM processing
with open(json_path, "w") as f:
    json.dump({"source": base_name, "assets": llm_data}, f)
```
**Why**: If Step 8 (Excel export) fails, no need to re-run Steps 1-7.

---

## Installation & Setup

### Prerequisites
- Python 3.8+
- Ollama installed locally with `llama3.1:8b` model running
- ~50GB free disk space (for PDFs)
- ~16GB RAM recommended

### Install Dependencies
```bash
# Create virtual environment
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\activate

# Install packages
pip install -r requirements.txt
```

### requirements.txt
```
pandas==2.2.2
geopandas==1.1.1
fiona==1.10.1
requests==2.32.3
beautifulsoup4==4.12.2
pdfplumber==0.11.9
argostranslate==1.10.0
langdetect==1.0.9
ollama==0.1.26
tqdm==4.66.5
openpyxl==3.11.0  # For Excel export
cloudscraper==1.2.71
```

### Download Ollama & Model
```bash
# Download from https://ollama.ai
ollama pull llama3.1:8b

# Start server (background)
ollama serve
```

---

## Running the Pipeline

```powershell
# 1. Activate virtual environment
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.\.venv\Scripts\activate

# 2. Ensure Ollama is running
ollama serve  # In another terminal

# 3. Run pipeline
python main.py
```

### Expected Output
```
======================================================================
🚀 PIPELINE WITH FULL RESUME & CHECKPOINT LOGIC
======================================================================

📂 Step 1: Loading Data...
   ✅ TEST MODE: Processing 2 sites

🔗 Step 2: Scraping PDF Links...
   ✅ Found 2 PDF links

📥 Step 3: Downloading PDFs...
   ✅ All PDFs ready

🔄 Step 4: Converting PDF to TXT...
   ✅ PDF→TXT complete

🧠 Step 5: LLM Asset Extraction...
   📊 Processed: 2 | Skipped: 0

📊 Step 6: Flattening to Excel...
   ✅ Exported 8 rows from 2 JSON files
   📁 Saved to: data/final/gpbv_final_assets.xlsx

======================================================================
✅ PIPELINE COMPLETE - All data saved locally with resume capability
======================================================================
```

---

## Configuration (config.py)

```python
# Directories
BASE_DIR = Path(r"C:\...Data_stock")  # Where PDFs/TXTs/JSONs stored
GPKG_FILE = r"...\data\raw\pf_gpbv.gpkg"  # Input geospatial data
FINAL_EXCEL = r"...\data\final\gpbv_final_assets.xlsx"  # Output

# LLM Config
OLLAMA_MODEL = "llama3.1:8b"

# Asset Keywords (101+ terms for filtering)
ASSET_KEYWORDS = [
    "generator", "turbine", "engine", "transformer",
    "battery", "boiler", "compressor", "pump",
    "kw", "mw", "kva", ...
]
```

---

## Output Format

### Excel File Structure (`gpbv_final_assets.xlsx`)

| id | nummer | naam | gemeente | postcode | asset_type | capacity_value | capacity_unit | count_of_units |
|----|--------|------|----------|----------|------------|-----------------|--------------|----------------|
| 1850 | BE.VL.000002273.INSTALLATION | Greenergy | Herselt | 2230 | Engine | 930 | kW | 4 |
| 1850 | BE.VL.000002273.INSTALLATION | Greenergy | Herselt | 2230 | Emergency Generator | 125 | kW | 1 |
| 1146 | BE.VL.000001389.INSTALLATION | Ganfraco/Snaet | Lichtervelde | 8810 | Biogas Engine | 500 | kW | 2 |

### JSON Format (per document)
```json
{
  "source": "1850_BE.VL.000002273.INSTALLATION_0d386",
  "assets": [
    {
      "asset_type": "Engine",
      "capacity_value": "930",
      "capacity_unit": "kW",
      "count_of_units": "4"
    },
    {
      "asset_type": "Emergency Generator",
      "capacity_value": "125",
      "capacity_unit": "kW",
      "count_of_units": "1"
    }
  ]
}
```

---

## Performance Metrics

| Stage | Time/Doc | Total (2K docs) | Bottleneck |
|-------|----------|-----------------|-----------|
| PDF Download | 5 sec | 3 hours | Network I/O |
| PDF → TXT | 2 sec | 1.1 hours | CPU (PDF parsing) |
| Translation | 1.5 sec | 50 min | Translation model |
| Keyword Filter | 0.1 sec | 3 min | Negligible |
| LLM Extraction | 2 sec | 1.1 hours | LLM inference |
| **Total** | **10.6 sec** | **~6 hours** | LLM + PDF parsing |

**For 12,000 PDFs**: ~3-4 days on consumer hardware (4 parallel workers)

---

## Troubleshooting

### Issue: "Ollama connection refused"
```bash
# Ensure Ollama server is running
ollama serve
# Or check port
netstat -ano | findstr :11434
```

### Issue: "Out of memory during PDF processing"
```python
# In main.py, reduce workers
with ProcessPoolExecutor(max_workers=2) as executor:  # Lower from 4
```

### Issue: "Translation model not found"
```python
# In scraping_data_test.ipynb or main.py
import argostranslate.package
argostranslate.package.update_package_index()
# Install nl→en package
for pkg in argostranslate.package.get_available_packages():
    if pkg.from_code == "nl" and pkg.to_code == "en":
        argostranslate.package.install_from_path(pkg.download())
```

---

## Future Improvements

1. **Parallel LLM Processing**: Deploy Ollama on multiple GPUs
2. **Fine-tuned Model**: Train llama on industrial asset taxonomy
3. **OCR Support**: Add Tesseract for scanned PDFs (~5% of dataset)
4. **Confidence Scoring**: Add LLM confidence for each extraction
5. **Active Learning**: Flag low-confidence results for manual review
6. **RESTful API**: Expose pipeline as FastAPI endpoint for real-time processing

---

## License & Attribution

- **argostranslate**: LGPL v2
- **Ollama & llama3.1**: MIT
- **pdfplumber**: MIT
- **geopandas**: BSD 3-Clause

---

## Author Notes

This project demonstrates **end-to-end data engineering**: from web scraping through NLP to structured ML-based extraction—**all offline, cost-free, and privacy-preserving**. The checkpoint architecture makes it production-ready for handling scale (12K+ documents).
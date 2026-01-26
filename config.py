import os
from pathlib import Path

# --- DIRECTORIES ---
# in this folder is where we will store PDFs, TXTs, JSONs
BASE_DIR = Path(r"C:\Users\m.saenzortiz\OneDrive - ENERGY POOL\Documents\PROJET Assets analysis BEL\Data_stock")

DATA_DIR = Path(r"C:\Users\m.saenzortiz\OneDrive - ENERGY POOL\Documents\PROJET Assets analysis BEL\Scraping-PDFs-LLM\data\raw")
PDF_DIR = BASE_DIR / "PDFs"
TXT_DIR = BASE_DIR / "TXT"
JSON_DIR = BASE_DIR / "JSON"  

# --- FILES ---
GPKG_FILE = DATA_DIR / "pf_gpbv.gpkg"
FINAL_EXCEL = Path(r"C:\Users\m.saenzortiz\OneDrive - ENERGY POOL\Documents\PROJET Assets analysis BEL\Scraping-PDFs-LLM\data\final\gpbv_final_assets.xlsx")

# --- CONFIG ---
OLLAMA_MODEL = "llama3.1:8b"
SHAREPOINT_BASE_URL = "local_storage://" 

# Ensure folders exist
for folder in [PDF_DIR, TXT_DIR, JSON_DIR, DATA_DIR]:
    os.makedirs(folder, exist_ok=True)


# --- KEYWORDS ---

ASSET_KEYWORDS = [
    # Power Generation
    "furnace","generator", "genset", "diesel generator", "gas generator",
    "emergency generator", "backup generator",
    "turbine", "gas turbine", "steam turbine",
    "engine", "internal combustion engine", "furnace", "combustion engine",

    
    # Electrical
    "transformer", "power transformer", "distribution transformer",
    "substation", "switchgear", "circuit breaker",
    "electrical panel", "electrical installation", "kva", "kva", "kw",
    
    # Energy Storage
    "battery", "batteries","battery system", "battery storage",
    "energy storage", "bess", "ups", "uninterruptible power supply",
    
    # Power Units
    "kw", "mw", "kva", "mva", "kwh", "mwh", "vah",
    
    # Thermal
    "boiler", "steam boiler", "hot water boiler",
    "heater", "furnace", "kiln", "burner", "oven",
    "glass furnace", "melting furnace",
    
    # Cooling/HVAC
    "chiller", "cooling system", "cooling unit", "cooling tower",
    "heat pump", "hvac", "air conditioning",
    
    # Gases/Fuel
    "hydrogen", "h2", "electrolyser", "electrolyzer", "reformer",
    "natural gas", "gas installation", "nm3/h", "m3/h", "diesel",
    "fuel oil", "light fuel oil", "heavy fuel oil",
    
    # Mechanical
    "compressor", "air compressor", "pump", "industrial pump",
    "motor", "electric motor", "fan",
    
    # Storage
    "tank", "storage tank", "well", "groundwater", "water well",
    "storage capacity", "storage volume", "container",
    
    # Grid/Demand
    "load shedding", "peak shaving",
    "demand response", "flexibility",
    "energy management", "ems",
    
    # General Power Terms
    "capacity", "rated power", "nominal power", "maximum power",
    "installed power", "thermal input", "rated thermal",
    "production capacity", "tonnes per day", "tonnes/day",
    "litres", "m3", "nm3",
]

import os
import pdfplumber
from langdetect import detect
import argostranslate.translate

_TRANSLATOR_CACHE = {}

def get_cached_translator(from_code, to_code="en"):
    cache_key = f"{from_code}_{to_code}"
    if cache_key not in _TRANSLATOR_CACHE:
        _TRANSLATOR_CACHE[cache_key] = argostranslate.translate.get_translation_from_codes(from_code, to_code)
    return _TRANSLATOR_CACHE[cache_key]

def process_document_task(item, pdf_base_dir, output_dir, sharepoint_base_url):
    try:
        idx = item['idx']
        pdf_path = item["pdf_path"]
        pdf_filename = os.path.basename(pdf_path)
        full_pdf_path = os.path.join(pdf_base_dir, pdf_filename)
        
        base_name = os.path.splitext(pdf_filename)[0]
        output_filename = f"{base_name}.txt"
        output_path = os.path.join(output_dir, output_filename)
        
        if os.path.exists(output_path):
            return idx, sharepoint_base_url + output_filename

        if not os.path.exists(full_pdf_path):
            return None, f"Missing: {pdf_filename}"

        text_content = []
        with pdfplumber.open(full_pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if page_text:
                    text_content.append(page_text)
        
        original_text = "\n".join(text_content)
        if not original_text.strip():
            return None, f"Empty PDF: {pdf_filename}"

        try:
            lang = detect(original_text[:2000])
        except:
            lang = "unknown"

        if lang in {"fr", "nl", "de"}:
            translator = get_cached_translator(lang, "en")
            chunks = [original_text[i:i+3000] for i in range(0, len(original_text), 3000)]
            translated = [translator.translate(c) for c in chunks]
            final_text = "".join(translated)
        else:
            final_text = original_text

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_text)

        return idx, sharepoint_base_url + output_filename
    except Exception as e:
        return None, str(e)
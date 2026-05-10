#!/usr/bin/env python3
"""
Enrich existing catalog.json with duration + languages from each product page.
Run: python enrich_catalog.py
Time: ~6-8 min (parallel)
"""

import json
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import chromadb
from chromadb.utils import embedding_functions

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.shl.com/",
}

def extract_detail(item: dict, session: requests.Session) -> dict:
    """Fetch product page and extract duration, languages, test_types."""
    try:
        r = session.get(item["url"], timeout=10, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        full_text = soup.get_text(separator=" ", strip=True)

        # ── Duration ──
        duration = ""
        dur_patterns = [
            r"(\d+)\s*minutes?",
            r"Approximately\s+(\d+)\s*min",
            r"takes\s+(\d+)\s*min",
            r"(\d+)\s*-\s*(\d+)\s*minutes?",  # range
        ]
        for pat in dur_patterns:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                if m.lastindex == 2:
                    duration = f"{m.group(1)}-{m.group(2)} minutes"
                else:
                    duration = f"{m.group(1)} minutes"
                break

        # ── Languages ──
        languages = []
        lang_keywords = [
            "English International", "English (USA)", "English (UK)",
            "French", "French (Canada)", "German", "Spanish",
            "Latin American Spanish", "Portuguese", "Portuguese (Brazil)",
            "Dutch", "Italian", "Swedish", "Norwegian", "Danish", "Finnish",
            "Russian", "Polish", "Czech", "Slovak", "Hungarian", "Romanian",
            "Turkish", "Arabic", "Hebrew", "Japanese", "Korean",
            "Chinese Simplified", "Chinese Traditional", "Thai", "Indonesian",
            "Greek", "Serbian", "Bulgarian", "Croatian", "Slovenian",
            "Ukrainian", "Lithuanian", "Latvian", "Estonian",
            "Hindi", "Malay", "Vietnamese", "Filipino",
        ]
        for lang in lang_keywords:
            if lang in full_text:
                languages.append(lang)

        # ── Test types (multi-letter like P,C or B,S) ──
        # Look for type key table on detail page
        test_types = item.get("test_types", [])
        
        # SHL detail pages often have a "Keys" section
        # Look for single uppercase letters in structured table cells
        tables = soup.find_all("table")
        for table in tables:
            cells = table.find_all("td")
            for cell in cells:
                txt = cell.get_text(strip=True)
                # Single letters separated by commas like "P, C" or "B, S"
                if re.fullmatch(r"[A-Z](,\s*[A-Z])*", txt):
                    types = [t.strip() for t in txt.split(",")]
                    if all(t in "ABCDEFGKLMNPQS" for t in types):
                        test_types = types
                        break

        # ── Better test_type from page content ──
        if not test_types or test_types == ["A"]:
            type_signals = {
                "P": ["personality", "opq", "behaviour", "behavioral", "papi"],
                "B": ["motivation", "biodata", "mq "],
                "S": ["situational judgment", "situational judgement", "sjt"],
                "K": ["knowledge", "coding", "java", "python", "sql", "javascript",
                      "excel", "technical skills", "spoken english", "svar",
                      "typing", "data entry", "microsoft", "css", "html",
                      "cloud", "devops", "agile", "salesforce"],
                "M": ["simulation", "call simulation", "contact center sim"],
                "D": ["360", "development", "feedback report"],
                "E": ["exercise", "in-tray", "inbox"],
                "C": ["competency", "ucf", "competencies"],
            }
            found_types = []
            combined = (item["name"] + " " + item.get("description", "")).lower()
            for code, signals in type_signals.items():
                if any(s in combined for s in signals):
                    found_types.append(code)
            if found_types:
                test_types = found_types

        item["duration"] = duration
        item["languages"] = languages[:15]  # cap at 15 for display
        item["test_types"] = test_types
        item["test_type"] = test_types[0] if test_types else item.get("test_type", "A")

    except Exception as e:
        item.setdefault("duration", "")
        item.setdefault("languages", [])

    return item


def rebuild_chroma(catalog: list[dict]):
    print(f"\nRebuilding Chroma with {len(catalog)} enriched items...")
    client = chromadb.PersistentClient(path="./chroma_db")
    try:
        client.delete_collection("shl_assessments")
    except:
        pass

    ef = embedding_functions.DefaultEmbeddingFunction()
    collection = client.create_collection(
        "shl_assessments",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    docs, ids, metas = [], [], []
    for i, item in enumerate(catalog):
        langs_str = ", ".join(item.get("languages", []))
        doc = (
            f"Name: {item['name']}. "
            f"Type: {', '.join(item.get('test_types', [item.get('test_type','A')]))}. "
            f"Duration: {item.get('duration', '')}. "
            f"Description: {item.get('description', '')}. "
            f"Job levels: {', '.join(item.get('job_levels', []))}. "
            f"Languages: {langs_str}."
        )
        docs.append(doc)
        ids.append(f"assessment_{i}")
        metas.append({
            "name": item["name"],
            "url": item["url"],
            "test_type": item.get("test_type", "A"),
            "test_types": ", ".join(item.get("test_types", [])),
            "duration": item.get("duration", ""),
            "languages": langs_str[:300],
            "remote_testing": str(item.get("remote_testing", True)),
            "adaptive_irt": str(item.get("adaptive_irt", False)),
            "description": item.get("description", "")[:300],
            "job_levels": ", ".join(item.get("job_levels", [])),
        })

    BATCH = 50
    for start in range(0, len(docs), BATCH):
        collection.add(
            documents=docs[start:start+BATCH],
            ids=ids[start:start+BATCH],
            metadatas=metas[start:start+BATCH],
        )
    print(f"✓ Chroma rebuilt with {len(docs)} documents.")


if __name__ == "__main__":
    with open("catalog.json") as f:
        catalog = json.load(f)

    print(f"Enriching {len(catalog)} items with duration + languages (12 workers)...")

    session = requests.Session()
    session.headers.update(HEADERS)

    enriched = [None] * len(catalog)
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(extract_detail, item.copy(), session): i
                   for i, item in enumerate(catalog)}
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            try:
                enriched[idx] = future.result()
            except Exception:
                enriched[idx] = catalog[idx]
            done += 1
            if done % 30 == 0 or done == len(catalog):
                # Sample check
                sample = enriched[idx]
                if sample:
                    print(f"  [{done}/{len(catalog)}] {sample['name']} | dur={sample.get('duration','?')} | langs={len(sample.get('languages',[]))}")

    enriched = [e for e in enriched if e]

    # Save
    with open("catalog.json", "w") as f:
        json.dump(enriched, f, indent=2)
    print(f"\n✓ Saved {len(enriched)} enriched assessments")

    # Verify sample
    print("\nSample item:")
    print(json.dumps(enriched[5], indent=2))

    # Rebuild Chroma
    rebuild_chroma(enriched)

    print("\n✅ DONE. Now update agent.py system prompt to include duration+languages in recs.")
    print("Then: git add catalog.json chroma_db/ && git commit -m 'enrich catalog' && git push")
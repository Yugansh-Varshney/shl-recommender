#!/usr/bin/env python3
"""
CATALOG FIXER — Run this to replace the 31-item fallback with full SHL catalog.
Strategy: 
  1. Hit SHL's paginated catalog (requests + BS4, no browser needed for listing)
  2. Enrich details with fast parallel requests (10 workers, 8s timeout each)
  3. Save catalog.json + rebuild Chroma

Run: python build_catalog.py
Time: ~5-8 minutes
"""

import requests
import json
import os
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import chromadb
from chromadb.utils import embedding_functions

BASE = "https://www.shl.com"
CATALOG_PAGE = "https://www.shl.com/solutions/products/product-catalog/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.shl.com/",
}

# ── Known SHL catalog URL patterns ──
# SHL catalog uses ?start=N&type=1 for Individual Test Solutions
# type=1 = Individual, type=2 = Pre-packaged (we skip type=2)

def fetch_listing_page(start: int, session: requests.Session) -> list[dict]:
    """Fetch one page of the catalog listing."""
    url = f"{CATALOG_PAGE}?start={start}&type=1"
    try:
        r = session.get(url, timeout=15, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        
        items = []
        # SHL catalog table rows
        table = soup.find("table", class_=lambda c: c and "custom" in c.lower() if c else False)
        if not table:
            # Try any table with product links
            tables = soup.find_all("table")
            for t in tables:
                if t.find("a", href=lambda h: h and "/product-catalog/view/" in h):
                    table = t
                    break
        
        if not table:
            # Fallback: find all product links directly
            links = soup.find_all("a", href=lambda h: h and "/product-catalog/view/" in h)
            for link in links:
                href = link.get("href", "")
                name = link.get_text(strip=True)
                if name and href:
                    full_url = BASE + href if not href.startswith("http") else href
                    items.append({
                        "name": name,
                        "url": full_url,
                        "test_type": "A",
                        "test_types": [],
                        "remote_testing": True,
                        "adaptive_irt": False,
                        "description": "",
                        "job_levels": [],
                    })
            return items
        
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]
        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue
            
            link = cells[0].find("a")
            if not link:
                continue
            
            name = link.get_text(strip=True)
            href = link.get("href", "")
            if not name or not href:
                continue
            full_url = BASE + href if not href.startswith("http") else href
            
            # Remote testing = cell 1 has img
            remote = bool(cells[1].find("img")) if len(cells) > 1 else False
            # Adaptive IRT = cell 2 has img  
            adaptive = bool(cells[2].find("img")) if len(cells) > 2 else False
            
            # Test type letters from remaining cells
            test_types = []
            for cell in cells[3:]:
                txt = cell.get_text(strip=True)
                if txt and len(txt) <= 2 and txt.isalpha() and txt.isupper():
                    test_types.append(txt)
                # Also check for img with alt text
                img = cell.find("img")
                if img:
                    alt = img.get("alt", "").strip()
                    if alt and len(alt) <= 2 and alt.isalpha():
                        test_types.append(alt)
            
            items.append({
                "name": name,
                "url": full_url,
                "test_type": test_types[0] if test_types else guess_type(name),
                "test_types": test_types,
                "remote_testing": remote,
                "adaptive_irt": adaptive,
                "description": "",
                "job_levels": [],
            })
        
        return items
    except Exception as e:
        print(f"  Listing error at start={start}: {e}")
        return []


def guess_type(name: str) -> str:
    """Guess test type from name."""
    n = name.lower()
    if any(x in n for x in ["personality", "opq", "papi", "behavior", "behaviour"]):
        return "P"
    if any(x in n for x in ["motivation", "mq", "biodata"]):
        return "B"
    if any(x in n for x in ["situational", "sjt", "judgment", "judgement"]):
        return "S"
    if any(x in n for x in ["simulation", "contact center", "call center"]):
        return "M"
    if any(x in n for x in ["360", "development", "feedback"]):
        return "D"
    if any(x in n for x in ["exercise", "in-tray", "inbox"]):
        return "E"
    if any(x in n for x in [
        "java", "python", "sql", "javascript", "coding", "c++", "php",
        "excel", "word", "powerpoint", "cobol", "cloud", "engineering",
        "accounting", "finance", "typing", "data entry", "technical",
        "ms office", "microsoft", "css", "html", "r programming",
        "machine learning", "devops", "agile", "salesforce", "sap"
    ]):
        return "K"
    # Default to cognitive/ability
    return "A"


def enrich_item(item: dict, session: requests.Session) -> dict:
    """Fetch detail page and extract description + job levels."""
    try:
        r = session.get(item["url"], timeout=8, headers=HEADERS)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        
        # Description: try multiple selectors
        desc = ""
        for sel in [
            {"class_": lambda c: c and "description" in c.lower() if c else False},
            {"class_": lambda c: c and "rich-text" in c.lower() if c else False},
            {"class_": lambda c: c and "product-detail" in c.lower() if c else False},
        ]:
            divs = soup.find_all("div", **sel)
            for d in divs:
                t = d.get_text(separator=" ", strip=True)
                if len(t) > 80:
                    desc = t[:500]
                    break
            if desc:
                break
        
        # Fallback: first substantial paragraph in main content
        if not desc:
            main = soup.find("main") or soup.find("article") or soup
            for p in main.find_all("p"):
                t = p.get_text(strip=True)
                if len(t) > 80:
                    desc = t[:500]
                    break
        
        # Job levels
        level_keywords = [
            "Entry-Level", "Graduate", "Manager", "Director",
            "Executive", "Mid-Professional", "Supervisor",
            "Professional Individual Contributor", "General Population",
            "Front Line Manager"
        ]
        page_text = soup.get_text()
        job_levels = [kw for kw in level_keywords if kw in page_text]
        
        # Better test type from page if not already set
        if not item["test_types"]:
            type_map = {
                "Ability": "A", "Cognitive": "A", "Reasoning": "A",
                "Numerical": "A", "Verbal": "A", "Inductive": "A",
                "Deductive": "A", "Spatial": "A", "Mechanical": "A",
                "Personality": "P", "OPQ": "P",
                "Motivation": "B", "MQ": "B",
                "Situational Judgment": "S",
                "Knowledge": "K", "Skills": "K", "Coding": "K",
                "Simulation": "M",
                "360": "D", "Development": "D",
                "Exercise": "E",
            }
            for keyword, code in type_map.items():
                if keyword.lower() in page_text.lower():
                    item["test_type"] = code
                    item["test_types"] = [code]
                    break

        item["description"] = desc
        item["job_levels"] = job_levels
    except Exception as e:
        pass  # keep item with empty description
    return item


def scrape_all_listings(session: requests.Session) -> list[dict]:
    """Paginate through all catalog listings."""
    print("Phase 1: Collecting all assessment URLs...")
    all_items = []
    seen_urls = set()
    start = 0
    step = 12
    empty_streak = 0

    while True:
        items = fetch_listing_page(start, session)
        new = [i for i in items if i["url"] not in seen_urls]
        
        if not new:
            empty_streak += 1
            if empty_streak >= 3:
                print(f"  No more pages. Total collected: {len(all_items)}")
                break
        else:
            empty_streak = 0
            all_items.extend(new)
            for i in new:
                seen_urls.add(i["url"])
            print(f"  start={start}: +{len(new)} items (total={len(all_items)})")
        
        start += step
        time.sleep(0.3)  # polite delay
    
    return all_items


def enrich_parallel(items: list[dict], session: requests.Session, workers: int = 12) -> list[dict]:
    """Enrich all items in parallel."""
    print(f"\nPhase 2: Enriching {len(items)} items with {workers} workers...")
    enriched = [None] * len(items)
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_item, item.copy(), session): i 
                   for i, item in enumerate(items)}
        
        done = 0
        for future in as_completed(futures):
            idx = futures[future]
            try:
                enriched[idx] = future.result()
            except Exception:
                enriched[idx] = items[idx]
            done += 1
            if done % 20 == 0 or done == len(items):
                print(f"  Enriched {done}/{len(items)}...")
    
    return [e for e in enriched if e is not None]


def rebuild_chroma(catalog: list[dict]):
    """Rebuild Chroma vector store from catalog."""
    print(f"\nPhase 3: Rebuilding Chroma with {len(catalog)} items...")
    
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
        doc = (
            f"Name: {item['name']}. "
            f"Type: {item.get('test_type', 'A')}. "
            f"Description: {item.get('description', '')}. "
            f"Job levels: {', '.join(item.get('job_levels', []))}."
        )
        docs.append(doc)
        ids.append(f"assessment_{i}")
        metas.append({
            "name": item["name"],
            "url": item["url"],
            "test_type": item.get("test_type", "A"),
            "remote_testing": str(item.get("remote_testing", True)),
            "adaptive_irt": str(item.get("adaptive_irt", False)),
            "description": item.get("description", "")[:200],
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
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # Phase 1: collect URLs
    items = scrape_all_listings(session)
    
    if len(items) < 50:
        print(f"WARNING: Only got {len(items)} items from listing. SHL may be blocking.")
        print("Loading existing catalog.json to enrich instead...")
        if os.path.exists("catalog.json"):
            with open("catalog.json") as f:
                items = json.load(f)
    
    # Phase 2: enrich in parallel (fast)
    enriched = enrich_parallel(items, session, workers=12)
    
    # Save
    with open("catalog.json", "w") as f:
        json.dump(enriched, f, indent=2)
    print(f"✓ Saved {len(enriched)} assessments to catalog.json")
    
    # Phase 3: rebuild Chroma
    rebuild_chroma(enriched)
    
    # Quick test
    print("\nQuick retrieval test...")
    from retriever import retrieve
    results = retrieve("Java developer", n=3)
    for r in results:
        print(f"  - {r['name']} ({r['test_type']})")
    
    print("\n✅ CATALOG REBUILD COMPLETE")
    print(f"   Items: {len(enriched)}")
    print("   Now restart server: python main.py")
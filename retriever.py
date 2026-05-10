import json
import chromadb
from chromadb.utils import embedding_functions

_client = None
_collection = None

def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path="./chroma_db")
        ef = embedding_functions.DefaultEmbeddingFunction()
        _collection = _client.get_collection("shl_assessments", embedding_function=ef)
    return _collection

def retrieve(query: str, n: int = 10) -> list[dict]:
    """Semantic search over SHL catalog. Returns top-n assessments."""
    col = get_collection()
    results = col.query(query_texts=[query], n_results=min(n, col.count()))
    
    assessments = []
    for i, meta in enumerate(results["metadatas"][0]):
        assessments.append({
            "name": meta["name"],
            "url": meta["url"],
            "test_type": meta["test_type"],
            "remote_testing": meta.get("remote_testing") == "True",
            "adaptive_irt": meta.get("adaptive_irt") == "True",
            "description": meta.get("description", ""),
            "job_levels": meta.get("job_levels", ""),
            "duration": meta.get("duration", ""),
            "languages": meta.get("languages", ""),
            "score": float(results["distances"][0][i]),
        })
    return assessments

def get_by_names(names: list[str]) -> list[dict]:
    """Retrieve specific assessments by name for comparison."""
    with open("catalog.json") as f:
        catalog = json.load(f)
    
    results = []
    for name in names:
        name_lower = name.lower()
        for item in catalog:
            if name_lower in item["name"].lower() or item["name"].lower() in name_lower:
                results.append(item)
                break
    return results

def get_all_names() -> list[str]:
    """Return all assessment names from catalog."""
    with open("catalog.json") as f:
        catalog = json.load(f)
    return [item["name"] for item in catalog]

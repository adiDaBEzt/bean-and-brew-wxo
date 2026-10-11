"""Long-Term Structured Semantic Memory Manager.

Architecture:
- Backed by an Entity-Attribute-Value (EAV) SQLite store at `data/semantic_memory.db`.
- Table schema: (user_id, category, entity, attribute, value, confidence, updated_at).
- Primary key / conflict target on (user_id, category, entity, attribute) with atomic UPSERT
  to completely eliminate contradictory preferences (e.g. Oat Milk -> Almond Milk).
- Self-hosted Qwen 2.5 7B on Modal for structured triples extraction in background tasks.
- Sentence-Transformers (all-MiniLM-L6-v2) for semantic vector recall over user state.
- Strict isolation by `user_id`: users only ever search & retrieve their own memories.
- Backward-compatible Mem0 instance integration for hybrid recall.
"""
import json
import os
import pathlib
import sqlite3
from typing import Any, Dict, List, Optional

import httpx
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "semantic_memory.db"

QWEN_ENDPOINT = os.getenv(
    "QWEN_ENDPOINT",
    "https://aditya-krishnan28--vllm-qwen-orchestrate-serve.modal.run/v1/chat/completions",
)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "qwen-orchestrate-token")
QWEN_MODEL = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")

_memory_instance = None
_embedder_instance = None


def init_db(db_path: pathlib.Path = DB_PATH) -> None:
    """Initialize SQLite database and ensure semantic_memory table schema exists."""
    db_path = pathlib.Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_memory (
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                entity TEXT NOT NULL,
                attribute TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, category, entity, attribute)
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_semantic_memory_user
            ON semantic_memory(user_id);
        """)
        conn.commit()


def upsert_semantic_memory(
    user_id: str,
    category: str,
    entity: str,
    attribute: str,
    value: str,
    confidence: float = 1.0,
    db_path: pathlib.Path = DB_PATH,
) -> None:
    """Atomic UPSERT on (user_id, category, entity, attribute) to prevent contradictions."""
    db_path = pathlib.Path(db_path)
    init_db(db_path)
    uid = (user_id or "").strip()
    cat = (category or "preference").strip().lower()
    ent = (entity or "").strip().lower()
    attr = (attribute or "preference").strip().lower()
    val = str(value if value is not None else "").strip()

    if not uid or not ent or not val:
        return

    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("""
            INSERT INTO semantic_memory (
                user_id, category, entity, attribute, value, confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, category, entity, attribute)
            DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                updated_at = CURRENT_TIMESTAMP;
        """, (uid, cat, ent, attr, val, float(confidence)))
        conn.commit()


def get_user_semantic_facts(user_id: str, db_path: pathlib.Path = DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve all structured EAV facts for a user."""
    db_path = pathlib.Path(db_path)
    init_db(db_path)
    uid = (user_id or "").strip()
    if not uid:
        return []
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT user_id, category, entity, attribute, value, confidence, updated_at
            FROM semantic_memory
            WHERE user_id = ?
            ORDER BY updated_at DESC, entity ASC;
        """, (uid,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def format_fact(fact: Dict[str, Any]) -> str:
    """Format structured fact into clean readable key-value string."""
    entity = str(fact.get("entity", "")).title()
    attr = str(fact.get("attribute", "")).lower()
    val = str(fact.get("value", ""))
    return f"{entity} {attr}: {val}"


def extract_semantic_triples(text: str) -> List[Dict[str, Any]]:
    """Use self-hosted Qwen 2.5 7B to extract structured triples (category, entity, attribute, value)."""
    if not (text and text.strip()):
        return []

    prompt = f"""You are a memory extraction system. Analyze the following dialogue and extract persistent user facts, preferences, constraints, or profile details.
Extract each fact as an Entity-Attribute-Value (EAV) entry in JSON.
Categories should be broad classifications like: preference, profile, schedule, workplace, constraint.
Entity is the object/subject (e.g., milk, syrup, shift, store, diet).
Attribute is the specific property (e.g., type, preference, time, allergy).
Value is the current explicit value or choice.

Normalize entities and attributes to lowercase canonical singular forms so updates overwrite old values cleanly (e.g. entity: "milk", attribute: "type").

Dialogue:
{text}

Respond ONLY with a JSON list of objects matching this schema:
[
  {{
    "category": "preference",
    "entity": "milk",
    "attribute": "type",
    "value": "oat milk",
    "confidence": 0.95
  }}
]
If there are no personal facts or preferences to extract, respond with []."""

    try:
        headers = {
            "Authorization": f"Bearer {QWEN_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": QWEN_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise JSON extractor. Output valid JSON only, without markdown fences or commentary.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(QWEN_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                print(f"[WARN] Qwen extraction HTTP {resp.status_code}: {resp.text}")
                return []
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"].strip()

            cleaned = raw_content
            # Strip markdown code fences if present
            fence = chr(96) * 3
            if fence in cleaned:
                parts = cleaned.split(fence)
                for part in parts:
                    part_str = part.strip()
                    if part_str.startswith("json"):
                        part_str = part_str[4:].strip()
                    if part_str.startswith("[") or part_str.startswith("{"):
                        cleaned = part_str
                        break

            # If still surrounded by chatter, extract substring bounded by '[' or '{'
            if not (cleaned.startswith("[") or cleaned.startswith("{")):
                start_arr = cleaned.find("[")
                end_arr = cleaned.rfind("]")
                start_obj = cleaned.find("{")
                end_obj = cleaned.rfind("}")
                if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
                    cleaned = cleaned[start_arr : end_arr + 1]
                elif start_obj != -1 and end_obj != -1 and end_obj > start_obj:
                    cleaned = cleaned[start_obj : end_obj + 1]

            try:
                items = json.loads(cleaned)
            except Exception:
                return []

            if isinstance(items, dict):
                items = [items]

            if isinstance(items, list):
                valid = []
                for item in items:
                    if isinstance(item, dict) and item.get("entity") and item.get("value"):
                        valid.append({
                            "category": str(item.get("category", "preference")).strip().lower(),
                            "entity": str(item.get("entity", "")).strip().lower(),
                            "attribute": str(item.get("attribute", "type")).strip().lower(),
                            "value": str(item.get("value", "")).strip(),
                            "confidence": float(item.get("confidence", 1.0)),
                        })
                return valid
            return []
    except Exception as e:
        print(f"[WARN] Qwen extraction error: {e}")
        return []


def get_embedder():
    """Singleton SentenceTransformer model for semantic vector similarity."""
    global _embedder_instance
    if _embedder_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder_instance = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        except Exception as e:
            print(f"[WARN] Could not load SentenceTransformer: {e}")
            _embedder_instance = False
    return _embedder_instance if _embedder_instance is not False else None


def get_memory_manager():
    """Backward-compatible Mem0 instance."""
    global _memory_instance
    if _memory_instance is None:
        try:
            from mem0 import Memory
            qdrant_dir = ROOT / "data" / "mem0_qdrant"
            qdrant_dir.mkdir(parents=True, exist_ok=True)

            config = {
                "vector_store": {
                    "provider": "qdrant",
                    "config": {
                        "path": str(qdrant_dir),
                        "collection_name": "bean_brew_user_memories",
                        "embedding_model_dims": 384,
                    },
                },
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": QWEN_MODEL,
                        "openai_base_url": "https://aditya-krishnan28--vllm-qwen-orchestrate-serve.modal.run/v1",
                        "api_key": QWEN_API_KEY,
                        "temperature": 0.1,
                    },
                },
                "embedder": {
                    "provider": "huggingface",
                    "config": {
                        "model": "sentence-transformers/all-MiniLM-L6-v2",
                    },
                },
            }
            _memory_instance = Memory.from_config(config)
        except Exception as e:
            print(f"[WARN] Mem0 initialization failed: {e}")
            _memory_instance = None
    return _memory_instance


def search_user_memories(
    user_id: str,
    query: str = "",
    limit: int = 5,
    db_path: pathlib.Path = DB_PATH,
) -> List[str]:
    """Retrieve relevant long-term memories for this user using structured EAV + vector recall."""
    facts = get_user_semantic_facts(user_id, db_path=db_path)
    if not facts:
        # Fallback to legacy Mem0 search if no structured facts exist yet
        try:
            mem = get_memory_manager()
            if mem:
                res = mem.search(query, filters={"user_id": user_id}, limit=limit)
                return [r.get("memory") for r in res.get("results", []) if r.get("memory")]
        except Exception:
            pass
        return []

    generic_queries = {"", "all", "preferences", "facts", "preferences and facts"}
    cleaned_query = (query or "").strip().lower()
    formatted_facts = [format_fact(f) for f in facts]

    if cleaned_query in generic_queries or len(cleaned_query) < 3:
        return formatted_facts[:limit]

    # Semantic Vector Recall over active structured facts
    embedder = get_embedder()
    if embedder is not None:
        try:
            query_emb = embedder.encode(cleaned_query)
            fact_embs = embedder.encode(formatted_facts)
            norms = np.linalg.norm(fact_embs, axis=1) * np.linalg.norm(query_emb)
            norms[norms == 0] = 1e-9
            scores = np.dot(fact_embs, query_emb) / norms
            ranked_indices = np.argsort(scores)[::-1]
            return [formatted_facts[idx] for idx in ranked_indices[:limit]]
        except Exception as e:
            print(f"[WARN] Semantic vector search error: {e}")

    # Fallback to lexical token overlap
    scored = []
    tokens = set(cleaned_query.split())
    for f, text in zip(facts, formatted_facts):
        overlap = sum(1 for t in tokens if t in text.lower())
        scored.append((overlap, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:limit]]


def record_user_memory(
    user_id: str,
    text: str,
    db_path: pathlib.Path = DB_PATH,
) -> List[Dict[str, Any]]:
    """Extract structured triples with Qwen and atomically upsert into SQLite."""
    try:
        triples = extract_semantic_triples(text)
        for t in triples:
            category = t.get("category", "preference")
            entity = t.get("entity", "")
            attribute = t.get("attribute", "preference")
            value = t.get("value", "")
            confidence = t.get("confidence", 1.0)
            if entity and value:
                upsert_semantic_memory(
                    user_id=user_id,
                    category=category,
                    entity=entity,
                    attribute=attribute,
                    value=value,
                    confidence=confidence,
                    db_path=db_path,
                )
        return triples
    except Exception as e:
        print(f"[WARN] record_user_memory error: {e}")
        return []

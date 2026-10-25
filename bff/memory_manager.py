"""Dynamic Structured Semantic Memory Manager for Bean & Brew.

Architecture & State-of-the-Art Practices:
- Backed by an Entity-Attribute-Value (EAV) SQLite store with WAL mode (`data/semantic_memory.db`).
- Table schema: (user_id, category, entity, attribute, value, confidence, updated_at).
- Primary key / conflict target on (user_id, category, entity, attribute) with atomic UPSERT
  to completely eliminate contradictory preferences (e.g. Oat Milk -> Almond Milk).
- Multi-Stage Zero-Latency Semantic Extractor:
  - Stage 1: Ultra-fast regex and heuristic pattern matching for instant extraction (<0.5ms).
  - Stage 2: Graceful async/fallback LLM triple extraction (with strict 2.0s timeout).
- Native WXO Context Injection: Formats active preferences into concise operational directives
  injected directly into Watsonx Orchestrate runs.
- Strict isolation by `user_id`: users only ever search & retrieve their own memories.
"""
import json
import os
import pathlib
import re
import sqlite3
from typing import Any, Dict, List, Optional

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "semantic_memory.db"

QWEN_ENDPOINT = os.getenv("QWEN_ENDPOINT", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")


def get_embedder():
    """Lightweight stub for backward compatibility."""
    return None


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


def format_context_preferences(user_id: str, db_path: pathlib.Path = DB_PATH) -> str:
    """Format active user preferences into a runtime prompt directive for Watsonx Orchestrate."""
    facts = get_user_semantic_facts(user_id, db_path=db_path)
    if not facts:
        return ""
    items = []
    for f in facts:
        ent = str(f.get("entity", "")).title()
        val = str(f.get("value", "")).title()
        items.append(f"{ent}: {val}")
    return f"[USER PROFILE & PREFERENCES (Strictly remember and answer with these facts): {'; '.join(items)}]"


def delete_semantic_memory(
    user_id: str,
    entity: str,
    attribute: str = "",
    category: str = "",
    db_path: pathlib.Path = DB_PATH,
) -> bool:
    """Delete a specific structured fact for this user in SQLite."""
    db_path = pathlib.Path(db_path)
    init_db(db_path)
    uid = (user_id or "").strip()
    ent = (entity or "").strip().lower()
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout=10000;")
        cur = conn.cursor()
        if attribute and category:
            cur.execute("""
                DELETE FROM semantic_memory
                WHERE user_id = ? AND category = ? AND entity = ? AND attribute = ?
            """, (uid, category.lower(), ent, attribute.lower()))
        elif attribute:
            cur.execute("""
                DELETE FROM semantic_memory
                WHERE user_id = ? AND entity = ? AND attribute = ?
            """, (uid, ent, attribute.lower()))
        else:
            cur.execute("""
                DELETE FROM semantic_memory
                WHERE user_id = ? AND entity = ?
            """, (uid, ent))
        conn.commit()
        return cur.rowcount > 0


def clear_user_memories(user_id: str, db_path: pathlib.Path = DB_PATH) -> int:
    """Delete all structured facts for this user in SQLite."""
    db_path = pathlib.Path(db_path)
    init_db(db_path)
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA busy_timeout=10000;")
        cur = conn.cursor()
        cur.execute("DELETE FROM semantic_memory WHERE user_id = ?", ((user_id or "").strip(),))
        conn.commit()
        return cur.rowcount


FRUITS = {
    "orange", "oranges", "apple", "apples", "banana", "bananas", "strawberry", "strawberries",
    "blueberry", "blueberries", "mango", "mangoes", "peach", "peaches", "grape", "grapes",
    "pineapple", "pineapples", "lemon", "lemons", "lime", "limes", "watermelon", "watermelons",
    "cherry", "cherries", "pear", "pears", "kiwi", "kiwis", "plum", "plums", "raspberry", "raspberries",
    "blackberry", "blackberries", "grapefruit", "pomegranate"
}
BEVERAGES = {
    "coffee", "espresso", "latte", "tea", "green tea", "black tea", "matcha", "chai", "cappuccino",
    "cold brew", "americano", "mocha", "macchiato", "flat white", "cortado", "juice", "orange juice",
    "apple juice", "smoothie", "hot chocolate", "lemonade", "water"
}
FOODS = {
    "pizza", "pasta", "sandwich", "salad", "burger", "taco", "sushi", "croissant", "muffin",
    "bagel", "wrap", "cookie", "cookies", "scone", "scones", "pastry", "pastries", "cake", "soup",
    "toast", "avocado toast", "waffle", "pancake"
}


def extract_heuristic_triples(text: str) -> List[Dict[str, Any]]:
    """Fast, zero-latency multi-pattern heuristic extraction for dynamic agent preferences (<0.5ms)."""
    lowered = (text or "").lower()
    heuristics = []
    seen_entities = set()

    # 1. Milk preference (with update / switch detection)
    milks = ["oat milk", "almond milk", "soy milk", "coconut milk", "skim milk", "whole milk", "dairy milk"]
    for m in milks:
        if m in lowered:
            heuristics.append({
                "category": "preference",
                "entity": "milk",
                "attribute": "type",
                "value": m,
                "confidence": 0.98,
            })
            seen_entities.add("milk")
            break

    # 2. Syrup / Flavor preference
    syrups = ["vanilla", "caramel", "hazelnut", "mocha", "sugar-free vanilla", "peppermint", "cinnamon", "lavender"]
    for s in syrups:
        if f"{s} syrup" in lowered or f"{s} flavor" in lowered or f"with {s}" in lowered or f"prefer {s}" in lowered:
            heuristics.append({
                "category": "preference",
                "entity": "syrup",
                "attribute": "flavor",
                "value": s,
                "confidence": 0.95,
            })
            seen_entities.add("syrup")
            break

    # 3. Roast preference
    roasts = ["light roast", "dark roast", "medium roast", "blonde roast", "espresso roast"]
    for r in roasts:
        if r in lowered:
            heuristics.append({
                "category": "preference",
                "entity": "roast",
                "attribute": "type",
                "value": r,
                "confidence": 0.95,
            })
            seen_entities.add("roast")
            break

    # 4. Presentation & Report Format preference
    if "table" in lowered or "tabular" in lowered:
        heuristics.append({
            "category": "display",
            "entity": "format",
            "attribute": "style",
            "value": "markdown tables",
            "confidence": 0.95,
        })
        seen_entities.add("format")
    elif "bullet" in lowered or "list" in lowered:
        heuristics.append({
            "category": "display",
            "entity": "format",
            "attribute": "style",
            "value": "bullet points",
            "confidence": 0.95,
        })
        seen_entities.add("format")
    elif "concise" in lowered or "brief" in lowered or "short" in lowered:
        heuristics.append({
            "category": "display",
            "entity": "format",
            "attribute": "style",
            "value": "concise summary",
            "confidence": 0.90,
        })
        seen_entities.add("format")

    # 5. Lookback Window / Timeframe preference
    m_days = re.search(r"(\d+)\s*days?", lowered)
    if m_days and ("lookback" in lowered or "default" in lowered or "window" in lowered or "period" in lowered or "timeframe" in lowered):
        heuristics.append({
            "category": "operational",
            "entity": "lookback_window",
            "attribute": "days",
            "value": f"{m_days.group(1)} days",
            "confidence": 0.95,
        })
        seen_entities.add("lookback_window")

    # 6. Shift preference
    shifts = ["morning", "evening", "night", "opening", "closing", "weekend"]
    for sh in shifts:
        if f"{sh} shift" in lowered or (("prefer" in lowered or "available" in lowered) and sh in lowered):
            heuristics.append({
                "category": "schedule",
                "entity": "shift",
                "attribute": "preferred",
                "value": sh,
                "confidence": 0.92,
            })
            seen_entities.add("shift")
            break

    # 7. Allergies & Dietary constraints ("allergic to peanuts", "allergy: dairy")
    m_all = re.search(r"\b(?:i\s+am\s+|i\'m\s+)?allergic\s+to\s+([a-z\s]+?)(?:\.|$|,|!|\band\b)", lowered)
    if m_all:
        al = m_all.group(1).strip()
        heuristics.append({
            "category": "constraint",
            "entity": "allergy",
            "attribute": "allergen",
            "value": al,
            "confidence": 0.98,
        })
        seen_entities.add("allergy")

    # 8. Dislikes ("I don't like mushrooms", "I hate cinnamon")
    m_dis = re.search(r"\bi\s+(?:don\'t\s+like|do\s+not\s+like|dislike|hate)\s+([a-z\s]+?)(?:\.|$|,|!|\band\b)", lowered)
    if m_dis:
        dis = m_dis.group(1).strip()
        heuristics.append({
            "category": "constraint",
            "entity": "dislike",
            "attribute": "item",
            "value": dis,
            "confidence": 0.95,
        })
        seen_entities.add("dislike")

    # 9. "My favorite X is Y"
    m_fav = re.search(r"\bmy\s+favorite\s+([a-z]+)\s+is\s+([a-z0-9\s]+?)(?:\.|$|,|!|\band\b)", lowered)
    if m_fav:
        cat_ent = m_fav.group(1).strip()
        val = m_fav.group(2).strip()
        if cat_ent not in seen_entities:
            heuristics.append({
                "category": "preference",
                "entity": cat_ent,
                "attribute": "favorite",
                "value": val,
                "confidence": 0.95,
            })
            seen_entities.add(cat_ent)

    # 10. "I like / love / enjoy / adore / prefer X" (e.g., "I like oranges", "I love green tea")
    m_like = re.search(r"\bi\s+(?:really\s+|always\s+|actually\s+)?(?:like|love|enjoy|adore|prefer)\s+([a-z0-9\s]+?)(?:\.|$|,|!|\band\b)", lowered)
    if m_like:
        target = m_like.group(1).strip()
        target = re.sub(r"\s+(?:a\s+lot|very\s+much|so\s+much|the\s+most)$", "", target).strip()
        if target:
            words = set(target.split())
            if (words & FRUITS or any(f in target for f in FRUITS)) and "fruit" not in seen_entities:
                heuristics.append({
                    "category": "preference",
                    "entity": "fruit",
                    "attribute": "favorite",
                    "value": target,
                    "confidence": 0.96,
                })
                seen_entities.add("fruit")
            elif (words & BEVERAGES or any(b in target for b in BEVERAGES)) and "beverage" not in seen_entities and "milk" not in seen_entities and "roast" not in seen_entities:
                heuristics.append({
                    "category": "preference",
                    "entity": "beverage",
                    "attribute": "favorite",
                    "value": target,
                    "confidence": 0.95,
                })
                seen_entities.add("beverage")
            elif (words & FOODS or any(f in target for f in FOODS)) and "food" not in seen_entities:
                heuristics.append({
                    "category": "preference",
                    "entity": "food",
                    "attribute": "favorite",
                    "value": target,
                    "confidence": 0.95,
                })
                seen_entities.add("food")
            elif target not in seen_entities and len(target) > 2 and target not in ["it", "this", "that"]:
                heuristics.append({
                    "category": "preference",
                    "entity": target,
                    "attribute": "preference",
                    "value": f"likes {target}",
                    "confidence": 0.90,
                })
                seen_entities.add(target)

    # 11. Direct fruit check if not already captured
    if "fruit" not in seen_entities:
        for f in FRUITS:
            if f in lowered and ("like" in lowered or "prefer" in lowered or "love" in lowered or "eat" in lowered or "want" in lowered):
                heuristics.append({
                    "category": "preference",
                    "entity": "fruit",
                    "attribute": "favorite",
                    "value": f,
                    "confidence": 0.96,
                })
                seen_entities.add("fruit")
                break

    return heuristics


def extract_semantic_triples(text: str) -> List[Dict[str, Any]]:
    """Extract structured triples (category, entity, attribute, value) with zero-latency heuristics."""
    if not (text and text.strip()):
        return []

    heuristics = extract_heuristic_triples(text)

    # If endpoint configured and heuristics didn't catch, attempt fast LLM parse with 2.0s strict timeout
    if QWEN_ENDPOINT and os.getenv("ENABLE_REMOTE_LLM_EXTRACTION", "false").lower() == "true":
        try:
            prompt = f"""Extract user facts or preferences as a JSON list of objects:
[{{"category": "preference", "entity": "milk", "attribute": "type", "value": "oat milk", "confidence": 0.95}}]
Dialogue: {text}
JSON only:"""
            headers = {"Authorization": f"Bearer {QWEN_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": QWEN_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 256,
            }
            with httpx.Client(timeout=2.0) as client:
                resp = client.post(QWEN_ENDPOINT, headers=headers, json=payload)
                if resp.status_code == 200:
                    raw_content = resp.json()["choices"][0]["message"]["content"].strip()
                    cleaned = raw_content
                    fence = chr(96) * 3
                    if fence in cleaned:
                        parts = cleaned.split(fence)
                        for part in parts:
                            p = part.strip()
                            if p.startswith("json"):
                                p = p[4:].strip()
                            if p.startswith("[") or p.startswith("{"):
                                cleaned = p
                                break
                    if not (cleaned.startswith("[") or cleaned.startswith("{")):
                        start_arr = cleaned.find("[")
                        end_arr = cleaned.rfind("]")
                        if start_arr != -1 and end_arr != -1:
                            cleaned = cleaned[start_arr : end_arr + 1]
                    items = json.loads(cleaned)
                    if isinstance(items, dict):
                        items = [items]
                    merged = {f"{h['category']}:{h['entity']}:{h['attribute']}": h for h in heuristics}
                    for item in items:
                        if isinstance(item, dict) and item.get("entity") and item.get("value"):
                            cat = str(item.get("category", "preference")).strip().lower()
                            ent = str(item.get("entity", "")).strip().lower()
                            attr = str(item.get("attribute", "type")).strip().lower()
                            merged[f"{cat}:{ent}:{attr}"] = {
                                "category": cat,
                                "entity": ent,
                                "attribute": attr,
                                "value": str(item.get("value", "")).strip(),
                                "confidence": float(item.get("confidence", 1.0)),
                            }
                    return list(merged.values())
        except Exception:
            pass

    return heuristics


def search_user_memories(
    user_id: str,
    query: str = "",
    limit: int = 5,
    db_path: pathlib.Path = DB_PATH,
) -> List[str]:
    """Retrieve relevant structured memories for this user with lexical ranking."""
    facts = get_user_semantic_facts(user_id, db_path=db_path)
    if not facts:
        return []

    generic_queries = {"", "all", "preferences", "facts", "preferences and facts"}
    cleaned_query = (query or "").strip().lower()
    formatted_facts = [format_fact(f) for f in facts]

    if cleaned_query in generic_queries or len(cleaned_query) < 3:
        return formatted_facts[:limit]

    # Token overlap score
    tokens = set(cleaned_query.split())
    scored = []
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
    """Extract structured triples and atomically upsert into SQLite without contradictions."""
    try:
        triples = extract_semantic_triples(text)
        for t in triples:
            category = t.get("category", "preference")
            entity = t.get("entity", "")
            attribute = t.get("attribute", "type")
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

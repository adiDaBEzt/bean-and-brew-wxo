"""Unit and integration tests for Structured Semantic Memory (EAV Store).
Run: venv/bin/python tests/test_semantic_memory.py
"""
import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bff.memory_manager import (
    extract_semantic_triples,
    format_fact,
    get_user_semantic_facts,
    init_db,
    record_user_memory,
    search_user_memories,
    upsert_semantic_memory,
)

results = []


def check(name, ok):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)


def test_schema_and_upsert_contradiction_elimination():
    with tempfile.NamedTemporaryFile(suffix=".db") as tf:
        db_path = pathlib.Path(tf.name)
        init_db(db_path)

        # 1. Insert initial preference
        upsert_semantic_memory(
            user_id="maya",
            category="preference",
            entity="milk",
            attribute="type",
            value="Oat Milk",
            confidence=0.9,
            db_path=db_path,
        )

        facts = get_user_semantic_facts("maya", db_path=db_path)
        check("Initial fact stored", len(facts) == 1 and facts[0]["value"] == "Oat Milk")

        # 2. Update preference to Almond Milk
        upsert_semantic_memory(
            user_id="maya",
            category="preference",
            entity="milk",
            attribute="type",
            value="Almond Milk",
            confidence=0.95,
            db_path=db_path,
        )

        facts_after = get_user_semantic_facts("maya", db_path=db_path)
        check(
            "Atomic UPSERT replaced old preference without duplicate/contradiction",
            len(facts_after) == 1 and facts_after[0]["value"] == "Almond Milk",
        )

        # 3. Third update to Coconut Milk
        upsert_semantic_memory(
            user_id="maya",
            category="preference",
            entity="milk",
            attribute="type",
            value="Coconut Milk",
            confidence=0.99,
            db_path=db_path,
        )
        facts_third = get_user_semantic_facts("maya", db_path=db_path)
        check(
            "Sequential UPSERT maintains single row invariant",
            len(facts_third) == 1 and facts_third[0]["value"] == "Coconut Milk",
        )


def test_user_isolation():
    with tempfile.NamedTemporaryFile(suffix=".db") as tf:
        db_path = pathlib.Path(tf.name)
        init_db(db_path)

        upsert_semantic_memory("maya", "preference", "milk", "type", "Almond Milk", db_path=db_path)
        upsert_semantic_memory("sam", "preference", "milk", "type", "Whole Milk", db_path=db_path)

        maya_facts = get_user_semantic_facts("maya", db_path=db_path)
        sam_facts = get_user_semantic_facts("sam", db_path=db_path)

        check("Maya facts isolated", len(maya_facts) == 1 and maya_facts[0]["value"] == "Almond Milk")
        check("Sam facts isolated", len(sam_facts) == 1 and sam_facts[0]["value"] == "Whole Milk")


def test_vector_recall():
    with tempfile.NamedTemporaryFile(suffix=".db") as tf:
        db_path = pathlib.Path(tf.name)
        init_db(db_path)

        # Insert test facts into isolated DB
        upsert_semantic_memory("test_user", "preference", "milk", "type", "almond milk", db_path=db_path)
        upsert_semantic_memory("test_user", "preference", "syrup", "flavor", "vanilla", db_path=db_path)
        upsert_semantic_memory("test_user", "schedule", "shift", "preferred", "morning", db_path=db_path)

        # 1. Limit=1 vector recall
        recalled_drink = search_user_memories("test_user", query="dairy-free beverage choice", limit=1, db_path=db_path)
        check("Vector recall matches dairy-free query to milk preference", any("milk" in r.lower() for r in recalled_drink))

        # 2. Limit >= len(facts) must still rank the most relevant item at top (index 0)
        recalled_shift_all = search_user_memories("test_user", query="what shift do I work", limit=3, db_path=db_path)
        check("Vector recall ranks shift at index 0 even when limit >= facts count", "shift" in recalled_shift_all[0].lower())

        # 3. Generic query returns all facts up to limit
        all_memories = search_user_memories("test_user", query="preferences and facts", limit=10, db_path=db_path)
        check("Generic query returns all structured facts", len(all_memories) == 3)


def test_robust_json_parsing_and_edge_cases():
    mock_chatter = """Here are the extracted user preferences:
```json
[
  {
    "category": "preference",
    "entity": "syrup",
    "attribute": "flavor",
    "value": "hazelnut",
    "confidence": 0.95
  }
]
```
Let me know if you need any additional facts extracted."""

    mock_single_obj = """{"category": "profile", "entity": "diet", "attribute": "constraint", "value": "vegan"}"""

    with patch("httpx.Client.post") as mock_post:
        # Test 1: Markdown code fences with commentary
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": mock_chatter}}]
        }
        triples_chatter = extract_semantic_triples("dummy dialogue")
        check("Robust parsing handles commentary and code fences", len(triples_chatter) == 1 and triples_chatter[0]["entity"] == "syrup")

        # Test 2: Single dict object response
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": mock_single_obj}}]
        }
        triples_obj = extract_semantic_triples("dummy dialogue")
        check("Robust parsing handles single object responses", len(triples_obj) == 1 and triples_obj[0]["entity"] == "diet")

        # Test 3: Empty input
        triples_empty = extract_semantic_triples("")
        check("Empty dialogue returns empty triples list", len(triples_empty) == 0)


def test_qwen_extraction():
    dialogue1 = "User said: I always take oat milk in my latte. Assistant replied: I have noted your milk preference."
    triples1 = extract_semantic_triples(dialogue1)
    check("Live Qwen extracts structured triple from dialogue", len(triples1) > 0 and triples1[0].get("entity") == "milk")

    dialogue_none = "User said: What was our revenue yesterday? Assistant replied: Revenue was $5,000."
    triples_none = extract_semantic_triples(dialogue_none)
    check("Live Qwen ignores non-personal dialogue turns", len(triples_none) == 0)


def main():
    print("--- Running Semantic Memory Tests ---")
    test_schema_and_upsert_contradiction_elimination()
    test_user_isolation()
    test_vector_recall()
    test_robust_json_parsing_and_edge_cases()
    test_qwen_extraction()

    print(f"\n{sum(results)}/{len(results)} tests passed.")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()

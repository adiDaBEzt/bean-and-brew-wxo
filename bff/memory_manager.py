"""Long-Term Semantic Memory Manager using Mem0 + Qdrant + self-hosted Qwen.

Architecture:
- Embedded local Qdrant vector database (stores semantic embeddings).
- Sentence-Transformers (all-MiniLM-L6-v2) for 384-dimensional dense vectors.
- Self-hosted Qwen 2.5 7B (vLLM) on Modal for fact extraction & memory synthesis.
- Strict isolation by `user_id`: users only ever search & retrieve their own memories.
"""
import os
import pathlib
from typing import List
from mem0 import Memory

ROOT = pathlib.Path(__file__).resolve().parent.parent

_memory_instance = None

def get_memory_manager() -> Memory:
    global _memory_instance
    if _memory_instance is None:
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
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "openai_base_url": "https://aditya-krishnan28--vllm-qwen-orchestrate-serve.modal.run/v1",
                    "api_key": "qwen-orchestrate-token",
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
    return _memory_instance


def search_user_memories(user_id: str, query: str, limit: int = 3) -> List[str]:
    """Retrieve relevant long-term memories for this specific user only."""
    try:
        mem = get_memory_manager()
        res = mem.search(query, filters={"user_id": user_id}, limit=limit)
        return [r.get("memory") for r in res.get("results", []) if r.get("memory")]
    except Exception as e:
        print(f"[WARN] Mem0 search error: {e}")
        return []


def record_user_memory(user_id: str, text: str):
    """Asynchronously extract and store persistent user preferences and facts."""
    try:
        mem = get_memory_manager()
        mem.add(text, user_id=user_id)
    except Exception as e:
        print(f"[WARN] Mem0 add error: {e}")

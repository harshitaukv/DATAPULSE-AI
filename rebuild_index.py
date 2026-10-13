"""Rebuild the RAG (FAISS) index from knowledge_base/troubleshooting_guides.

Usage:  python scripts/rebuild_index.py
"""
import json

import _bootstrap  # noqa: F401

from app.ai.rag import get_index

if __name__ == "__main__":
    print(json.dumps(get_index().build(), indent=2))

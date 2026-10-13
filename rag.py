"""Retrieval-Augmented Generation index over the troubleshooting knowledge base.

Pipeline: load markdown -> extract text -> chunk by section -> embed -> FAISS
(inner product on L2-normalised vectors = cosine similarity) -> top-k search
with a relevance threshold. The index is persisted to DATA_DIR/index together
with a manifest (knowledge-base hash, embedding backend). If the knowledge base
changes or the index files are missing (e.g. an ephemeral host restarted), the
index is rebuilt automatically from the markdown sources.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ai.embeddings import Embedder, TfidfEmbedder, create_embedder
from app.config import get_settings

logger = logging.getLogger("datapulse.rag")

try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without faiss installed
    FAISS_AVAILABLE = False


@dataclass
class Chunk:
    chunk_id: int
    doc_id: str
    title: str
    section: str
    text: str


@dataclass
class Hit:
    doc_id: str
    title: str
    section: str
    text: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def load_documents(kb_dir: Path) -> list[tuple[str, str, str]]:
    docs = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        docs.append((path.stem, title_match.group(1).strip() if title_match else path.stem, text))
    return docs


def chunk_document(doc_id: str, title: str, text: str, max_chars: int, start_id: int) -> list[Chunk]:
    sections = re.split(r"^##\s+", text, flags=re.MULTILINE)
    chunks: list[Chunk] = []
    intro = re.sub(r"^#\s+.+$", "", sections[0], flags=re.MULTILINE).strip()
    parts = [("Overview", intro)] if intro else []
    for sec in sections[1:]:
        heading, _, body = sec.partition("\n")
        parts.append((heading.strip(), body.strip()))
    for heading, body in parts:
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        buf = ""
        for para in paragraphs:
            if buf and len(buf) + len(para) > max_chars:
                chunks.append(Chunk(start_id + len(chunks), doc_id, title, heading, buf))
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            chunks.append(Chunk(start_id + len(chunks), doc_id, title, heading, buf))
    return chunks


class RAGIndex:
    def __init__(self):
        self.s = get_settings()
        self.dir = self.s.index_dir
        self.chunks: list[Chunk] = []
        self.embedder: Embedder | None = None
        self.index = None
        self.vectors: np.ndarray | None = None
        self.manifest: dict = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------------- building
    def kb_hash(self) -> str:
        h = hashlib.sha256()
        for path in sorted(self.s.knowledge_base_dir.glob("*.md")):
            h.update(path.name.encode())
            h.update(path.read_bytes())
        return h.hexdigest()

    def build(self) -> dict:
        with self._lock:
            docs = load_documents(self.s.knowledge_base_dir)
            chunks: list[Chunk] = []
            for doc_id, title, text in docs:
                chunks.extend(chunk_document(doc_id, title, text, self.s.chunk_max_chars, len(chunks)))
            if not chunks:
                raise RuntimeError("The knowledge base is empty; add markdown files to knowledge_base/.")
            embedder = create_embedder()
            texts = [f"{c.title}. {c.section}. {c.text}" for c in chunks]
            embedder.fit(texts)
            vectors = embedder.encode(texts)
            self.dir.mkdir(parents=True, exist_ok=True)
            if FAISS_AVAILABLE:
                index = faiss.IndexFlatIP(vectors.shape[1])
                index.add(vectors)
                faiss.write_index(index, str(self.dir / "kb.faiss"))
                self.index = index
            np.save(self.dir / "kb_vectors.npy", vectors)
            embedder.save(self.dir)
            (self.dir / "chunks.json").write_text(json.dumps([asdict(c) for c in chunks]))
            self.manifest = {"kb_hash": self.kb_hash(), "backend": embedder.name,
                             "model": getattr(embedder, "model_name", "tfidf-1-2gram"),
                             "documents": len(docs), "chunks": len(chunks), "dimensions": int(vectors.shape[1]),
                             "vector_store": "faiss.IndexFlatIP" if FAISS_AVAILABLE else "numpy",
                             "built_at": datetime.now(timezone.utc).isoformat()}
            (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2))
            self.chunks, self.embedder, self.vectors = chunks, embedder, vectors
            logger.info("RAG index built: %s", self.manifest)
            return self.manifest

    def _try_load(self) -> bool:
        manifest_path = self.dir / "manifest.json"
        if not manifest_path.exists() or not (self.dir / "chunks.json").exists():
            return False
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("kb_hash") != self.kb_hash():
            logger.info("Knowledge base changed; index will be rebuilt")
            return False
        try:
            if manifest["backend"] == "tfidf":
                embedder: Embedder = TfidfEmbedder()
                embedder.load(self.dir)
            else:
                embedder = create_embedder()
                if embedder.name != manifest["backend"]:
                    return False
            self.vectors = np.load(self.dir / "kb_vectors.npy")
            if FAISS_AVAILABLE and (self.dir / "kb.faiss").exists():
                self.index = faiss.read_index(str(self.dir / "kb.faiss"))
            self.chunks = [Chunk(**c) for c in json.loads((self.dir / "chunks.json").read_text())]
            self.embedder, self.manifest = embedder, manifest
            return True
        except Exception as exc:  # noqa: BLE001 - any corruption -> rebuild
            logger.warning("Could not load RAG index (%s); rebuilding", type(exc).__name__)
            return False

    def ensure_ready(self) -> None:
        if self.embedder is not None and self.manifest.get("kb_hash") == self.kb_hash():
            return
        if not self._try_load():
            self.build()

    # -------------------------------------------------------------- querying
    def search(self, query: str, k: int | None = None) -> dict:
        self.ensure_ready()
        k = k or self.s.rag_top_k
        q = self.embedder.encode([query])
        if self.index is not None:
            scores, ids = self.index.search(q, min(k, len(self.chunks)))
            pairs = [(int(i), float(sc)) for i, sc in zip(ids[0], scores[0]) if i >= 0]
        else:
            sims = self.vectors @ q[0]
            order = np.argsort(-sims)[:k]
            pairs = [(int(i), float(sims[i])) for i in order]
        threshold = self.embedder.min_score
        hits = [Hit(self.chunks[i].doc_id, self.chunks[i].title, self.chunks[i].section, self.chunks[i].text,
                    round(sc, 4)) for i, sc in pairs if sc >= threshold]
        return {"query": query, "hits": [h.to_dict() for h in hits], "threshold": threshold,
                "backend": self.manifest.get("backend"), "relevant_found": bool(hits),
                "best_score": round(pairs[0][1], 4) if pairs else None}

    def status(self) -> dict:
        try:
            self.ensure_ready()
            return {"ready": True, **self.manifest}
        except Exception as exc:  # noqa: BLE001
            return {"ready": False, "error": str(exc)}


_index: RAGIndex | None = None


def get_index() -> RAGIndex:
    global _index
    if _index is None:
        _index = RAGIndex()
    return _index


def reset_index() -> None:
    global _index
    _index = None

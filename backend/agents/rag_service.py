import json
import logging
from typing import Any, Dict, List

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from backend.config import settings
from backend.factory import get_chat_model

logger = logging.getLogger("rag_service")


class RAGService:
    """Local Chroma RAG with a short yes/no relevance gate before returning context."""

    @staticmethod
    def _client():
        return chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIRECTORY)

    @staticmethod
    def _embedding_function():
        # Local Chroma embeddings; no Gemini API required
        return DefaultEmbeddingFunction()

    @classmethod
    def _collection(cls, name: str):
        return cls._client().get_or_create_collection(
            name=f"{name}_local",
            embedding_function=cls._embedding_function(),
            metadata={"hnsw:space": "cosine"}
        )
    @classmethod
    def _ingest(cls, collection_name: str, owner_key: str, blocks: List[Dict[str, Any]]) -> int:
        if not blocks:
            return 0
        collection = cls._collection(collection_name)
        collection.upsert(
            ids=[block["id"] for block in blocks],
            documents=[block["content"] for block in blocks],
            metadatas=[dict(block["metadata"], **{owner_key: block["owner_id"]}) for block in blocks],
        )
        return len(blocks)

    @classmethod
    async def ingest_product(cls, search_id: str, product_name: str, product_description: str,
                             capabilities: List[str], value_propositions: List[str]) -> int:
        texts = [product_description, *capabilities, *value_propositions]
        blocks = [
            {"id": f"product:{search_id}:{index}", "owner_id": search_id,
             "content": f"{product_name}: {text}", "metadata": {"type": "product"}}
            for index, text in enumerate(texts) if text.strip()
        ]
        return cls._ingest("product_rag", "search_id", blocks)

    @classmethod
    async def ingest_company_docs(cls, company_id: str, content_blocks: List[str],
                                  metadata: Dict[str, Any] = None) -> int:
        blocks = [
            {"id": f"company:{company_id}:{index}", "owner_id": company_id, "content": text,
             "metadata": metadata or {}}
            for index, text in enumerate(content_blocks) if text.strip()
        ]
        return cls._ingest("company_rag", "company_id", blocks)

    @classmethod
    async def query_product(cls, search_id: str, query: str, limit: int = 3) -> Dict[str, Any]:
        collection = cls._collection("product_rag")
        result = collection.query(query_texts=[query], n_results=limit, where={"search_id": search_id})
        documents = result.get("documents", [[]])[0]
        distances = result.get("distances", [[]])[0]
        sources = [{"content": doc, "similarity": round(1 - distance, 3)} for doc, distance in zip(documents, distances)]
        context = "\n".join(documents)
        if not context:
            return {"answer": "no", "tldr": "No relevant product context found.", "sources": []}

        prompt = (
            "Answer only JSON: {\"answer\":\"yes|no\",\"tldr\":\"max 25 words\"}. "
            "Say yes only if the context directly helps answer the query.\n"
            f"Query: {query}\nContext: {context[:1800]}"
        )
        try:
            raw = (await get_chat_model(temperature=0).ainvoke(prompt)).content.strip().removeprefix("```json").removesuffix("```").strip()
            gate = json.loads(raw)
            answer = "yes" if str(gate.get("answer", "no")).lower() == "yes" else "no"
            return {"answer": answer, "tldr": str(gate.get("tldr", ""))[:240], "sources": sources if answer == "yes" else []}
        except Exception as exc:
            logger.warning("RAG relevance gate failed: %s", exc)
            return {"answer": "no", "tldr": "RAG relevance check unavailable.", "sources": []}

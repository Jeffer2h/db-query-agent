"""Embed table descriptions and retrieve the most relevant ones per question.

Why this exists: putting the full schema in every prompt does not scale
beyond ~10 tables. The retriever embeds each table as a small document
and returns only the top-k most relevant ones for the user's question.
The same RAG pattern as project 01, applied to schema metadata.

Embeddings are produced by Voyage AI (voyage-3-lite). Keeping a local
PyTorch model just to embed 6 short table descriptions was overkill for
this project and inflated the Docker image by ~2 GB. Voyage is called
through a thin wrapper here and the cost per query is logged via the
observability helper, same as the Claude API calls.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import chromadb
import voyageai

from src.database import ColumnInfo, TableInfo, list_tables_metadata
from src.observability import log_call
from src.seed import PROJECT_ROOT

CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
COLLECTION_NAME = "schema"
EMBED_MODEL_NAME = "voyage-3-lite"


# Natural-language descriptions per table.
# These are what the embedding model "reads", so they should describe the
# *meaning* of the table in the words a user would actually use.
TABLE_DESCRIPTIONS: dict[str, str] = {
    "customers": (
        "Customers who registered in the store. Each row has the customer "
        "name, email, country, and the date they signed up (created_at). "
        "Use this table to answer questions about users, buyers, clients, "
        "countries of origin or signup dates."
    ),
    "categories": (
        "Product categories such as electronics, books, clothing, home, "
        "sports and toys. Used to group products into departments or "
        "sections of the store."
    ),
    "products": (
        "Catalog of items sold in the store. Each product belongs to a "
        "category and has a name, current price and stock level. Use this "
        "table to answer questions about products, inventory, prices or "
        "what is for sale."
    ),
    "orders": (
        "Customer orders. Each order has a date (order_date) and a status: "
        "pending, paid, shipped, delivered or cancelled. Each order belongs "
        "to one customer. Use this table to answer questions about sales "
        "volume, time periods, order status, or who bought what."
    ),
    "order_items": (
        "Line items inside each order: which product, how many units "
        "(quantity) and the unit_price at the time of purchase. To compute "
        "revenue or units sold per product, multiply quantity by "
        "unit_price from this table — not products.price, which is the "
        "current price."
    ),
    "payments": (
        "Payments received for orders. Each payment has an amount, method "
        "(credit_card, debit_card, paypal, bank_transfer), the date "
        "(paid_at) and a status (completed, failed, refunded). Use this "
        "table to answer questions about revenue actually collected, "
        "payment methods, refunds, or cashflow."
    ),
}


@dataclass
class RetrievedTable:
    name: str
    columns: list[ColumnInfo]
    description: str


class SchemaRetriever:
    """Builds and queries a vector index of the database schema."""

    def __init__(
        self,
        chroma_dir: Path = CHROMA_DIR,
        collection_name: str = COLLECTION_NAME,
        model_name: str = EMBED_MODEL_NAME,
        voyage_client: voyageai.Client | None = None,
    ) -> None:
        chroma_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        # Voyage client is injectable so tests can pass a fake without
        # touching the network. In production the default client picks up
        # VOYAGE_API_KEY from the environment — we validate eagerly so a
        # missing key fails on startup, not on the first user question.
        if voyage_client is None:
            if not os.environ.get("VOYAGE_API_KEY"):
                raise RuntimeError(
                    "VOYAGE_API_KEY is not set. Add it to your .env file."
                )
            voyage_client = voyageai.Client()
        self._voyage = voyage_client
        self._model_name = model_name
        self._tables_by_name: dict[str, TableInfo] = {
            t["name"]: t for t in list_tables_metadata()
        }

    def _embed_texts(
        self, texts: list[str], input_type: str
    ) -> list[list[float]]:
        """Call Voyage to embed a batch of texts and log the call.

        Args:
            texts: Texts to embed. Documents at index time, the question
                at query time.
            input_type: Either "document" (for stored items) or "query"
                (for user questions). Voyage uses this hint to make the
                vectors of queries and documents align better in the
                vector space.

        Returns:
            One embedding (list of floats) per input text, in order.

        Raises:
            voyageai.error.VoyageError: Network or quota issues. We
                propagate so the UI surfaces the failure instead of
                silently returning poor results.
        """
        t0 = time.perf_counter()
        try:
            result = self._voyage.embed(
                texts,
                model=self._model_name,
                input_type=input_type,
                truncation=True,
            )
            success = True
            error_msg: str | None = None
            embeddings = result.embeddings
            total_tokens = result.total_tokens
        except Exception as exc:
            success = False
            error_msg = str(exc)
            embeddings = []
            total_tokens = 0
            raise
        finally:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log_call(
                model=self._model_name,
                input_tokens=total_tokens,
                output_tokens=0,
                latency_ms=latency_ms,
                success=success,
                error_msg=error_msg,
            )
        return embeddings

    def build_index(self, force: bool = False) -> None:
        """Embed and store one document per table.

        Args:
            force: If True, wipe the collection first. Use after schema
                changes or description edits.
        """
        if force:
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )

        indexed_ids = set(self._collection.get(include=[])["ids"])
        if indexed_ids == set(self._tables_by_name.keys()):
            return  # already indexed with the exact same tables

        ids: list[str] = []
        documents: list[str] = []
        for name, table in self._tables_by_name.items():
            description = TABLE_DESCRIPTIONS.get(name, "")
            columns_str = ", ".join(
                f"{c['name']} ({c['type']})" for c in table["columns"]
            )
            doc = f"Table: {name}\nDescription: {description}\nColumns: {columns_str}"
            ids.append(name)
            documents.append(doc)

        embeddings = self._embed_texts(documents, input_type="document")
        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
        )

    def retrieve(self, question: str, k: int = 5) -> list[RetrievedTable]:
        """Return the top-k tables most relevant to the question."""
        if self._collection.count() == 0:
            self.build_index()

        query_emb = self._embed_texts([question], input_type="query")
        result = self._collection.query(
            query_embeddings=query_emb,
            n_results=min(k, len(self._tables_by_name)),
        )

        retrieved: list[RetrievedTable] = []
        for table_id in result["ids"][0]:
            table = self._tables_by_name[table_id]
            retrieved.append(
                RetrievedTable(
                    name=table_id,
                    columns=table["columns"],
                    description=TABLE_DESCRIPTIONS.get(table_id, ""),
                )
            )
        return retrieved

    @staticmethod
    def format_for_prompt(tables: list[RetrievedTable]) -> str:
        """Render retrieved tables as a schema block for the LLM prompt."""
        blocks: list[str] = []
        for t in tables:
            cols = "\n".join(
                f"  - {c['name']} {c['type']}" + (" NOT NULL" if c["not_null"] else "")
                for c in t.columns
            )
            blocks.append(
                f"Table: {t.name}\nPurpose: {t.description}\nColumns:\n{cols}"
            )
        return "\n\n".join(blocks)


if __name__ == "__main__":
    r = SchemaRetriever()
    r.build_index()
    for q in [
        "How much did we sell in electronics last month?",
        "Which customers signed up in 2025?",
        "What payment methods are most popular?",
    ]:
        tables = r.retrieve(q, k=3)
        print(f"\nQ: {q}")
        print("  ->", [t.name for t in tables])

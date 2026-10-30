"""Векторное хранилище ChromaDB и ранжирование разрешённых чанков."""

from functools import lru_cache

import chromadb
import numpy as np

from .common import ROOT, cfg


BATCH_SIZE = 500


@lru_cache(maxsize=1)
def _client(path: str):
    """Создаёт постоянный клиент ChromaDB."""

    return chromadb.PersistentClient(path=path)


def collection():
    """Возвращает коллекцию векторного поиска."""

    path = ROOT / "data" / "chroma"
    path.mkdir(parents=True, exist_ok=True)

    return _client(str(path)).get_or_create_collection(
        name="chat_chunks",
        metadata={"hnsw:space": "cosine"},
    )


def embed(texts: list[str]) -> list[list[float]]:
    """Получает embeddings через настроенную модель Ollama."""

    if not texts:
        return []

    from src import llm

    result = llm.embed(
        model=cfg()["models"]["embed"],
        input=texts,
    )

    return result["embeddings"]


def upsert(chunks) -> None:
    """Добавляет или обновляет чанки в ChromaDB."""

    if not chunks:
        return

    col = collection()

    for start in range(0, len(chunks), 16):
        batch = chunks[start:start + 16]

        embeddings = embed([chunk.text for chunk in batch])

        col.upsert(
            ids=[chunk.id for chunk in batch],
            embeddings=embeddings,
            documents=[chunk.text for chunk in batch],
            metadatas=[
                {
                    "chat": chunk.chat,
                    "ts_from": chunk.ts_from,
                    "ts_to": chunk.ts_to,
                    "roles": ",".join(chunk.roles),
                    "msg_ids": ",".join(chunk.msg_ids),
                    "discipline": chunk.discipline or "",
                }
                for chunk in batch
            ],
        )


def _cosine_similarity(query_vector, vectors):
    """Считает cosine similarity для одного запроса и набора векторов."""

    query = np.asarray(query_vector, dtype=np.float32)
    matrix = np.asarray(vectors, dtype=np.float32)

    if query.ndim != 1:
        raise ValueError("Embedding запроса должен быть одномерным")

    if matrix.ndim != 2:
        raise ValueError("Embeddings документов должны быть двумерными")

    if matrix.shape[1] != query.shape[0]:
        raise ValueError(
            "Размерности embeddings запроса и документов не совпадают"
        )

    query_norm = np.linalg.norm(query)
    vector_norms = np.linalg.norm(matrix, axis=1)

    denominators = vector_norms * query_norm

    similarities = np.divide(
        matrix @ query,
        denominators,
        out=np.zeros(len(matrix), dtype=np.float32),
        where=denominators != 0,
    )

    return similarities


def rank(query: str, eligible, count: int = 20) -> list[tuple[str, float]]:
    """
    Ранжирует только разрешённые ID чанков.

    Возвращает список:
        [(chunk_id, cosine_similarity), ...]

    Чем выше score, тем ближе чанк к запросу.
    """

    if count <= 0 or not eligible:
        return []

    eligible_ids = sorted(set(eligible))

    if not eligible_ids:
        return []

    if not query or not query.strip():
        return []

    query_embeddings = embed([query])

    if not query_embeddings:
        return []

    query_vector = query_embeddings[0]

    col = collection()

    results = []

    for start in range(0, len(eligible_ids), BATCH_SIZE):
        batch_ids = eligible_ids[start:start + BATCH_SIZE]

        data = col.get(
            ids=batch_ids,
            include=["embeddings"],
        )

        found_ids = data.get("ids") or []
        found_embeddings = data.get("embeddings")

        if not found_ids or found_embeddings is None:
            continue

        if len(found_ids) != len(found_embeddings):
            raise ValueError(
                "ChromaDB вернула разное количество ID и embeddings"
            )

        similarities = _cosine_similarity(
            query_vector,
            found_embeddings,
        )

        for chunk_id, score in zip(found_ids, similarities):
            results.append((chunk_id, float(score)))

    results.sort(
        key=lambda item: (-item[1], item[0])
    )

    return results[:count]

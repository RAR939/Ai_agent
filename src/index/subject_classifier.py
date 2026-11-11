"""Assign a subject to messages that explicit aliases and reply links cannot resolve."""
from __future__ import annotations

import json
import warnings
from collections import defaultdict, deque
from typing import Sequence

from src.schemas import Message


def _chat(**kwargs):
    from src import llm
    return llm.chat(**kwargs)


def _content(response) -> str:
    if isinstance(response, dict):
        return response.get("message", {}).get("content", "") or ""
    return response.message.content or ""


def classify(messages: Sequence[Message], subjects: dict[str, str | None],
             config: dict) -> dict[str, str]:
    """Classify unresolved messages in batches; reject invalid or uncertain labels.

    A failed model call keeps existing rule-based labels and emits a warning.
    """
    settings = config["retrieval"]
    if not settings.get("subject_model_enabled", False):
        return {}
    unknown = [m for m in messages if subjects[m.id] is None]
    if not unknown:
        return {}
    allowed = list(config["disciplines"])
    threshold = float(settings.get("subject_model_min_confidence", 0.75))
    batch_size = max(1, int(settings.get("subject_model_batch_size", 20)))
    by_id = {m.id: m for m in messages}
    recent = defaultdict(lambda: deque(maxlen=2))
    preceding = {}
    for m in messages:
        preceding[m.id] = list(recent[m.chat])
        recent[m.chat].append(m)
    labels = {}
    schema = {
        "type": "object", "properties": {"labels": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "string"},
                "discipline": {"type": ["string", "null"], "enum": allowed + [None]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["id", "discipline", "confidence"]}}},
        "required": ["labels"]}
    names = ", ".join(f"{key} — {item['name']}" for key, item in config["disciplines"].items())
    system = ("Определи учебный предмет каждого сообщения. Доступные предметы: " + names +
              ". Верни JSON с labels: id, discipline, confidence (0..1). "
              "Если сообщение бытовое или предмет нельзя установить по тексту, ответу и контексту, "
              "верни discipline=null. Не угадывай по соседним несвязанным сообщениям. "
              "Для каждого id верни ровно одну запись.")
    for start in range(0, len(unknown), batch_size):
        batch = unknown[start:start + batch_size]
        payload = []
        for m in batch:
            parent = by_id.get(m.reply_to)
            payload.append({"id": m.id, "text": m.text,
                            "reply_to": ({"text": parent.text,
                                          "discipline": subjects[parent.id] or labels.get(parent.id)}
                                         if parent else None),
                            "previous": [{"text": p.text,
                                          "discipline": subjects[p.id] or labels.get(p.id)}
                                         for p in preceding[m.id]]})
        try:
            response = _chat(model=config["models"]["llm"],
                             messages=[{"role": "system", "content": system},
                                       {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                             format=schema, think=False, options={"temperature": 0})
            parsed = json.loads(_content(response))["labels"]
            if not isinstance(parsed, list):
                raise ValueError("labels is not a list")
        except Exception as exc:
            warnings.warn(f"Subject classification unavailable; remaining labels stay unknown: {exc}",
                          RuntimeWarning, stacklevel=2)
            break
        requested = {m.id for m in batch}
        for item in parsed:
            if not isinstance(item, dict) or item.get("id") not in requested:
                continue
            key = item.get("discipline")
            confidence = item.get("confidence")
            if (key in allowed and isinstance(confidence, (int, float)) and
                    not isinstance(confidence, bool) and threshold <= confidence <= 1):
                labels[item["id"]] = key
    return labels

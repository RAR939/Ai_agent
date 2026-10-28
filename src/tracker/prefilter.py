"""Роль 4 (задача 4.4): предфильтр. В модель идут только сообщения, где может быть срок.

Сообщение проходит, если в нём есть ключевое слово (по леммам, список в config.yaml)
И признак времени (дата, время, день недели, «завтра», «на паре» и т. п.).
Слова отмены и переноса проходят и без признака времени: «ДЗ 1 отменяется».
Отдельно проходят ответы на сообщения про задания, если в ответе есть признак времени:
«до пятницы» в ответ на «когда сдавать Лаб.2?» должно попасть в модель.
Ошибка «пропустили настоящий дедлайн» хуже, чем лишний вызов модели.
"""
import re
from functools import lru_cache
from typing import Mapping

from src.schemas import Message
from src.tracker import common

_MONTHS = ("январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр")
_DATE_RE = re.compile(r"(?<!\d)\d{1,2}[./]\d{1,2}(?!\d)")
_MONTH_DATE_RE = re.compile(rf"(?<!\d)\d{{1,2}}\s+(?:{_MONTHS})")
_CLOCK_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)|\b\d{1,2}\s*(?:час\w*|утра|вечера)\b")
_WORD_RE = re.compile(r"[a-zа-яё]+")


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3
    return pymorphy3.MorphAnalyzer()


def _fold(word: str) -> str:
    return word.lower().replace("ё", "е")


@lru_cache(maxsize=50000)
def lemma(word: str) -> str:
    """Начальная форма слова (ё заменено на е): сдаём -> сдавать, лабу -> лаба."""
    return _fold(_morph().parse(_fold(word))[0].normal_form)


def lemmas(text: str) -> set[str]:
    """Множество слов текста: и сами слова, и их начальные формы."""
    result: set[str] = set()
    for w in _WORD_RE.findall(text.lower()):
        result.add(_fold(w))
        result.add(lemma(w))
    return result


@lru_cache(maxsize=8)
def _vocab(words: tuple[str, ...]) -> frozenset[str]:
    out = set()
    for w in words:
        out.add(_fold(w))
        out.add(lemma(w))
    return frozenset(out)


def _keywords() -> frozenset[str]:
    return _vocab(tuple(common.tracker_cfg()["prefilter_keywords"]))


def _time_words() -> frozenset[str]:
    return _vocab(tuple(common.tracker_cfg()["prefilter_time_words"]))


def _strong_keywords() -> frozenset[str]:
    return _vocab(tuple(common.tracker_cfg()["prefilter_strong_keywords"]))


def has_strong_keyword(text: str) -> bool:
    return bool(lemmas(text) & _strong_keywords())


def has_keyword(text: str) -> bool:
    return bool(lemmas(text) & _keywords())


def has_time_marker(text: str) -> bool:
    low = text.lower()
    if _DATE_RE.search(low) or _MONTH_DATE_RE.search(low) or _CLOCK_RE.search(low):
        return True
    return bool(lemmas(text) & _time_words())


def looks_like_deadline(msg: Message, by_id: Mapping[str, Message] | None = None,
                        deadline_ids: set[str] | None = None) -> bool:
    """True, если сообщение стоит отправить в модель.

    by_id: сообщения чата по идентификатору (для правила про ответы);
    deadline_ids: сообщения, в которых модель уже нашла срок.
    """
    text = msg.text or ""
    if not text.strip():
        return False
    if has_strong_keyword(text):            # отмена и перенос бывают без даты
        return True
    timed = has_time_marker(text)
    if timed and has_keyword(text):
        return True
    if timed and msg.reply_to:
        if deadline_ids and msg.reply_to in deadline_ids:
            return True
        parent = by_id.get(msg.reply_to) if by_id else None
        if parent is not None and has_keyword(parent.text or ""):
            return True
    return False

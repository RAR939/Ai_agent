from scripts.make_search_experiment_chat import generate
from src.index.chunking import chunk_messages, discipline


def test_generated_chat_mixes_subjects_and_social_messages():
    chats, gold = generate()
    assert set(chats) == {"synthetic_group"}
    messages = chats["synthetic_group"]
    assert len(messages) == 390
    assert len(gold) == 82
    assert all(row["chat"] == "synthetic_group" for row in gold)
    ids = {message.id for message in messages}
    assert all(message.reply_to is None or message.reply_to in ids for message in messages)
    assert all(set(row["relevant_msg_ids"]) <= ids for row in gold)
    assert sum("тетрадь" in message.text or "зарядку" in message.text or
               "кофе" in message.text for message in messages) > 10
    assert len({message.text for message in messages}) == len(messages)
    assert all(9 <= int(message.ts[11:13]) <= 20 for message in messages)


def test_mixed_subject_chunks_keep_separate_labels(monkeypatch):
    from src.index import chunking
    from src.config import load_config
    config = load_config()
    config["retrieval"]["subject_model_enabled"] = False
    monkeypatch.setattr(chunking, "cfg", lambda: config)
    messages = generate()[0]["synthetic_group"]
    chunks = chunk_messages(messages)
    subjects = {message.id: discipline(message.text) for message in messages}
    for chunk in chunks:
        explicit = {subjects[mid] for mid in chunk.msg_ids if subjects[mid]}
        assert len(explicit) <= 1
        if explicit:
            assert chunk.discipline in explicit
    assert discipline("ЛР2 по электротехнике") == "elektro"
    assert discipline("ДЗ1 по алгоритмам") == "algo"
    assert discipline("По моделям данных") == "models"

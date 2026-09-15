import json
import os
from datetime import datetime, timezone

import chat_storage
from config import DIARY_ENABLED, LONG_TERM_MEMORY_ENABLED


def _memory_file(chat_id):
    return chat_storage.chat_path(chat_id, "memory.json")


def _transcript_file(chat_id):
    return chat_storage.chat_path(chat_id, "transcript_log.jsonl")


def _archive_file(chat_id):
    return chat_storage.chat_path(chat_id, "archive.jsonl")


def load_memory(chat_id):
    path = _memory_file(chat_id)
    if not os.path.exists(path):
        return {"history": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(chat_id, memory):
    with open(_memory_file(chat_id), "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def append_history(chat_id, user_text, reply_text, limit):
    memory = load_memory(chat_id)
    memory["history"].append({"role": "user", "content": user_text})
    memory["history"].append({"role": "assistant", "content": reply_text})
    memory["history"] = memory["history"][-limit * 2:]
    save_memory(chat_id, memory)

    # Полный лог, отдельно от урезанной истории выше - копится с прошлого
    # "сна" этого чата и очищается после рефлексии в diary.py. Если дневник
    # выключен, копить его незачем.
    if DIARY_ENABLED:
        append_transcript_entry(chat_id, "user", user_text)
        append_transcript_entry(chat_id, "assistant", reply_text)

    # Архив - в отличие от лога выше, НИКОГДА не очищается. Это то, что
    # recall.py ищет по ключевым словам, когда собеседник ссылается на
    # что-то за пределами текущего окна контекста.
    if LONG_TERM_MEMORY_ENABLED:
        append_archive_entry(chat_id, user_text, reply_text)


def append_transcript_entry(chat_id, role, content):
    entry = {
        "role": role,
        "content": content,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    with open(_transcript_file(chat_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_transcript(chat_id):
    path = _transcript_file(chat_id)
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def clear_transcript(chat_id):
    path = _transcript_file(chat_id)
    if os.path.exists(path):
        os.remove(path)


def append_archive_entry(chat_id, user_text, reply_text):
    entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "user": user_text,
        "assistant": reply_text,
    }
    with open(_archive_file(chat_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_archive(chat_id):
    path = _archive_file(chat_id)
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def get_context_messages(chat_id, limit):
    return load_memory(chat_id)["history"][-limit:]
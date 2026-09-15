import json
import logging
import os

import chat_storage

logger = logging.getLogger("mood")

# Три файла с промтами лежат прямо рядом с остальным кодом, без отдельной
# папки - они общие для всех чатов, это часть характера, а не памяти.
MODE_FILES = {
    "normal": "mood_normal.txt",
    "rp": "mood_rp.txt",
    "serious": "mood_serious.txt",
}

RP_KEYWORDS = [
]

SERIOUS_KEYWORDS = [
]


def _state_file(chat_id):
    return chat_storage.chat_path(chat_id, "mood_state.json")


def _load_state(chat_id):
    path = _state_file(chat_id)
    if not os.path.exists(path):
        return {"mode": "normal"}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(chat_id, state):
    with open(_state_file(chat_id), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _contains_any(text, keywords):
    text_low = text.lower()
    return any(kw in text_low for kw in keywords)


def _detect_mode(current_text):
    # серьёзный режим проверяется первым - если в сообщении одновременно
    # есть оба триггера, побеждает серьёзный
    if _contains_any(current_text, SERIOUS_KEYWORDS):
        return "serious"
    if _contains_any(current_text, RP_KEYWORDS):
        return "rp"
    return None


def get_mood_note(chat_id, current_text):
    state = _load_state(chat_id)
    previous_mode = state.get("mode", "normal")

    detected = _detect_mode(current_text)
    mode = detected or previous_mode
    _save_state(chat_id, {"mode": mode})

    if mode != previous_mode:
        logger.info("[%s] режим сменился: %s -> %s", chat_id, previous_mode, mode)

    path = MODE_FILES.get(mode, MODE_FILES["normal"])
    if not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return ""

    return content + "\n\n"
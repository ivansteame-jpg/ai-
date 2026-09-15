import asyncio
import json
import logging
import os
import random

import activity
import diary
import web_search
from config import (
    CURIOSITY_CHANCE,
    CURIOSITY_CHECK_INTERVAL_SECONDS,
    CURIOSITY_JITTER_SECONDS,
    OWNER_ID,
)
from ollama_client import ask_ollama

logger = logging.getLogger("curiosity")

NOTES_FILE = "curiosity_notes.json"
MAX_NOTES_SHOWN = 5

TOPIC_PROMPT_HEAD = (
    "У тебя есть немного свободного времени. Подумай, есть ли что-то, что "
    "тебе самой было бы интересно узнать или погуглить - не обязательно "
    "связанное с текущими задачами, просто из любопытства.\n\n"
)

TOPIC_PROMPT_TAIL = (
    "\n\nЕсли есть - ответь СТРОГО одной строкой в формате \"SEARCH: тема "
    "поиска\". Если сейчас не хочется ничего искать - ответь ровно словом "
    "NOTHING."
)

NOTE_PROMPT_TAIL = (
    "\n\nЗапиши для себя короткую заметку от первого лица - что узнала, "
    "что показалось интересным. Несколько предложений."
)


def _load_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_notes(notes):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def get_curiosity_note():
    notes = _load_notes()
    if not notes:
        return ""
    lines = [n["text"] for n in notes[-MAX_NOTES_SHOWN:]]
    return "Недавно тебе было интересно узнать:\n" + "\n\n".join(lines) + "\n\n"


async def _explore_once():
    context = diary.get_diary_note(OWNER_ID)
    prompt = context + TOPIC_PROMPT_HEAD + TOPIC_PROMPT_TAIL

    reply = await asyncio.to_thread(ask_ollama, [{"role": "user", "content": prompt}])

    if reply.strip().upper() == "NOTHING":
        logger.info("сейчас ничего не заинтересовало")
        return

    topic = reply.strip()
    if topic.upper().startswith("SEARCH:"):
        topic = topic[len("SEARCH:"):].strip()

    if not topic:
        return

    logger.info("любопытство привело к теме: \"%s\"", topic)
    results_text = await asyncio.to_thread(web_search.search, topic)

    note_prompt = (
        "Ты искала в интернете по теме \"" + topic + "\" и вот что нашла:\n\n"
        + (results_text or "ничего не нашлось")
        + NOTE_PROMPT_TAIL
    )
    note_text = await asyncio.to_thread(ask_ollama, [{"role": "user", "content": note_prompt}])

    notes = _load_notes()
    notes.append({"topic": topic, "text": note_text.strip()})
    _save_notes(notes)
    logger.info("записала для себя: \"%s\"", note_text.strip()[:60])


async def curiosity_loop():
    while True:
        jitter = random.uniform(-CURIOSITY_JITTER_SECONDS, CURIOSITY_JITTER_SECONDS)
        await asyncio.sleep(CURIOSITY_CHECK_INTERVAL_SECONDS + jitter)

        try:
            if activity.is_busy():
                logger.info("проверка любопытства пропущена - модель занята разговором")
                continue

            if random.random() > CURIOSITY_CHANCE:
                continue

            await _explore_once()
        except Exception as e:
            logger.error("сбой в проверке любопытства: %s", e)
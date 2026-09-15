import asyncio
import logging

import diary
import memory
from config import PROACTIVE_CHECKIN_MIN_EXCHANGES
from ollama_client import ask_ollama
from telegram_client import client

logger = logging.getLogger("checkin")

CHECKIN_PROMPT_TAIL = (
    "\n\nЕсли, судя по этому, тебе хочется написать первой - что-то по "
    "поводу того, о чём говорили, или просто поинтересоваться, как дела "
    "- ответь текстом самого сообщения, обычным текстом, как будто "
    "пишешь прямо сейчас. Если не хочется писать первой сейчас - ответь "
    "ровно словом NOTHING."
)


def _is_eligible(chat_id):
    """Настоящий разговор - минимум N обменов репликами, а не разовое
    сообщение. history уже парами [user, assistant], отсюда деление на 2."""
    history = memory.load_memory(chat_id)["history"]
    return len(history) // 2 >= PROACTIVE_CHECKIN_MIN_EXCHANGES


async def maybe_check_in(chat_id, idle_hours):
    if not _is_eligible(chat_id):
        return False

    diary_note = diary.get_diary_note(chat_id)
    prompt = (
        diary_note
        + "Ты не общалась с этим собеседником уже примерно "
        + str(round(idle_hours))
        + " часов."
        + CHECKIN_PROMPT_TAIL
    )

    reply = await asyncio.to_thread(ask_ollama, [{"role": "user", "content": prompt}])

    if reply.strip().upper() == "NOTHING":
        logger.info("[%s] решила пока не писать первой", chat_id)
        return False

    try:
        await client.send_message(chat_id, reply.strip())
        logger.info("[%s] написала первой: \"%s\"", chat_id, reply.strip()[:60])
        return True
    except Exception as e:
        logger.error("[%s] не удалось написать первой: %s", chat_id, e)
        return False
import asyncio
import logging
import random

import activity
import diary
import vision
from config import (
    MONITORED_CHANNELS,
    OWNER_ID,
    PROACTIVE_CHECK_INTERVAL_SECONDS,
    PROACTIVE_JITTER_SECONDS,
    PROACTIVE_MESSAGES_PER_CHANNEL,
    PROACTIVE_SHARE_CHANCE,
    PROACTIVE_TARGET_ID,
    VISION_ENABLED,
)
from ollama_client import ask_ollama
from telegram_client import client

logger = logging.getLogger("proactive")

REACTION_PROMPT_HEAD = (
    "Ты увидела этот пост в Telegram:\n\n"
)

REACTION_PROMPT_TAIL = (
   "\n\nЕсли у тебя возникло естественное желание переслать это собеседнику, "
    "напиши только то сообщение, которое отправила бы вместе с постом. "
    "Если желания не возникло, ответь ровно NOTHING."
)


async def _fetch_candidates():
    """Последние сообщения из отслеживаемых каналов. Канал, который
    оказался недоступен, просто пропускается - одна ошибка не должна
    валить всю проверку."""
    candidates = []
    for channel in MONITORED_CHANNELS:
        try:
            messages = await client.get_messages(channel, limit=PROACTIVE_MESSAGES_PER_CHANNEL)
            for m in messages:
                if m.text or m.photo or m.video:
                    candidates.append(m)
        except Exception:
            continue
    return candidates


async def _pick_candidate():
    candidates = await _fetch_candidates()
    if not candidates:
        return None
    return random.choice(candidates)


async def _describe(message):
    if message.photo and VISION_ENABLED:
        try:
            image_bytes = await message.download_media(bytes)
            seen = await asyncio.to_thread(vision.describe_image, image_bytes, message.text)
        except Exception:
            seen = "не удалось разобрать изображение"
        if message.text:
            return "[изображение: " + seen + "] Подпись: " + message.text
        return "[изображение: " + seen + "]"
    if message.photo:
        if message.text:
            return "[изображение без описания] Подпись: " + message.text
        return "[изображение без описания]"
    if message.text:
        return message.text
    return "[вложение]"


async def _maybe_share_once():
    message = await _pick_candidate()
    if message is None:
        logger.info("нечего показать - каналы пусты или недоступны")
        return

    context_note = diary.get_diary_note(OWNER_ID)

    description = await _describe(message)
    prompt = context_note + REACTION_PROMPT_HEAD + description + REACTION_PROMPT_TAIL
    comment = await asyncio.to_thread(ask_ollama, [{"role": "user", "content": prompt}])

    if comment.strip().upper() == "NOTHING":
        logger.info("нашла что-то, но решила не делиться: \"%s\"", description[:60])
        return

    try:
        await client.forward_messages(PROACTIVE_TARGET_ID, message)
        await asyncio.sleep(random.uniform(1.5, 4))
        await client.send_message(PROACTIVE_TARGET_ID, comment.strip())
        logger.info("поделилась и написала: \"%s\"", comment.strip()[:60])
    except Exception as e:
        logger.error("не получилось отправить: %s", e)


async def proactive_loop():
    while True:
        jitter = random.uniform(-PROACTIVE_JITTER_SECONDS, PROACTIVE_JITTER_SECONDS)
        await asyncio.sleep(PROACTIVE_CHECK_INTERVAL_SECONDS + jitter)

        try:
            if activity.is_busy():
                logger.info("проверка каналов пропущена - модель занята разговором")
                continue

            if random.random() > PROACTIVE_SHARE_CHANCE:
                logger.info("проверка каналов - шанс не выпал")
                continue

            logger.info("проверка каналов - шанс выпал, смотрю что там")
            await _maybe_share_once()
        except Exception as e:
            logger.error("сбой в проактивной проверке: %s", e)
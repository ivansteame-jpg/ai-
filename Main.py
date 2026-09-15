import asyncio
import logging
import os
import random
import sys
from logging.handlers import TimedRotatingFileHandler

# supervisor.py запускает этот файл тем же интерпретатором, что и себя -
# если это pythonw.exe (без консоли), sys.stdout/stderr бывают None.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from colorama import Fore, Style
from colorama import init as colorama_init
from telethon import events

import activity
import curiosity
import diary
import files
import memory
import mood
import proactive
import qa
import recall
import vision
import web_search
from config import (
    BLOCKED_SENDER_IDS,
    CURIOSITY_ENABLED,
    DIARY_ENABLED,
    FILES_ENABLED,
    HISTORY_LIMIT,
    BUFFER_DELAY,
    IDLE_HOURS_BEFORE_SLEEP,
    LONG_DELAY_CHANCE,
    LONG_DELAY_RANGE,
    LONG_TERM_MEMORY_ENABLED,
    MONITORED_CHANNELS,
    MOOD_ENABLED,
    OLLAMA_MODEL,
    OWNER_ID,
    PARAGRAPH_DELAY,
    PROACTIVE_CHECKIN_ENABLED,
    PROACTIVE_CHECKIN_HOURS,
    PROACTIVE_ENABLED,
    QA_CONTEXT_MESSAGES,
    QA_ENABLED,
    SHORT_DELAY_RANGE,
    VISION_ENABLED,
    WEB_SEARCH_ENABLED,
)
from ollama_client import ask_ollama
from telegram_client import client

# ---------- логирование: цвет в консоли, файл в отдельной папке ----------

colorama_init()

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.ERROR: Fore.RED,
        logging.WARNING: Fore.YELLOW,
    }

    def format(self, record):
        message = super().format(record)
        color = self.COLORS.get(record.levelno)
        return color + message + Style.RESET_ALL if color else message


_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_ColorFormatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))

# Один файл в день, храним последние 10 - более старые удаляются сами
_file_handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "assistant.log"),
    when="midnight",
    backupCount=10,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger("main")


def _preview(text, limit=60):
    text = text.replace("\n", " ").strip()
    return text[:limit] + "…" if len(text) > limit else text

# ---------- имитация живого присутствия (бывший presence.py) ----------


async def _wait_before_reply():
    if random.random() < LONG_DELAY_CHANCE:
        delay = random.uniform(*LONG_DELAY_RANGE)
    else:
        delay = random.uniform(*SHORT_DELAY_RANGE)
    await asyncio.sleep(delay)


async def _mark_read(chat, message):
    try:
        await client.send_read_acknowledge(chat, message=message)
    except Exception:
        pass  # не критично - просто не появится галочка прочтения


# ---------- отправка ответа по параграфам (бывший sender.py) ----------

TELEGRAM_LIMIT = 4000  # реальный жёсткий лимит Telegram - 4096, с запасом


def _split_hard(text):
    if len(text) <= TELEGRAM_LIMIT:
        return [text]
    return [text[i:i + TELEGRAM_LIMIT] for i in range(0, len(text), TELEGRAM_LIMIT)]


async def _send_by_paragraphs(chat, text):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return
    for paragraph in paragraphs:
        for chunk in _split_hard(paragraph):
            await client.send_message(chat, chunk)
            await asyncio.sleep(random.uniform(PARAGRAPH_DELAY * 0.6, PARAGRAPH_DELAY * 1.6))


# ---------- обработка сообщений ----------

# Буферы и таймеры на каждый чат отдельно - сообщения из разных бесед
# не должны перемешиваться в один поток.
_buffers = {}
_buffer_tasks = {}


async def process_message(event, chat_id, full_text):
    chat = await event.get_chat()

    await _wait_before_reply()
    await _mark_read(chat, event.message)

    recent = memory.get_context_messages(chat_id, HISTORY_LIMIT)
    diary_note = diary.get_diary_note(chat_id) if DIARY_ENABLED else ""
    mood_note = mood.get_mood_note(chat_id, full_text) if MOOD_ENABLED else ""
    curiosity_note = curiosity.get_curiosity_note() if CURIOSITY_ENABLED else ""

    base_note = diary_note + mood_note + curiosity_note

    is_owner = chat_id == OWNER_ID

    messages = list(recent)
    search_instruction = web_search.SEARCH_INSTRUCTION if WEB_SEARCH_ENABLED else ""
    files_instruction = files.FILES_INSTRUCTION if (FILES_ENABLED and is_owner) else ""
    recall_instruction = recall.RECALL_INSTRUCTION if LONG_TERM_MEMORY_ENABLED else ""
    messages.append({
        "role": "user",
        "content": search_instruction + files_instruction + recall_instruction + base_note + full_text,
    })

    activity.set_busy(True)
    logger.info("[%s] отправляю в модель: \"%s\"", chat_id, _preview(full_text))
    try:
        async with client.action(chat, "typing"):
            reply = await asyncio.to_thread(ask_ollama, messages)

            if WEB_SEARCH_ENABLED and web_search.needs_search(reply):
                query = web_search.extract_query(reply, full_text)
                logger.info("[%s] запросила поиск: \"%s\"", chat_id, query)
                results_text = await asyncio.to_thread(web_search.search, query)
                followup_note = web_search.build_followup_note(query, results_text)

                second_messages = list(recent)
                second_messages.append({
                    "role": "user",
                    "content": base_note + followup_note + full_text,
                })
                reply = await asyncio.to_thread(ask_ollama, second_messages)

            elif is_owner and FILES_ENABLED and files.needs_listdir(reply):
                path = files.extract_listdir_path(reply)
                logger.info("[%s] запросила листинг папки: \"%s\"", chat_id, path)
                listing, error = files.list_directory(path)
                listdir_note = files.build_listdir_note(path, listing, error)

                second_messages = list(recent)
                second_messages.append({
                    "role": "user",
                    "content": base_note + listdir_note + full_text,
                })
                reply = await asyncio.to_thread(ask_ollama, second_messages)

            elif is_owner and FILES_ENABLED and files.needs_sendfile(reply):
                path = files.extract_sendfile_path(reply)
                logger.info("[%s] отправляет файл: \"%s\"", chat_id, path)
                if os.path.isfile(path):
                    try:
                        await client.send_file(chat, path)
                        reply = "Готово, отправила: " + os.path.basename(path)
                    except Exception as e:
                        logger.error("[%s] не удалось отправить файл: %s", chat_id, e)
                        reply = "Не получилось отправить файл: " + str(e)
                else:
                    reply = "Не нашла такой файл: " + path

            elif LONG_TERM_MEMORY_ENABLED and recall.needs_recall(reply):
                query = recall.extract_query(reply, full_text)
                logger.info("[%s] вспоминает по запросу: \"%s\"", chat_id, query)
                snippets = recall.search(chat_id, query)
                recall_note = recall.build_recall_note(query, snippets)

                second_messages = list(recent)
                second_messages.append({
                    "role": "user",
                    "content": base_note + recall_note + full_text,
                })
                reply = await asyncio.to_thread(ask_ollama, second_messages)
    except Exception as e:
        logger.error("[%s] ошибка при обращении к модели: %s", chat_id, e)
        await client.send_message(chat, "Ошибка при обращении к модели: " + str(e))
        return
    finally:
        activity.set_busy(False)

    logger.info("[%s] ответ: \"%s\"", chat_id, _preview(reply))
    if QA_ENABLED:
        qa_context = recent[-QA_CONTEXT_MESSAGES:]
        ok, detail = await asyncio.to_thread(qa.evaluate, qa_context, full_text, reply)
        if ok is None:
            logger.warning("[%s] QA не дала чёткого вердикта: %s", chat_id, detail or "(пусто)")
        elif ok:
            logger.info("[%s] QA: ок - %s", chat_id, detail)
        else:
            logger.warning("[%s] QA нашла проблемы: %s", chat_id, detail)

    memory.append_history(chat_id, full_text, reply, HISTORY_LIMIT)
    await _send_by_paragraphs(chat, reply)


async def _debounced_flush(event, chat_id):
    try:
        await asyncio.sleep(BUFFER_DELAY)
    except asyncio.CancelledError:
        return
    full_text = "\n".join(_buffers.pop(chat_id, []))
    _buffer_tasks.pop(chat_id, None)
    await process_message(event, chat_id, full_text)


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.is_private:
        return  # групповые чаты пока не обрабатываем

    sender_id = event.sender_id
    if sender_id in BLOCKED_SENDER_IDS:
        return

    chat_id = event.chat_id
    activity.touch(chat_id)

    message = event.message

    try:
        if message.voice and VISION_ENABLED:
            logger.info("[%s] пришло голосовое, расшифровываю через Gemini", chat_id)
            audio_bytes = await message.download_media(bytes)
            transcript = await asyncio.to_thread(vision.transcribe_audio, audio_bytes)
            text = "[голосовое сообщение] " + transcript
        elif message.voice:
            return  # голосовые без зрения понять нечем - реагировать не на что
        elif message.photo and VISION_ENABLED:
            caption = event.raw_text or ""
            logger.info("[%s] пришло изображение, разбираю через Gemini", chat_id)
            image_bytes = await message.download_media(bytes)
            description = await asyncio.to_thread(vision.describe_image, image_bytes, caption)

            text = "[собеседник прислал изображение. Вот что на нём: " + description + "]"
            if caption:
                text += "\nПодпись: " + caption
        elif message.photo:
            caption = event.raw_text or ""
            if not caption:
                return  # картинка без подписи, а зрение выключено - реагировать не на что
            text = caption
        else:
            text = event.raw_text or ""
            if not text:
                return  # не текст и не фото - пока не обрабатываем
    except Exception as e:
        logger.error("[%s] не удалось обработать вложение: %s", chat_id, e)
        return

    logger.info("[%s] получено: \"%s\"", chat_id, _preview(text))

    _buffers.setdefault(chat_id, []).append(text)
    if chat_id in _buffer_tasks:
        _buffer_tasks[chat_id].cancel()
    _buffer_tasks[chat_id] = asyncio.create_task(_debounced_flush(event, chat_id))


def _print_startup_banner():
    def _flag(value):
        return "включено" if value else "выключено"

    print("=" * 60)
    print("Ассистент запущен")
    print("Модель: " + OLLAMA_MODEL)
    print(
        "Настроение: " + _flag(MOOD_ENABLED)
        + " | Дневник: " + _flag(DIARY_ENABLED)
        + (" (сон через " + str(IDLE_HOURS_BEFORE_SLEEP) + "ч простоя)" if DIARY_ENABLED else "")
    )
    print(
        "Проактивность: " + _flag(PROACTIVE_ENABLED)
        + (" (" + str(len(MONITORED_CHANNELS)) + " канал(ов))" if PROACTIVE_ENABLED else "")
        + " | Зрение: " + _flag(VISION_ENABLED)
        + " | Веб-поиск: " + _flag(WEB_SEARCH_ENABLED)
    )
    print(
        "Пишет первой: " + _flag(PROACTIVE_CHECKIN_ENABLED)
        + (" (через " + str(PROACTIVE_CHECKIN_HOURS) + "ч молчания)" if PROACTIVE_CHECKIN_ENABLED else "")
        + " | Любопытство: " + _flag(CURIOSITY_ENABLED)
    )
    print("Для остановки: Ctrl+C")
    print("=" * 60)


if __name__ == "__main__":
    _print_startup_banner()
    client.start()
    if DIARY_ENABLED or PROACTIVE_CHECKIN_ENABLED:
        client.loop.create_task(activity.idle_watcher_loop())
    if PROACTIVE_ENABLED:
        client.loop.create_task(proactive.proactive_loop())
    if CURIOSITY_ENABLED:
        client.loop.create_task(curiosity.curiosity_loop())
    client.loop.create_task(activity.heartbeat_loop())

    try:
        client.run_until_disconnected()
    except KeyboardInterrupt:
        print("\nОстанавливаюсь...")

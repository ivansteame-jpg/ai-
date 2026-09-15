import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import chat_storage
import checkin
import diary
from config import (
    DIARY_ENABLED,
    HEARTBEAT_INTERVAL_SECONDS,
    IDLE_CHECK_INTERVAL_SECONDS,
    IDLE_HOURS_BEFORE_SLEEP,
    PROACTIVE_CHECKIN_ENABLED,
    PROACTIVE_CHECKIN_HOURS,
)

logger = logging.getLogger("activity")
heartbeat_logger = logging.getLogger("heartbeat")

REGISTRY_FILE = "chats_registry.json"

# Счётчик занятости моделью - несколько чатов могут одновременно к ней
# обращаться, поэтому это счётчик, а не просто True/False.
_busy_count = 0


def set_busy(value):
    global _busy_count
    if value:
        _busy_count += 1
    else:
        _busy_count = max(0, _busy_count - 1)


def is_busy():
    return _busy_count > 0


def _load_registry():
    if not os.path.exists(REGISTRY_FILE):
        return []
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(chat_ids):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(chat_ids, f, ensure_ascii=False, indent=2)


def _register_chat(chat_id):
    chat_ids = _load_registry()
    if chat_id not in chat_ids:
        chat_ids.append(chat_id)
        _save_registry(chat_ids)


def _state_file(chat_id):
    return chat_storage.chat_path(chat_id, "activity_state.json")


def _load_state(chat_id):
    path = _state_file(chat_id)
    if not os.path.exists(path):
        return {"last_activity": None, "reflected": False, "checked_in": False}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_state(chat_id, state):
    with open(_state_file(chat_id), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def touch(chat_id):
    """Вызывается при любом сообщении в этом чате - сбрасывает таймер
    бездействия и регистрирует чат, если он новый."""
    _register_chat(chat_id)
    _save_state(chat_id, {
        "last_activity": datetime.now(timezone.utc).isoformat(),
        "reflected": False,
        "checked_in": False,
    })


def hours_idle(chat_id):
    state = _load_state(chat_id)
    if not state.get("last_activity"):
        return 0
    last = datetime.fromisoformat(state["last_activity"])
    now = datetime.now(timezone.utc)
    return (now - last).total_seconds() / 3600


def mark_reflected(chat_id):
    state = _load_state(chat_id)
    state["reflected"] = True
    _save_state(chat_id, state)


def mark_checked_in(chat_id):
    state = _load_state(chat_id)
    state["checked_in"] = True
    _save_state(chat_id, state)


async def idle_watcher_loop():
    """Фоновая задача - раз в IDLE_CHECK_INTERVAL_SECONDS обходит все
    известные чаты и проверяет, не пора ли кому-то из них "уснуть" или
    написать первой. Сбой на одной итерации не должен останавливать весь
    цикл навсегда - без этого один сетевой сбой тихо отключил бы обе
    функции до перезапуска."""
    while True:
        await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)

        try:
            for chat_id in _load_registry():
                state = _load_state(chat_id)
                idle = hours_idle(chat_id)

                if DIARY_ENABLED and not state.get("reflected") and idle >= IDLE_HOURS_BEFORE_SLEEP:
                    logger.info("[%s] бездействует %.1fч - начинаю сон", chat_id, idle)
                    await asyncio.to_thread(diary.write_entry, chat_id)
                    mark_reflected(chat_id)

                if PROACTIVE_CHECKIN_ENABLED and not state.get("checked_in") and idle >= PROACTIVE_CHECKIN_HOURS:
                    await checkin.maybe_check_in(chat_id, idle)
                    mark_checked_in(chat_id)
        except Exception as e:
            logger.error("сбой в проверке бездействия: %s", e)


async def heartbeat_loop():
    """Фоновая задача - раз в HEARTBEAT_INTERVAL_SECONDS пишет в лог,
    что процесс жив, даже если давно не было реальных событий."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            chat_count = len(_load_registry())
            heartbeat_logger.info("жива, %d чатов активно", chat_count)
        except Exception as e:
            heartbeat_logger.error("сбой пульса: %s", e)
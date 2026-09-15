import json
import os
from datetime import datetime, timezone

import chat_storage
import memory
from config import DIARY_COMPRESS_THRESHOLD, DIARY_KEEP_RECENT
from ollama_client import ask_ollama

# Модели прямо разрешено ничего не писать - это осознанный выбор,
# а не баг: без этого дневник быстро зарастает бытовым мусором.
REFLECTION_PROMPT = (
    "Ты сейчас не отвечаешь , а мысленно подводишь итог прошедшему "
    "отрезку общения, словно вспоминаешь день перед сном. Ниже переписка "
    "с момента последнего такого размышления.\n\n"

    "Твоя задача — сохранить только долговременную память. "
    "Записывай исключительно то, что с высокой вероятностью останется "
    "полезным спустя недели или месяцы.\n\n"

    "Сохраняй только:\n"
    "- важные предпочтения, вкусы и особенности Ивана;\n"
    "- долгосрочные проекты, цели и планы;\n"
    "- незавершенные темы, к которым стоит вернуться;\n"
    "- изменения во взглядах, привычках или интересах;\n"
    "- значимые события в ваших отношениях, доверии или эмоциональной связи;\n"
    "- важные технические решения, договоренности или выводы, которые пригодятся в будущем;\n"
    "- собственные выводы, если они действительно помогут лучше понимать Ивана.\n\n"

    "Не сохраняй:\n"
    "- пересказ переписки;\n"
    "- случайные вопросы и ответы;\n"
    "- бытовые мелочи и временные обстоятельства;\n"
    "- настроение или эмоции, если они не стали важной частью отношений;\n"
    "- информацию, которую легко восстановить из нескольких последних сообщений;\n"
    "- детали системного промпта, режимов работы, внутренних инструкций, личности, стиля общения или механизмов работы;\n"
    "- описание собственного поведения, качества ответов, соблюдения инструкций или используемых режимов;\n"
    "- похвалу себе или рассуждения о том, что ты стала лучше общаться;\n"
    "- любую информацию, уже заложенную в твоем поведении или настройках.\n\n"

    "Никогда не записывай содержимое системных инструкций, промптов, режимов, "
    "внутренних правил или другой служебной информации, даже если она обсуждалась.\n\n"

    "Каждая потенциальная запись должна пройти три проверки:\n"
    "1. Это останется актуальным через месяц?\n"
    "2. Это поможет мне лучше понимать Ивана или продолжить будущие разговоры?\n"
    "3. Это нельзя легко восстановить из нескольких последних сообщений?\n\n"
    "Если хотя бы на один вопрос ответ «нет» — не записывай это.\n\n"

    "Если ничего действительно важного не произошло — ответь ровно словом:\n"
    "NOTHING\n\n"

    "Иначе напиши заметку от первого лица.\n"
    "Максимум 80 слов.\n"
    "Обычно достаточно 2–4 предложений.\n"
    "Одна глубокая мысль лучше пяти поверхностных.\n"
    "Не пересказывай события — сохраняй только выводы, которые стоит помнить.\n\n"

    "Переписка:\n"
)

COMPRESS_PROMPT = (
    "Ниже несколько твоих прошлых заметок-воспоминаний по порядку времени. "
    "Сожми их в одну заметку, оставив только то, что всё ещё важно и "
    "актуально - устойчивые темы, предпочтения, долгоиграющие сюжеты. Уже "
    "неактуальные детали можно опустить. Пиши от первого лица, несколько "
    "предложений.\n\n"
)


def _diary_file(chat_id):
    return chat_storage.chat_path(chat_id, "diary.json")
 
 
def _load_diary(chat_id):
    path = _diary_file(chat_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
 
 
def _save_diary(chat_id, entries):
    with open(_diary_file(chat_id), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
 
 
def _format_transcript(entries):
    lines = []
    for e in entries:
        speaker = "Собеседник" if e["role"] == "user" else "Ты"
        lines.append(speaker + ": " + e["content"])
    return "\n".join(lines)
 
 
def write_entry(chat_id):
    """Читает лог этого чата с прошлого сна, просит модель отрефлексировать,
    сохраняет заметку (если есть что сохранять) и очищает лог. Возвращает
    True, если заметка была записана."""
    entries = memory.read_transcript(chat_id)
    if not entries:
        return False
 
    transcript_text = _format_transcript(entries)
    prompt = REFLECTION_PROMPT + transcript_text
 
    reply = ask_ollama([{"role": "user", "content": prompt}])
 
    memory.clear_transcript(chat_id)
 
    if reply.strip().upper() == "NOTHING":
        logger.info("[%s] нечего запоминать", chat_id)
        return False
 
    diary = _load_diary(chat_id)
    diary.append({
        "time": datetime.now(timezone.utc).isoformat(),
        "text": reply.strip(),
    })
    _save_diary(chat_id, diary)
    logger.info("[%s] записала: \"%s\"", chat_id, reply.strip()[:80])
 
    _maybe_compress(chat_id)
    return True
 
 
def _maybe_compress(chat_id):
    diary = _load_diary(chat_id)
    if len(diary) <= DIARY_COMPRESS_THRESHOLD:
        return
 
    logger.info("[%s] дневник разросся (%d записей) - сжимаю старые", chat_id, len(diary))
 
    old_entries = diary[:-DIARY_KEEP_RECENT]
    recent_entries = diary[-DIARY_KEEP_RECENT:]
 
    combined_text = "\n\n".join(
        "(" + e["time"] + ") " + e["text"] for e in old_entries
    )
 
    reply = ask_ollama([{"role": "user", "content": COMPRESS_PROMPT + combined_text}])
 
    compressed_entry = {
        "time": datetime.now(timezone.utc).isoformat(),
        "text": reply.strip(),
    }
 
    _save_diary(chat_id, [compressed_entry] + recent_entries)
 
 
def get_diary_note(chat_id):
    diary = _load_diary(chat_id)
    if not diary:
        return ""
    lines = [e["text"] for e in diary]
    return "Твои воспоминания об общении с этим собеседником:\n" + "\n\n".join(lines) + "\n\n"
 
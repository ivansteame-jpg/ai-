import logging

from google import genai

logger = logging.getLogger("qa")

# Получить бесплатный ключ: https://aistudio.google.com/apikey
# Можно вписать тот же ключ, что и в vision.py, либо отдельный.
API_KEY = "ВСТАВЬ_СЮДА_GEMINI_API_KEY"
MODEL = "gemini-2.0-flash"

CHARACTER_FILE = "qa_character.txt"

# Просим не жёсткий JSON, а одно ключевое слово первой строкой - Gemini
# гораздо надёжнее соблюдает такой формат, чем строгую схему, и при этом
# не приходится жертвовать развёрнутым объяснением, которое реально
# полезно при отладке промтов.
PROMPT_TEMPLATE = """Character:
{character}

Conversation:
{conversation}

Candidate response:
{response}

Evaluate ONLY:
1. does it match the character;
2. does it match the context;
3. does it contradict itself;
4. is there an obvious hallucination.

Start your reply with exactly one word on its own first line: OK or ISSUES.
Then, on the following lines, briefly explain your reasoning in your own
words - this explanation is for a developer debugging prompts, so be
specific and concrete about what's wrong (or confirm what's right).

Do not rewrite the response.
Do not produce an alternative response.
Do not apply your own personality or communication style.
"""

_client = genai.Client(api_key=API_KEY)


def _load_character():
    try:
        with open(CHARACTER_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _format_conversation(recent_messages, current_text):
    lines = []
    for m in recent_messages:
        speaker = "User" if m["role"] == "user" else "Assistant"
        lines.append(speaker + ": " + m["content"])
    lines.append("User: " + current_text)
    return "\n".join(lines)


def evaluate(recent_messages, current_text, candidate_reply):
    """Возвращает (ok, detail). ok=None означает, что проверка не дала
    чёткого вердикта (сбой Gemini, либо ответ не начался с OK/ISSUES) -
    это НЕ означает, что сам ответ плохой, просто его не удалось разобрать.
    detail - текст объяснения от Gemini как есть, без попытки впихнуть
    его в строгую структуру. Решение о том, отправлять ли ответ
    собеседнику, эта функция не принимает - только сообщает."""
    character = _load_character() or "(не задан)"
    conversation = _format_conversation(recent_messages, current_text)

    prompt = PROMPT_TEMPLATE.format(
        character=character,
        conversation=conversation,
        response=candidate_reply,
    )

    try:
        response = _client.models.generate_content(model=MODEL, contents=prompt)
        text = (response.text or "").strip()
    except Exception as e:
        logger.warning("проверка через Gemini не удалась: %s", e)
        return None, ""

    if not text:
        return None, ""

    first_line, _, rest = text.partition("\n")
    verdict = first_line.strip().upper()
    detail = rest.strip()

    if verdict.startswith("OK"):
        return True, detail
    if verdict.startswith("ISSUES"):
        return False, detail

    # не соблюла формат - вердикт неясен, но сам текст всё равно
    # полезен, отдаём его целиком, а не выбрасываем
    return None, text
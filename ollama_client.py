import logging
import time

import requests

from config import OLLAMA_URL, OLLAMA_MODEL

logger = logging.getLogger("ollama_client")

# Если Ollama временно недоступна (например, ещё не успела запуститься
# после старта скрипта, или ПК только что вышел из сна) - пробуем ещё
# несколько раз, прежде чем сдаться и показать ошибку.
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def ask_ollama(messages):
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                },
                timeout=180,
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except requests.exceptions.ConnectionError as e:
            last_error = e
            logger.warning(
                "Ollama недоступна (попытка %d/%d)", attempt + 1, MAX_RETRIES
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY_SECONDS)

    raise last_error
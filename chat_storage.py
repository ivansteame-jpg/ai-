import os

CHATS_DIR = "chats"


def chat_path(chat_id, filename):
    """Возвращает путь к файлу внутри папки конкретного чата, создавая
    папку при необходимости. Например chat_path(12345, "memory.json")
    -> "chats/12345/memory.json"."""
    chat_dir = os.path.join(CHATS_DIR, str(chat_id))
    os.makedirs(chat_dir, exist_ok=True)
    return os.path.join(chat_dir, filename)
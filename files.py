import os

# Подмешивается только в чат с владельцем (проверка - в main.py).
# Модель сама решает, когда это нужно - без ручных команд, тем же
# способом, что и веб-поиск.
FILES_INSTRUCTION = (
    "Если владелец просит посмотреть содержимое папки на его компьютере - "
    "ответь СТРОГО одной строкой в формате \"LISTDIR: путь\", без пояснений "
    "и без ничего больше. Если просит прислать конкретный файл - ответь "
    "СТРОГО одной строкой в формате \"SENDFILE: полный путь к файлу\", без "
    "ничего больше. Иначе отвечай как обычно.\n\n"
)


def needs_listdir(reply_text):
    return reply_text.strip().upper().startswith("LISTDIR:")


def needs_sendfile(reply_text):
    return reply_text.strip().upper().startswith("SENDFILE:")


def extract_listdir_path(reply_text):
    return reply_text.strip()[len("LISTDIR:"):].strip()


def extract_sendfile_path(reply_text):
    return reply_text.strip()[len("SENDFILE:"):].strip()


def _human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024:
            return "{:.0f}{}".format(size, unit) if unit == "Б" else "{:.1f}{}".format(size, unit)
        size /= 1024
    return "{:.1f}ТБ".format(size)


def list_directory(path):
    """Только чтение - os.scandir ничего не меняет и не удаляет."""
    if not os.path.isdir(path):
        return None, "папка не найдена"

    try:
        entries = []
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    entries.append("[папка] " + entry.name)
                else:
                    size = _human_size(entry.stat().st_size)
                    entries.append("[файл] " + entry.name + " - " + size)
        entries.sort()
        return ("\n".join(entries) if entries else "(папка пуста)"), None
    except Exception as e:
        return None, str(e)


def build_listdir_note(path, listing, error):
    if error:
        return (
            "Не получилось открыть папку \"" + path + "\": " + error + ". "
            "Сообщи об этом собеседнику своими словами, не выдумывай содержимое.\n\n"
        )
    return (
        "Содержимое папки \"" + path + "\":\n" + listing
        + "\n\nОпиши это собеседнику обычным текстом, коротко.\n\n"
    )

import os
import socket
from functools import wraps

from flask import Flask, Response, redirect, render_template_string, request, url_for

PORT = 8765

# 0.0.0.0 = доступна с любого устройства в локальной сети, не только с
# этого ПК. Если нужно вернуть доступ только с этого компьютера - смени
# обратно на "127.0.0.1".
HOST = "0.0.0.0"

# Обязательно смени на свой пароль - раз панель теперь видна в локальной
# сети, а не только с этого ПК, без пароля кто угодно на той же сети
# сможет останавливать и перезапускать ассистента.
DASHBOARD_PASSWORD = "1500"

LOG_FILE = os.path.join("logs", "assistant.log")

app = Flask(__name__)

_state = None  # выставляется через set_state() из run_forever.py


def set_state(state):
    global _state
    _state = state


def get_lan_ip():
    """Определяет IP этого ПК в локальной сети - именно его нужно
    набирать с ноутбука или телефона."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _check_auth(password):
    return password == DASHBOARD_PASSWORD


def _authenticate():
    return Response(
        "Нужен пароль для доступа к панели.",
        401,
        {"WWW-Authenticate": 'Basic realm="Assistant Dashboard"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_auth(auth.password):
            return _authenticate()
        return f(*args, **kwargs)
    return decorated


def _read_log_tail(lines=60):
    if not os.path.exists(LOG_FILE):
        return "(лога пока нет)"
    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return "".join(all_lines[-lines:])


def _format_uptime(seconds):
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return str(hours) + "ч " + str(minutes) + "м " + str(secs) + "с"


PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ассистент - панель</title>
<meta http-equiv="refresh" content="5">
<style>
  :root {
    --bg: #14161c;
    --surface: #1c1f28;
    --border: #2a2e3a;
    --text: #e8e6e1;
    --muted: #8b8f9c;
    --alive: #e8a33d;
    --stopped: #e5484d;
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    max-width: 640px;
    margin: 48px auto;
    padding: 0 20px;
    line-height: 1.5;
  }
  .eyebrow {
    font-size: 12px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin: 0 0 4px;
  }
  h1 { font-size: 22px; margin: 0 0 28px; font-weight: 600; }
  .status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; }
  .dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--stopped);
    flex-shrink: 0;
  }
  .dot.alive {
    background: var(--alive);
    animation: pulse 1.8s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(232, 163, 61, 0.5); }
    50% { box-shadow: 0 0 0 6px rgba(232, 163, 61, 0); }
  }
  @media (prefers-reduced-motion: reduce) {
    .dot.alive { animation: none; }
  }
  .status-text { font-size: 16px; font-weight: 600; }
  .status-text.alive { color: var(--alive); }
  .status-text.stopped { color: var(--stopped); }
  .reason { color: var(--muted); font-size: 14px; }

  .metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 28px; }
  .metric { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .metric-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 4px; }
  .metric-value { font-family: ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace; font-size: 18px; }

  .actions { display: flex; gap: 8px; margin-bottom: 32px; }
  form { margin: 0; }
  button {
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 9px 16px;
    font-size: 14px;
    cursor: pointer;
    transition: border-color 0.15s;
  }
  button:hover { border-color: var(--alive); }
  button:focus-visible { outline: 2px solid var(--alive); outline-offset: 2px; }
  .btn-stop:hover { border-color: var(--stopped); }

  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; margin: 0 0 10px; }
  pre {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
    max-height: 400px;
    overflow-y: auto;
    font-family: ui-monospace, "SF Mono", "Cascadia Code", Consolas, monospace;
    font-size: 12px;
    color: var(--muted);
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
</head>
<body>
  <p class="eyebrow">Панель управления</p>
  <h1>Ассистент</h1>

  <div class="status-row">
    <span class="dot {{ 'alive' if running else '' }}"></span>
    <span class="status-text {{ 'alive' if running else 'stopped' }}">
      {{ 'работает' if running else 'остановлен' }}
    </span>
    {% if not running and reason %}<span class="reason">— {{ reason }}</span>{% endif %}
  </div>

  <div class="metrics">
    <div class="metric">
      <div class="metric-label">Аптайм</div>
      <div class="metric-value">{{ uptime or '—' }}</div>
    </div>
    <div class="metric">
      <div class="metric-label">Падений / 5 мин</div>
      <div class="metric-value">{{ restart_count }}</div>
    </div>
  </div>

  <div class="actions">
    <form method="post" action="{{ url_for('do_restart') }}"><button>Перезапустить</button></form>
    <form method="post" action="{{ url_for('do_stop') }}"><button class="btn-stop">Остановить</button></form>
    <form method="post" action="{{ url_for('do_start') }}"><button>Запустить</button></form>
  </div>

  <h2>Последние строки лога</h2>
  <pre>{{ log_tail }}</pre>
</body>
</html>
"""


@app.route("/")
@requires_auth
def status():
    running = _state.is_running()
    uptime = _format_uptime(_state.uptime_seconds()) if running else None
    return render_template_string(
        PAGE,
        running=running,
        uptime=uptime,
        reason=_state.stopped_reason,
        restart_count=len(_state.restart_times),
        log_tail=_read_log_tail(),
    )


@app.route("/restart", methods=["POST"])
@requires_auth
def do_restart():
    _state.restart()
    return redirect(url_for("status"))


@app.route("/stop", methods=["POST"])
@requires_auth
def do_stop():
    _state.stop()
    return redirect(url_for("status"))


@app.route("/start", methods=["POST"])
@requires_auth
def do_start():
    _state.start()
    return redirect(url_for("status"))
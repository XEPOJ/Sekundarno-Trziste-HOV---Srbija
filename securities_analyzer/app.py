import logging
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from typing import NoReturn

import uvicorn

from .api.app import create_app
from .db.seed import ensure_user_db
from .paths import seed_path, user_data_dir

log = logging.getLogger("securities_analyzer")
APP_TITLE = "Analiza državnih hartija"


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _show_dialog(msg: str) -> None:
    """Native error dialog; the only visible channel in a windowed build (no stderr)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, APP_TITLE, 0x10)
    except Exception:                           # never let the dialog mask the real error
        log.exception("Could not show error dialog")


def _fatal(msg: str, code: int) -> NoReturn:
    log.error(msg)
    if sys.stderr is not None:                  # None in PyInstaller --windowed builds
        print(msg, file=sys.stderr)
    _show_dialog(msg)
    raise SystemExit(code)


def run() -> None:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data_dir / "app.log", level=logging.INFO,
                        encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
    db_path = data_dir / "data.db"
    try:
        ensure_user_db(db_path, seed_path())
    except sqlite3.DatabaseError as e:
        # Never delete or replace a user's DB automatically.
        msg = f"Baza podataka je oštećena ili zaključana: {db_path}\n{e}"
        _fatal(msg, 2)

    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(db_path), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        _fatal("Server nije pokrenut", 3)

    url = f"http://127.0.0.1:{port}/"
    log.info("Serving %s", url)
    try:
        import webview
        webview.create_window(APP_TITLE, url, width=1440, height=900)
        webview.start()
    except Exception as e:                      # no pywebview / no WebView2 runtime
        log.warning("Window unavailable (%s); falling back to browser", e)
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True

import logging
import socket
import sqlite3
import sys
import threading
import time
import webbrowser

import uvicorn

from .api.app import create_app
from .db.seed import ensure_user_db
from .paths import seed_path, user_data_dir

log = logging.getLogger("securities_analyzer")


def find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run() -> None:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=data_dir / "app.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    db_path = data_dir / "data.db"
    try:
        ensure_user_db(db_path, seed_path())
    except sqlite3.DatabaseError as e:
        # Never delete or replace a user's DB automatically.
        msg = f"Baza podataka je oštećena ili zaključana: {db_path}\n{e}"
        log.error(msg)
        print(msg, file=sys.stderr)
        raise SystemExit(2) from e

    port = find_free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(db_path), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise SystemExit("Server nije pokrenut")

    url = f"http://127.0.0.1:{port}/"
    log.info("Serving %s", url)
    try:
        import webview
        webview.create_window("Analiza državnih hartija", url, width=1440, height=900)
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

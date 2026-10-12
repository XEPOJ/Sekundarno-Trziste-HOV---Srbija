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

# Browser-fallback watchdog (no console in the windowed exe, so Ctrl+C is not an exit path).
HEARTBEAT_GRACE_S = 180.0      # how long to wait for the very first heartbeat
HEARTBEAT_TIMEOUT_S = 180.0    # silence after which the app exits (hidden tabs throttle timers to ~1/min)
WATCHDOG_INTERVAL_S = 2.0


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


def _webview_usable() -> bool:
    """False when pywebview would silently fall back to the IE11 engine (no WebView2 runtime).

    pywebview 6.x does not raise in that case, so we inspect the chosen renderer ourselves.
    Any problem inspecting it (internal module moved, attribute renamed) counts as usable;
    webview.start() then fails or works on its own.
    """
    if sys.platform != "win32":
        return True
    try:
        from webview.platforms import winforms
        renderer = winforms.renderer
    except Exception:
        log.warning("Could not inspect the pywebview renderer", exc_info=True)
        return True
    return renderer == "edgechromium"


def heartbeat_expired(last: float | None, started: float, now: float, *,
                      grace: float | None = None, timeout: float | None = None) -> bool:
    """Pure decision: has the UI gone away?  `grace`/`timeout` default to the module constants."""
    grace = HEARTBEAT_GRACE_S if grace is None else grace
    timeout = HEARTBEAT_TIMEOUT_S if timeout is None else timeout
    if last is None:
        return now - started > grace
    return now - last > timeout


def watch_heartbeat(get_last, server, *, clock=time.monotonic, sleep=time.sleep,
                    interval: float | None = None) -> None:
    """Block until the UI stops sending heartbeats, then ask the server to exit."""
    interval = WATCHDOG_INTERVAL_S if interval is None else interval
    started = clock()
    while not server.should_exit:
        if heartbeat_expired(get_last(), started, clock()):
            log.info("No UI heartbeat; shutting down")
            server.should_exit = True
            return
        sleep(interval)


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
    fastapi_app = create_app(db_path)
    server = uvicorn.Server(uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=port, log_level="warning"))
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
        if not _webview_usable():
            raise RuntimeError("WebView2 runtime nije instaliran")
        webview.create_window(APP_TITLE, url, width=1440, height=900)
        webview.start()
    except Exception as e:                      # no pywebview / no WebView2 runtime
        log.warning("Window unavailable (%s); falling back to browser", e)
        webbrowser.open(url)
        threading.Thread(
            target=watch_heartbeat, args=(lambda: fastapi_app.state.last_heartbeat, server),
            daemon=True).start()
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    server.should_exit = True

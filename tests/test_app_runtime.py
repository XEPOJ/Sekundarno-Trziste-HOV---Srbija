import sys
import threading
import time
import types

import pytest

from securities_analyzer import app as app_module


# ---------- WebView2 detection ----------
def _fake_winforms(monkeypatch, **attrs):
    mod = types.ModuleType("webview.platforms.winforms")
    for k, v in attrs.items():
        setattr(mod, k, v)
    pkg = types.ModuleType("webview.platforms")
    pkg.winforms = mod
    monkeypatch.setitem(sys.modules, "webview.platforms", pkg)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", mod)


@pytest.mark.skipif(sys.platform != "win32", reason="renderer check is Windows-only")
@pytest.mark.parametrize("renderer,usable", [
    ("edgechromium", True), ("mshtml", False), ("cef", False)])
def test_webview_usable_follows_renderer(monkeypatch, renderer, usable):
    _fake_winforms(monkeypatch, renderer=renderer)
    assert app_module._webview_usable() is usable


@pytest.mark.skipif(sys.platform != "win32", reason="renderer check is Windows-only")
def test_webview_usable_does_not_raise_when_internals_change(monkeypatch):
    _fake_winforms(monkeypatch)                         # attribute `renderer` is gone
    assert app_module._webview_usable() is True
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", None)   # import fails
    monkeypatch.delitem(sys.modules, "webview.platforms", raising=False)
    assert app_module._webview_usable() is True


# ---------- heartbeat watchdog (injected clock, no server) ----------
class _Server:
    should_exit = False


class _Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def test_heartbeat_expired_rules(monkeypatch):
    monkeypatch.setattr(app_module, "HEARTBEAT_GRACE_S", 180.0)
    monkeypatch.setattr(app_module, "HEARTBEAT_TIMEOUT_S", 60.0)
    f = app_module.heartbeat_expired
    assert not f(None, 0.0, 180.0) and f(None, 0.0, 180.1)      # grace before any heartbeat
    assert not f(100.0, 0.0, 160.0) and f(100.0, 0.0, 160.1)    # timeout after one
    assert not f(100.0, 0.0, 200.0 - 41.0)


def test_watchdog_exits_server_after_heartbeats_stop(monkeypatch):
    monkeypatch.setattr(app_module, "HEARTBEAT_GRACE_S", 180.0)
    monkeypatch.setattr(app_module, "HEARTBEAT_TIMEOUT_S", 60.0)
    clk, srv = _Clock(), _Server()
    last = {"v": None}

    def sleep(dt):
        clk.sleep(dt)
        if clk.t <= 100:                    # UI beats every tick for the first 100 s
            last["v"] = clk.t
    app_module.watch_heartbeat(lambda: last["v"], srv, clock=clk.now, sleep=sleep, interval=5.0)
    assert srv.should_exit is True
    assert 160 < clk.t <= 170               # ~60 s after the last beat, not the 180 s grace


def test_watchdog_uses_grace_when_no_heartbeat_ever_arrives(monkeypatch):
    monkeypatch.setattr(app_module, "HEARTBEAT_GRACE_S", 180.0)
    clk, srv = _Clock(), _Server()
    app_module.watch_heartbeat(lambda: None, srv, clock=clk.now, sleep=clk.sleep, interval=5.0)
    assert srv.should_exit is True and 180 < clk.t <= 190


def test_watchdog_stops_when_server_already_exiting():
    srv = _Server()
    srv.should_exit = True
    clk = _Clock()
    app_module.watch_heartbeat(lambda: None, srv, clock=clk.now, sleep=clk.sleep)
    assert clk.t == 0


# ---------- run(): fallback wiring with a fake server and fake webview ----------
def test_run_falls_back_to_browser_and_exits_when_heartbeats_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_module.logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr(app_module, "seed_path", lambda: None)
    monkeypatch.setattr(app_module, "_webview_usable", lambda: False)
    monkeypatch.setattr(app_module, "HEARTBEAT_GRACE_S", 0.3)
    monkeypatch.setattr(app_module, "HEARTBEAT_TIMEOUT_S", 0.3)
    monkeypatch.setattr(app_module, "WATCHDOG_INTERVAL_S", 0.02)

    class FakeServer:
        def __init__(self, config):
            self.started = False
            self.should_exit = False

        def run(self):
            self.started = True
            while not self.should_exit:
                time.sleep(0.01)

    opened, window_calls = [], []
    monkeypatch.setattr(app_module.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(app_module.uvicorn, "Config", lambda *a, **kw: None)
    monkeypatch.setattr(app_module.webbrowser, "open", opened.append)
    fake_webview = types.ModuleType("webview")
    fake_webview.create_window = lambda *a, **kw: window_calls.append("window")
    fake_webview.start = lambda: window_calls.append("start")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    t = threading.Thread(target=app_module.run, daemon=True)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "run() must return once heartbeats stop"
    assert len(opened) == 1 and opened[0].startswith("http://127.0.0.1:")
    assert window_calls == []                       # unusable WebView2 -> no window attempted


def test_server_config_works_without_console_streams(monkeypatch):
    # A PyInstaller --windowed exe has sys.stdout/stderr = None. uvicorn's default logging setup
    # then raises "Unable to configure formatter 'default'" and the app dies on start.
    from fastapi import FastAPI

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdin", None)
    config = app_module.server_config(FastAPI(), 8123)
    assert (config.host, config.port) == ("127.0.0.1", 8123)
    assert config.log_config is None                # our own app.log logging is the only logging


def test_default_heartbeat_timing_tolerates_throttled_background_tabs():
    # Browsers throttle timers in hidden tabs to ~1/min, so the timeout must be generous.
    assert app_module.HEARTBEAT_TIMEOUT_S >= 180
    assert app_module.HEARTBEAT_GRACE_S >= app_module.HEARTBEAT_TIMEOUT_S

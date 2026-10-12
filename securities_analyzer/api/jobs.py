import threading
from collections.abc import Callable


class UpdateJob:
    """Runs one background update at a time and exposes its progress for polling."""

    def __init__(self, run: Callable[[Callable[[str], None]], object]):
        self._run = run                      # run(progress) -> UpdateReport
        self._lock = threading.Lock()
        self._state: dict = {"state": "idle", "messages": [], "report": None, "error": None}

    def start(self) -> bool:
        with self._lock:
            if self._state["state"] == "running":
                return False
            self._state = {"state": "running", "messages": [], "report": None, "error": None}
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def _progress(self, msg: str) -> None:
        with self._lock:
            self._state["messages"].append(msg)

    def _work(self) -> None:
        try:
            report = self._run(self._progress)
            with self._lock:
                self._state.update(state="done", report=report.to_dict())
        except Exception as e:                       # surface any failure to the UI
            with self._lock:
                self._state.update(state="error", error=str(e))

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "messages": list(self._state["messages"])}

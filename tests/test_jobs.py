import threading
import time

from securities_analyzer.api.jobs import UpdateJob


class _Report:
    def to_dict(self):
        return {"ok": True}


def _wait_until_not_running(job, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = job.snapshot()
        if snap["state"] != "running":
            return snap
        time.sleep(0.01)
    raise AssertionError("job still running after timeout")


def test_single_flight_and_progress():
    gate = threading.Event()
    started = threading.Event()

    def run(progress):
        progress("korak 1")
        started.set()
        assert gate.wait(5)
        return _Report()

    job = UpdateJob(run)
    assert job.snapshot()["state"] == "idle"
    assert job.start() is True
    assert started.wait(5)
    assert job.start() is False
    snap = job.snapshot()
    assert snap["state"] == "running" and snap["messages"] == ["korak 1"]
    gate.set()
    snap = _wait_until_not_running(job)
    assert snap["state"] == "done" and snap["report"] == {"ok": True} and snap["error"] is None
    assert job.start() is True          # a finished job can be started again
    _wait_until_not_running(job)


def test_failure_ends_in_error_state():
    def run(progress):
        raise RuntimeError("boom")

    job = UpdateJob(run)
    assert job.start() is True
    snap = _wait_until_not_running(job)
    assert snap["state"] == "error" and "boom" in snap["error"] and snap["report"] is None

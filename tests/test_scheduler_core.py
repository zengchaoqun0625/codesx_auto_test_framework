import json
import threading

from api_project.scheduler import scheduler_core


def _test_job(name="scheduled test"):
    return {
        "name": name,
        "cron": "0 * * * *",
        "command": "run_testcases.py",
        "env": {},
        "timeout_sec": 60,
    }


def test_default_test_schedules_are_staggered():
    config = scheduler_core.load_jobs()
    test_jobs = [job for job in config["jobs"] if job["command"] == "run_testcases.py"]
    assert len(test_jobs) >= 2
    assert [job["cron"] for job in test_jobs[:2]] == ["*/30 * * * *", "15,45 * * * *"]


def test_framework_test_jobs_do_not_run_concurrently(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler_core, "TEST_RUN_LOCK_FILE", tmp_path / "test-run.lock")
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_run(job):
        calls.append(job["name"])
        started.set()
        assert release.wait(timeout=2)
        return 0

    monkeypatch.setattr(scheduler_core, "_run_command", fake_run)
    first = threading.Thread(target=scheduler_core.run_job, args=(_test_job("full"),))
    first.start()
    assert started.wait(timeout=2)

    assert scheduler_core.run_job(_test_job("smoke")) == 0
    release.set()
    first.join(timeout=2)

    assert not first.is_alive()
    assert calls == ["full"]
    assert not scheduler_core.TEST_RUN_LOCK_FILE.exists()


def test_stale_test_run_lock_is_recovered(monkeypatch, tmp_path):
    lock_path = tmp_path / "test-run.lock"
    lock_path.write_text(json.dumps({"pid": 999_999_999, "job": "old"}), encoding="utf-8")
    monkeypatch.setattr(scheduler_core, "TEST_RUN_LOCK_FILE", lock_path)
    monkeypatch.setattr(scheduler_core, "_run_command", lambda job: 7)

    assert scheduler_core.run_job(_test_job()) == 7
    assert not lock_path.exists()


def test_api_request_fixture_is_function_scoped_and_isolated(monkeypatch):
    from api_project.testcases import conftest

    created = []

    class FakeSession:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeApiRequest:
        def __init__(self):
            self.session = FakeSession()
            created.append(self)

    monkeypatch.setattr(conftest, "ApiRequest", FakeApiRequest)
    first = conftest.api_request.__wrapped__()
    second = conftest.api_request.__wrapped__()
    first_request = next(first)
    second_request = next(second)

    assert conftest.api_request._fixture_function_marker.scope == "function"
    assert first_request is not second_request

    next(first, None)
    next(second, None)
    assert all(item.session.closed for item in created)

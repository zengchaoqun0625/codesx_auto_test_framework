import os

from web_app import app


def test_dashboard_is_available():
    response = app.test_client().get("/api/dashboard")
    assert response.status_code == 200
    data = response.get_json()
    assert "cases" in data
    assert "environment" in data
    assert "scheduler" in data
    assert {"email_configured", "notification_mode", "bots"} <= data["environment"].keys()
    assert {"飞书", "钉钉", "企业微信", "电话告警"} == {bot["name"] for bot in data["environment"]["bots"]}
    assert all({"value", "label"} <= item.keys() for item in data["modules"])


def test_favicon_is_served_from_project_resources():
    response = app.test_client().get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype == "image/vnd.microsoft.icon"


def test_dashboard_uses_the_svg_browser_icon():
    response = app.test_client().get("/")
    assert 'type="image/svg+xml"' in response.get_data(as_text=True)
    icon = app.test_client().get("/static/favicon.svg")
    assert icon.status_code == 200
    assert icon.mimetype == "image/svg+xml"


def test_operation_manual_opens_inline_from_the_local_console():
    response = app.test_client().get("/manual")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_web_console_includes_operation_guide_tab_and_manual_link():
    with open(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"), encoding="utf-8") as file:
        source = file.read()
    assert "data-tab=\"help\"" in source
    assert 'href="/manual"' in source


def test_unknown_module_is_rejected_without_running_tests():
    response = app.test_client().post("/api/runs", json={"module": "not-a-real-module"})
    assert response.status_code == 400


def test_run_button_uses_selected_module_value_instead_of_click_event():
    script = (os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(script, encoding="utf-8") as file:
        source = file.read()
    assert "$('#runSelected').addEventListener('click', () => beginRun())" in source


def test_settings_save_keeps_a_visible_success_state_after_refreshing_settings():
    script = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(script, encoding="utf-8") as file:
        source = file.read()
    assert "await loadDashboard();\n    $('#configState').textContent = '已保存；配置将在下次执行时生效'" in source


def test_dashboard_run_disables_pytest_cache(monkeypatch):
    """Windows cache locks must not prevent a dashboard-triggered run."""
    captured = {}

    class Process:
        pid = 123
        stdout = []

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = command
        return Process()

    monkeypatch.setattr("web_app.subprocess.Popen", fake_popen)
    run_id = "test-run"
    from web_app import _runs, _runs_lock, _execute_run
    with _runs_lock:
        _runs[run_id] = {"log": "", "status": "running"}
    _execute_run(run_id, None)
    assert captured["command"][-2:] == ["-p", "no:cacheprovider"]


def test_curl_preview_masks_secrets_and_does_not_write_case_file():
    from web_app import CASE_DIR
    before = {path.name for path in CASE_DIR.glob("*.json")}
    curl = "curl 'https://example.test/api/orders?token=secret' -H 'iToken: secret-token' -H 'Cookie: sid=secret' --data-raw '{\"password\":\"secret\",\"name\":\"demo\"}'"
    response = app.test_client().post("/api/curl/preview", json={"curl": curl})
    assert response.status_code == 200
    data = response.get_json()
    serialized = str(data["cases"])
    assert "secret-token" not in serialized
    assert "sid=secret" not in serialized
    assert "secret\"" not in serialized
    assert before == {path.name for path in CASE_DIR.glob("*.json")}


def test_curl_draft_save_writes_sanitized_case_and_validates(tmp_path, monkeypatch):
    import web_app

    class Completed:
        returncode = 0
        stdout = "validation passed"
        stderr = ""

    monkeypatch.setattr(web_app, "CASE_DIR", tmp_path)
    monkeypatch.setattr(web_app.subprocess, "run", lambda *args, **kwargs: Completed())
    preview = app.test_client().post("/api/curl/preview", json={"curl": "curl https://example.test/api/invoices -H 'iToken: secret'"})
    assert preview.status_code == 200
    saved = app.test_client().post("/api/curl/save", json={"draft_id": preview.get_json()["draft_id"]})
    assert saved.status_code == 201
    output = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "secret" not in output
    assert "${API_ITOKEN}" in output


def test_curl_save_reports_collection_warning_after_persisting_case(tmp_path, monkeypatch):
    """A collection warning must not make a successful write look unsaved."""
    import web_app

    class Completed:
        returncode = 0
        stdout = "threshold sync"
        stderr = ""

    monkeypatch.setattr(web_app, "CASE_DIR", tmp_path)
    monkeypatch.setattr(web_app.subprocess, "run", lambda *args, **kwargs: Completed())
    monkeypatch.setattr(web_app, "_validate_new_cases", lambda: (False, "collection warning"))
    preview = app.test_client().post("/api/curl/preview", json={"curl": "curl https://example.test/api/warning"})
    saved = app.test_client().post("/api/curl/save", json={"draft_id": preview.get_json()["draft_id"]})

    assert saved.status_code == 201
    assert saved.get_json()["collect_ok"] is False
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_multiple_requests_for_same_endpoint_share_one_case_file():
    response = app.test_client().post("/api/curl/preview", json={"curl": "curl https://example.test/api/items\ncurl https://example.test/api/items"})
    assert response.status_code == 200
    names = [case["filename"] for case in response.get_json()["cases"]]
    assert names == ["api_items.json", "api_items.json"]


def test_curl_save_merges_endpoint_cases_and_ignores_exact_duplicates(tmp_path, monkeypatch):
    import json
    import web_app

    class Completed:
        returncode = 0
        stdout = "validation passed"
        stderr = ""

    monkeypatch.setattr(web_app, "CASE_DIR", tmp_path)
    monkeypatch.setattr(web_app.subprocess, "run", lambda *args, **kwargs: Completed())
    curl = "curl 'https://example.test/api/items?page=1'\ncurl 'https://example.test/api/items?page=2'"
    preview = app.test_client().post("/api/curl/preview", json={"curl": curl})
    saved = app.test_client().post("/api/curl/save", json={"draft_id": preview.get_json()["draft_id"]})

    assert saved.status_code == 201
    assert saved.get_json()["saved"] == ["api_items.json"]
    case_file = tmp_path / "api_items.json"
    assert len(json.loads(case_file.read_text(encoding="utf-8"))["test_cases"]) == 2

    duplicate_preview = app.test_client().post("/api/curl/preview", json={"curl": curl})
    duplicate_save = app.test_client().post("/api/curl/save", json={"draft_id": duplicate_preview.get_json()["draft_id"]})
    assert duplicate_save.status_code == 200
    assert duplicate_save.get_json()["saved"] == []
    assert duplicate_save.get_json()["skipped"] == ["api_items.json"]
    assert len(json.loads(case_file.read_text(encoding="utf-8"))["test_cases"]) == 2


def test_curl_preview_returns_inferred_url_prefix():
    response = app.test_client().post("/api/curl/preview", json={"curl": "curl https://example.test:8443/api/items"})
    assert response.status_code == 200
    assert response.get_json()["url_prefix"] == "https://example.test:8443"


def test_curl_preview_uses_convert_json_contract():
    """The web preview must stay compatible with the script conversion path."""
    from convert_json import Controller, RequestProcessor
    from saf.utils.Curl2Object import Curl

    curl_text = "curl https://example.test/api/orders?token=secret -H 'iToken: private-token' --data-raw '{\"password\":\"secret\",\"name\":\"demo\"}'"
    preview = app.test_client().post("/api/curl/preview", json={"curl": curl_text}).get_json()
    web_case = preview["cases"][0]["case"]["test_cases"]["test_case_1"]

    previous_host = os.environ.get("HOST")
    os.environ["HOST"] = "https://example.test"
    try:
        parser = Curl()
        parser.load(curl_str=curl_text)
    finally:
        if previous_host is None:
            os.environ.pop("HOST", None)
        else:
            os.environ["HOST"] = previous_host
    expected = Controller().normalize_request_data(dict(parser.group[0]))
    expected["url"] = "https://example.test/" + expected["url"].lstrip("/")
    expected.pop("api_name", None)
    assert web_case["data"] == expected
    assert web_case["request_type"] == RequestProcessor.get_request_type(expected)


def test_curl_upload_preview_accepts_multiple_text_files():
    from io import BytesIO
    response = app.test_client().post(
        "/api/curl/upload-preview",
        data={"files": [(BytesIO(b"curl https://example.test/api/one"), "one.txt"), (BytesIO(b"curl https://example.test/api/two"), "two.curl")]},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert len(response.get_json()["cases"]) == 2


def test_curl_preview_does_not_leak_parser_state_between_requests():
    curl = "curl https://example.test/api/one\ncurl https://example.test/api/two\ncurl https://example.test/api/three"
    first = app.test_client().post("/api/curl/preview", json={"curl": curl})
    second = app.test_client().post("/api/curl/preview", json={"curl": curl})
    assert len(first.get_json()["cases"]) == 3
    assert len(second.get_json()["cases"]) == 3


def test_case_library_is_paged_and_searchable(monkeypatch):
    monkeypatch.setattr("web_app._case_summary", lambda: [{"file": f"case_{i}.json", "count": 1, "updated_at": "now"} for i in range(25)])
    response = app.test_client().get("/api/cases?page=2&page_size=20&q=case")
    assert response.status_code == 200
    data = response.get_json()
    assert data["total"] == 25 and data["page"] == 2 and len(data["items"]) == 5


def test_case_allure_assignment_is_persisted_in_console_store(monkeypatch, tmp_path):
    import web_app

    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    (case_dir / "example.json").write_text('{"test_cases": {}}', encoding="utf-8")
    monkeypatch.setattr(web_app, "CASE_DIR", case_dir)
    monkeypatch.setattr(web_app, "ALLURE_PRESETS_FILE", tmp_path / "allure_presets.json")
    monkeypatch.setattr(web_app, "_allure_preset_options", lambda: [{"key": "smoke_api"}])

    response = app.test_client().post("/api/cases/allure", json={"files": ["example.json"], "preset": "smoke_api"})
    assert response.status_code == 200
    assert web_app._read_json(web_app.ALLURE_PRESETS_FILE, {})["assignments"] == {"example.json": "smoke_api"}


def test_schedule_crud_uses_safe_test_runner_command(monkeypatch, tmp_path):
    import web_app

    monkeypatch.setattr(web_app, "SCHEDULER_JOBS_FILE", tmp_path / "scheduler_jobs.json")
    monkeypatch.setattr(web_app, "_allure_preset_options", lambda: [{"key": "smoke_api"}])
    created = app.test_client().post("/api/schedules", json={"name": "smoke", "cron": "0 2 * * *", "preset": "smoke_api", "timeout_sec": 120, "enabled": True})
    assert created.status_code == 201
    job = created.get_json()
    assert job["command"] == "run_testcases.py"
    assert job["env"] == {"RUN_MODULE": "smoke_api"}
    toggled = app.test_client().post(f"/api/schedules/{job['id']}/toggle")
    assert toggled.status_code == 200 and toggled.get_json()["enabled"] is False
    assert app.test_client().delete(f"/api/schedules/{job['id']}").status_code == 200


def test_run_scheduler_starts_project_scheduler_entry(monkeypatch):
    import web_app

    class FakeProcess:
        pid = 4321

        def poll(self):
            return None

    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(web_app.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(web_app, "_scheduler_process", None)
    monkeypatch.setattr(web_app, "_scheduler_status", lambda: {"total": 1, "enabled": 1, "jobs": []})
    monkeypatch.setattr(web_app, "_safe_env_status", lambda: {"scheduler_enabled": True})
    response = app.test_client().post("/api/scheduler/run")
    assert response.status_code == 202
    assert captured["command"] == [web_app.sys.executable, str(web_app.SCHEDULER_RUNNER)]
    web_app._scheduler_process = None


def test_stop_scheduler_stops_console_owned_process(monkeypatch):
    import web_app

    class FakeProcess:
        pid = 7654
        terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    process = FakeProcess()
    monkeypatch.setattr(web_app, "_scheduler_process", process)
    response = app.test_client().post("/api/scheduler/stop")
    assert response.status_code == 200
    assert response.get_json()["stopped"] is True
    assert process.terminated is True
    assert web_app._scheduler_process is None


def test_settings_updates_only_allowed_env_keys(tmp_path, monkeypatch):
    import web_app
    monkeypatch.setattr(web_app, "ROOT", tmp_path)
    (tmp_path / "api_project").mkdir()
    (tmp_path / "api_project" / ".env").write_text("OTHER=keep\nAPI_TOKEN=old\n", encoding="utf-8")
    response = app.test_client().post("/api/settings", json={"api_token": "new-token", "api_cookie": "new-cookie", "email_mode": "never", "notification_mode": "only_failed", "scheduler_enabled": True})
    assert response.status_code == 200
    content = (tmp_path / "api_project" / ".env").read_text(encoding="utf-8")
    assert "OTHER=keep" in content and "API_TOKEN=new-token" in content and "API_COOKIE=new-cookie" in content


def test_settings_supports_individual_notification_channels(tmp_path, monkeypatch):
    import web_app
    monkeypatch.setattr(web_app, "ROOT", tmp_path)
    (tmp_path / "api_project").mkdir()
    response = app.test_client().post("/api/settings", json={"feishu_enabled": False, "dingding_enabled": True, "feishu_token": "new-feishu", "dingding_secret": "new-secret"})
    assert response.status_code == 200
    content = (tmp_path / "api_project" / ".env").read_text(encoding="utf-8")
    assert "FEISHU_ENABLED=false" in content and "DINGDING_ENABLED=true" in content
    assert "FEISHU_TOKEN=new-feishu" in content and "DINGDING_SECRET=new-secret" in content


def test_settings_exposes_resolved_defaults_and_sources(tmp_path, monkeypatch):
    import web_app
    monkeypatch.setattr(web_app, "ROOT", tmp_path)
    (tmp_path / "api_project").mkdir()
    data = app.test_client().get("/api/settings").get_json()
    assert data["values"]["API_TIMEOUT"] == "10"
    assert data["value_sources"]["API_TIMEOUT"] == "default"
    assert data["values"]["SMTP_HOST"] == "smtp.qq.com"
    assert data["values"]["SMTP_PORT"] == "465"
    assert data["values"]["SMTP_SUBJECT"] == "自动化测试报告"

"""Offline regression tests for framework behavior; no API calls are made."""
from datetime import timedelta
from types import SimpleNamespace

from requests import Response
from requests.structures import CaseInsensitiveDict

from api_project.common.api_request import ApiRequest, sanitize_headers
from api_project.common.reporting import (
    collect_worker_results,
    is_report_upload_enabled,
    is_xdist_worker,
    publish_worker_results,
)
from api_project.common.settings import get_bool_env, get_positive_float_env


def test_sanitize_headers_masks_common_credentials_without_mutating_source():
    source = {
        "Authorization": "Bearer private-token",
        "Cookie": "session=private-cookie",
        "X-API-Key": "private-key",
        "X-Trace-Id": "safe-to-display",
    }

    sanitized = sanitize_headers(source)

    assert sanitized == {
        "Authorization": "***",
        "Cookie": "***",
        "X-API-Key": "***",
        "X-Trace-Id": "safe-to-display",
    }
    assert source["Cookie"] == "session=private-cookie"


def test_sanitize_headers_handles_missing_or_non_mapping_values():
    assert sanitize_headers(None) == {}
    assert sanitize_headers("not-a-mapping") == {}
    assert sanitize_headers(CaseInsensitiveDict({"Set-Cookie": "private"})) == {
        "Set-Cookie": "***"
    }


def test_request_metadata_does_not_keep_sensitive_headers():
    client = ApiRequest()
    client.user_token = None
    response = Response()
    response.status_code = 200
    response._content = b'{}'
    response.elapsed = timedelta(milliseconds=1)

    captured = {}

    def fake_request(*args, **kwargs):
        captured.update(kwargs)
        return response

    client.session.request = fake_request
    client.send_request(
        method="GET",
        url="https://example.test/health",
        headers={"Cookie": "private", "X-Request-Id": "visible"},
    )

    assert client.last_request_info["headers"] == {
        "Cookie": "***",
        "X-Request-Id": "visible",
    }
    assert captured["verify"] is True


def test_report_upload_is_opt_in():
    assert not is_report_upload_enabled({})
    assert not is_report_upload_enabled({"UPLOAD_TEST_REPORT": "false"})
    assert is_report_upload_enabled({"UPLOAD_TEST_REPORT": "true"})


def test_worker_result_round_trip():
    config = SimpleNamespace(workerinput={}, workeroutput={})
    results = [{"name": "case-a", "outcome": "passed"}]

    assert is_xdist_worker(config)
    publish_worker_results(config, results)

    node = SimpleNamespace(workeroutput=config.workeroutput)
    assert collect_worker_results(node) == results


def test_controller_is_not_considered_a_worker_and_ignores_bad_payloads():
    assert not is_xdist_worker(SimpleNamespace())
    assert collect_worker_results(SimpleNamespace(workeroutput={"api_test_results": "bad"})) == []


def test_environment_settings_use_safe_defaults_for_invalid_values():
    assert get_bool_env("FLAG", default=True, environ={"FLAG": "unexpected"}) is True
    assert get_positive_float_env("TIMEOUT", 10, environ={"TIMEOUT": "-1"}) == 10


def test_allure_uses_project_relative_bundled_executable():
    from api_project import ALLURE_BIN_PATH
    from api_project.config.allure_config import Allure

    assert Allure.PATH == ALLURE_BIN_PATH


def test_weixin_notification_uses_tls_verification_and_timeout(monkeypatch):
    from api_project.common.notifications import senders

    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"errcode": 0}

    class Service:
        app_name = "企业微信"
        webhook = "https://example.test/webhook"

        @staticmethod
        def client(**kwargs):
            captured.update(kwargs)
            return Response()

    monkeypatch.setattr(senders, "_build_weixin_markdown", lambda *args, **kwargs: "test")
    assert senders._send_weixin_rich(Service(), "ignored", {"total": 1, "passed": 1, "failed": 0})
    assert captured["verify"] is True
    assert captured["timeout"] == 10.0

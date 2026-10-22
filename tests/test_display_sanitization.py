from datetime import timedelta

from requests import Response

from api_project.common.api_request import ApiRequest, sanitize_for_display, sanitize_url


def test_recursive_display_sanitizer_masks_sensitive_values_in_one_style():
    payload = {
        "password": "password123",
        "access_token": "token-value-987",
        "mobile": "15112345241",
        "identity_card": "110101199001011234",
        "nested": {"contactPhone": "13812345678"},
        "free_text": "phone=13912345678&token=unstructured-secret",
    }

    safe = sanitize_for_display(payload)

    assert payload["password"] == "password123"  # input remains usable for the request
    assert safe["password"] == "pas*******123"
    assert safe["access_token"] == "tok*******987"
    assert safe["mobile"] == "151*******241"
    assert safe["identity_card"] == "110*******234"
    assert safe["nested"]["contactPhone"] == "138*******678"
    assert "139*******678" in safe["free_text"]
    assert "uns*******ret" in safe["free_text"]


def test_url_sanitizer_masks_query_values_without_changing_endpoint():
    safe_url = sanitize_url("https://example.test/orders?mobile=15112345241&token=token-value-987&page=1")

    assert safe_url.startswith("https://example.test/orders?")
    assert "mobile=151*******241" in safe_url
    assert "token=tok*******987" in safe_url
    assert "page=1" in safe_url


def test_api_request_sends_original_values_but_records_masked_copy(monkeypatch):
    client = ApiRequest()
    captured = {}
    response = Response()
    response.status_code = 200
    response.headers = {"Set-Cookie": "sid=private-cookie"}
    response._content = b'{"mobile":"15112345241","token":"response-secret"}'
    response.elapsed = timedelta(milliseconds=12)

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return response

    monkeypatch.setattr(client.session, "request", fake_request)
    client.send_request(
        "POST",
        "https://example.test/orders?token=query-secret",
        params={"mobile": "15112345241"},
        json={"password": "password123", "token": "body-secret"},
        headers={"Authorization": "Bearer header-secret"},
        use_token=False,
    )

    assert captured["params"] == {"mobile": "15112345241"}
    assert captured["json"] == {"password": "password123", "token": "body-secret"}
    assert captured["headers"]["Authorization"] == "Bearer header-secret"
    assert "query-secret" not in client.last_request_info["url"]
    assert client.last_request_info["params"]["mobile"] == "151*******241"
    assert client.last_request_info["body"]["password"] == "pas*******123"
    assert "private-cookie" not in client.last_response_info["headers"]["Set-Cookie"]
    assert "response-secret" not in client.last_response_info["text"]


def test_allure_request_attachment_uses_display_safe_copy(monkeypatch):
    from api_project.common import allure_decorator

    attachments = []
    monkeypatch.setattr(allure_decorator.allure, "attach", lambda content, *args, **kwargs: attachments.append(str(content)))

    allure_decorator.AllureAttachments.attach_request(
        "POST",
        "https://example.test/orders?token=query-secret",
        headers={"Authorization": "Bearer header-secret"},
        params={"mobile": "15112345241"},
        body={"password": "password123"},
    )

    rendered = "\n".join(attachments)
    for secret in ("query-secret", "header-secret", "15112345241", "password123"):
        assert secret not in rendered
    assert "151*******241" in rendered
    assert "pas*******123" in rendered

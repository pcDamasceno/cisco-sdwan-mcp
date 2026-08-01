"""
Tests for the vManage client — the login handshake, session recovery and
error translation.

These are the behaviours that break against real controllers: vManage answers
a *failed* login with HTTP 200, so anything checking status codes alone would
sail past a wrong password and fail confusingly on the first data call.
"""

from __future__ import annotations

import httpx
import pytest

from cisco_sdwan_mcp.sdwan.client import VManageClient, extract_data
from cisco_sdwan_mcp.sdwan.errors import APIError, AuthenticationError
from tests.conftest import LOGIN_PAGE, FakeVManage, make_client


async def test_login_captures_cookie_and_token():
    fake = FakeVManage({"/dataservice/device": {"data": [{"host-name": "BR1"}]}})
    client = make_client(fake)

    records = await client.get_data("/dataservice/device")

    assert records == [{"host-name": "BR1"}]
    assert fake.login_count == 1
    assert "/dataservice/client/token" in fake.paths()
    data_request = fake.last_request_for("/dataservice/device")
    assert data_request.headers["X-XSRF-TOKEN"] == "csrf-token-123"
    await client.close()


async def test_login_sends_form_encoded_credentials():
    fake = FakeVManage({"/dataservice/device": {"data": []}})
    client = make_client(fake)

    await client.get_data("/dataservice/device")

    login = fake.last_request_for("/j_security_check")
    assert login.headers["content-type"] == "application/x-www-form-urlencoded"
    assert b"j_username=tester" in login.content
    assert b"j_password=secret" in login.content
    await client.close()


async def test_bad_credentials_raise_even_though_vmanage_returns_200():
    fake = FakeVManage(login_fails=True)
    client = make_client(fake)

    with pytest.raises(AuthenticationError, match="rejected the credentials"):
        await client.get_data("/dataservice/device")
    await client.close()


async def test_missing_session_cookie_raises():
    fake = FakeVManage()
    # Accept the login but issue no cookie, as a cookie-stripping proxy would.
    fake._handle_login = lambda: httpx.Response(200)  # type: ignore[method-assign]
    client = make_client(fake)

    with pytest.raises(AuthenticationError, match="no JSESSIONID cookie"):
        await client.get_data("/dataservice/device")
    await client.close()


async def test_older_controller_without_token_endpoint_still_works():
    fake = FakeVManage({"/dataservice/device": {"data": []}}, token=None)
    client = make_client(fake)

    await client.get_data("/dataservice/device")

    assert "X-XSRF-TOKEN" not in fake.last_request_for("/dataservice/device").headers
    await client.close()


async def test_expired_session_triggers_one_reauth_and_retry():
    fake = FakeVManage({"/dataservice/device": {"data": [{"host-name": "BR1"}]}},
                       expire_after=1)
    client = make_client(fake)

    first = await client.get_data("/dataservice/device")
    assert first == [{"host-name": "BR1"}]
    assert fake.login_count == 1

    # The next call is served the login page, so the client re-authenticates.
    second = await client.get_data("/dataservice/device")

    assert second == [{"host-name": "BR1"}]
    assert fake.login_count == 2
    await client.close()


async def test_http_error_surfaces_vmanage_message():
    fake = FakeVManage(
        {
            "/dataservice/device": httpx.Response(
                500, json={"error": {"message": "Internal error",
                                     "details": "database unavailable"}}
            )
        }
    )
    client = make_client(fake)

    with pytest.raises(APIError, match="database unavailable") as exc_info:
        await client.get_data("/dataservice/device")

    assert exc_info.value.status_code == 500
    await client.close()


async def test_forbidden_reports_a_permissions_problem():
    # 403 on every attempt: the client re-authenticates once, then gives up.
    fake = FakeVManage({"/dataservice/template/device": httpx.Response(403)})
    client = make_client(fake)

    with pytest.raises(AuthenticationError, match="may lack the required role"):
        await client.get_data("/dataservice/template/device")
    await client.close()


async def test_unreachable_controller_reports_actionable_error():
    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = VManageClient(
        make_client(FakeVManage()).settings, transport=httpx.MockTransport(explode)
    )

    with pytest.raises(APIError, match="cannot reach vmanage.test"):
        await client.get_data("/dataservice/device")
    await client.close()


async def test_timeout_reports_the_configured_limit():
    def stall(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    client = VManageClient(
        make_client(FakeVManage()).settings, transport=httpx.MockTransport(stall)
    )

    with pytest.raises(APIError, match="timed out after 5.0s"):
        await client.get_data("/dataservice/device")
    await client.close()


async def test_non_json_response_is_reported_clearly():
    fake = FakeVManage({"/dataservice/device": httpx.Response(200, text="not json")})
    client = make_client(fake)

    with pytest.raises(APIError, match="not valid JSON"):
        await client.get_data("/dataservice/device")
    await client.close()


def test_login_page_detection_covers_missing_content_type():
    assert VManageClient._session_expired(
        httpx.Response(200, text=LOGIN_PAGE)
    ) is True
    assert VManageClient._session_expired(
        httpx.Response(200, json={"data": []})
    ) is False


# ---------------------------------------------------------------------------
# Envelope handling — vManage is not consistent about how it wraps results.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"data": [{"a": 1}]}, [{"a": 1}]),
        ({"data": {"a": 1}}, [{"a": 1}]),
        ([{"a": 1}], [{"a": 1}]),
        ({"data": []}, []),
        (None, []),
        ("unexpected", []),
    ],
)
def test_extract_data(payload, expected):
    assert extract_data(payload) == expected

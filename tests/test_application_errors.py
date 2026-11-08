"""Application failures must work without coupling callers to FastAPI."""

import subprocess
import sys

import pytest

from qinzora.errors import ApplicationError, require


def test_service_import_does_not_load_the_web_framework():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import qinzora.service; import sys; "
            "assert not {'fastapi', 'sqlite3'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("value", [False, 0, "", [], {}])
def test_require_preserves_existing_falsy_values(value):
    assert require(value) is value


def test_missing_resource_is_an_application_failure():
    with pytest.raises(ApplicationError) as failure:
        require(None)
    assert failure.value.code == "not_found"


@pytest.mark.parametrize(
    ("code", "status"),
    [("not_found", 404), ("conflict", 409), ("capacity_exceeded", 429), ("replay_too_large", 413)],
)
def test_http_adapter_preserves_error_contract(api, code, status):
    client, _ = api

    @client.app.get("/test-application-error")
    def fail():
        raise ApplicationError(code, "Operation rejected")

    response = client.get("/test-application-error")
    assert response.status_code == status
    assert response.json() == {"detail": "Operation rejected"}

import secrets

import pytest
from fastapi.testclient import TestClient

from api_sentinel.app import create_app


@pytest.fixture
def api(tmp_path):
    token = secrets.token_urlsafe(32)
    app = create_app(str(tmp_path / "test.sqlite"), token)
    with TestClient(app) as client:
        yield client, token


def auth(key):
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture
def tenant(api):
    client, admin = api
    response = client.post("/v1/admin/tenants", headers=auth(admin), json={"name": "Test"})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def event():
    return {
        "event_id": "event-1",
        "service": "documents",
        "route": "/documents/{id}",
        "subject": "user-a",
        "actor_tenant": "company-a",
        "resource_tenant": "company-a",
    }

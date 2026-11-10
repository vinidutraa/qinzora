import pytest

from qinzora.app import create_app


@pytest.mark.parametrize("token", ["é" * 32, "a" * 513, "a" * 31 + " ", "a" * 31 + "\n"])
def test_invalid_admin_configuration_fails_before_creating_storage(tmp_path, token):
    with pytest.raises(ValueError, match="QINZORA_ADMIN_TOKEN"):
        create_app(str(tmp_path / "invalid.sqlite"), token)
    assert not list(tmp_path.iterdir())


def test_non_ascii_bearer_is_an_authentication_error_not_a_server_error(api):
    client, _ = api
    response = client.post(
        "/v1/admin/tenants",
        headers=[(b"authorization", b"Bearer invalid-\xff")],
        json={"name": "must not be created"},
    )
    assert response.status_code == 401

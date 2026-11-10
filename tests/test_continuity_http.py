from conftest import auth


def test_management_requires_manager_and_isolates_accounts(api, tenant):
    client, admin = api
    body = {"service": "s", "route": "/r", "consumer": "c", "effect": "read"}
    assert client.post("/v1/continuity/contracts", json=body).status_code == 401
    assert (
        client.post(
            "/v1/continuity/contracts", json=body, headers=auth(tenant["collector_key"])
        ).status_code
        == 403
    )
    created = client.post(
        "/v1/continuity/contracts", json=body, headers=auth(tenant["manager_key"])
    )
    assert created.status_code == 201
    other = client.post("/v1/admin/tenants", json={"name": "Other"}, headers=auth(admin)).json()
    assert (
        client.get(
            f"/v1/continuity/contracts/{created.json()['id']}", headers=auth(other["manager_key"])
        ).status_code
        == 404
    )


def test_manual_activation_requires_review_of_the_current_digest(api, tenant):
    from qinzora.models import now

    client, _ = api
    headers = auth(tenant["manager_key"])
    contract = client.post(
        "/v1/continuity/contracts",
        headers=headers,
        json={
            "service": "s",
            "route": "/r",
            "consumer": "c",
            "effect": "read",
            "allow_cached": True,
            "maximum_age_seconds": 60,
        },
    ).json()
    profile = client.post(
        "/v1/continuity/profiles",
        headers=headers,
        json={
            "name": "p",
            "service": "s",
            "route": "/r",
            "source": "local",
            "contract_ids": [contract["id"]],
        },
    ).json()
    path = f"/v1/continuity/profiles/{profile['id']}"
    suite = {
        "captured_at": now().isoformat(),
        "scenarios": [
            {
                "name": "fresh",
                "contract_id": contract["id"],
                "observed": {
                    "available": True,
                    "authorized": True,
                    "same_tenant": True,
                    "consumer_matches": True,
                },
                "expected": "permit",
            }
        ],
    }
    assert client.put(path + "/rehearsal", headers=headers, json=suite).status_code == 200
    report = client.post(path + "/simulate", headers=headers).json()
    assert report["eligible"]
    activation = {"expected_digest": report["config_digest"], "acknowledge_impact": False}
    assert client.post(path + "/activate", headers=headers, json=activation).status_code == 409
    activation["acknowledge_impact"] = True
    assert (
        client.post(path + "/activate", headers=headers, json=activation).json()["state"]
        == "active"
    )
    assert client.post(path + "/revoke", headers=headers).json()["state"] == "revoked"
    suite["scenarios"][0]["name"] = "changed"
    assert client.put(path + "/rehearsal", headers=headers, json=suite).status_code == 200
    assert client.post(path + "/activate", headers=headers, json=activation).status_code == 409

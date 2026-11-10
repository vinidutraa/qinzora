import httpx

from qinzora.explain import KNOWN_REASONS, explain


def test_english_canonical_explanation_stays_available_on_model_failure(monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx.Client, "post", offline)
    result = explain(
        {"findings": [{"reason": "cross_tenant_access"}, {"reason": "unrecognized"}]},
        "http://127.0.0.1:11434",
        "example-model",
    )
    assert result["evidence_counts"] == {"cross_tenant_access": 1}
    assert result["explanation"] == KNOWN_REASONS["cross_tenant_access"]
    assert result["explanation"] == "The actor tenant differs from the resource tenant."
    assert result["source"] == "deterministic"
    assert result["advisory_only"] and result["model_error"]
    assert result["model_explanation"] is None

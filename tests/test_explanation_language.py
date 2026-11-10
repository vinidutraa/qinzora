import httpx
import pytest

from qinzora.explain import KNOWN_REASONS, explain


def test_english_canonical_explanation_stays_available_on_model_failure():
    def offline(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    result = explain(
        {"findings": [{"reason": "cross_tenant_access"}, {"reason": "unrecognized"}]},
        "http://127.0.0.1:11434",
        "example-model",
        transport=httpx.MockTransport(offline),
    )
    assert result["evidence_counts"] == {"cross_tenant_access": 1}
    assert result["explanation"] == KNOWN_REASONS["cross_tenant_access"]
    assert result["explanation"] == "The actor tenant differs from the resource tenant."
    assert result["source"] == "deterministic"
    assert result["advisory_only"] and result["model_error"]
    assert result["model_explanation"] is None


@pytest.mark.parametrize(
    "envelope",
    [
        {"message": {"content": "Incomplete output"}, "done": False},
        {"message": {"content": "Truncated output"}, "done": True, "done_reason": "length"},
        {"message": {"content": "x" * 270000}, "done": True},
        [],
    ],
)
def test_incomplete_or_oversized_explanations_keep_the_grounded_fallback(envelope):
    result = explain(
        {"findings": [{"reason": "cross_tenant_access"}]},
        "http://model.test",
        "model",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope)),
    )
    assert result["source"] == "deterministic" and result["model_error"]
    assert result["explanation"] == KNOWN_REASONS["cross_tenant_access"]
    assert result["model_explanation"] is None

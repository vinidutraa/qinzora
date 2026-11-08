"""Optional Ollama adapter. Only enumerated reasons/counts leave the engine."""

import json
from collections import Counter

import httpx

KNOWN_REASONS = {
    "missing_tenant_context": "Contexto de empresa ausente na integração.",
    "cross_tenant_access": "Empresa do usuário difere da empresa do recurso.",
    "request_rate_exceeded": "Limite de tentativas por identidade e rota excedido.",
    "high_latency": "Latência observada acima do limite configurado.",
    "error_burst": "Quantidade de respostas com erro excedeu o limite configurado.",
}


def explain(incident: dict, base_url: str | None = None, model: str | None = None):
    counts = Counter(f["reason"] for f in incident["findings"] if f["reason"] in KNOWN_REASONS)
    result = {
        "source": "deterministic",
        "evidence_counts": dict(counts),
        "explanation": " ".join(KNOWN_REASONS[reason] for reason in counts),
        "advisory_only": True,
        "model_error": None,
        "model_explanation": None,
    }
    if not base_url or not model:
        return result
    try:
        with httpx.Client(
            timeout=httpx.Timeout(60, connect=2), follow_redirects=False, trust_env=False
        ) as client:
            response = client.post(
                base_url.rstrip("/") + "/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "think": False,
                    "keep_alive": "1m",
                    "messages": [
                        {
                            "role": "system",
                            "content": "Resuma em português as VIOLAÇÕES OBSERVADAS abaixo. "
                            "São ocorrências detectadas, não opções de configuração. "
                            "Use apenas os significados e contagens informados. "
                            "Não invente atores, causas ou resultados. Máximo 60 palavras.",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                [
                                    {
                                        "reason": reason,
                                        "meaning": KNOWN_REASONS[reason],
                                        "count": count,
                                    }
                                    for reason, count in counts.items()
                                ],
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    "options": {"temperature": 0, "num_predict": 160},
                },
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            if not isinstance(content, str) or not content.strip() or len(content) > 5000:
                raise ValueError("Invalid model response")
            # Canonical explanation remains grounded, even if the model invents details.
            result.update(source="ollama", model_explanation=content)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        result["model_error"] = "Model unavailable or invalid response; deterministic fallback used"
    return result

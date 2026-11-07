"""Server-side SDK. Never expose collector keys or trust tenant claims from clients."""

import httpx

from .models import Event


class SentinelUnavailable(RuntimeError):
    pass


class SentinelClient:
    def __init__(self, base_url: str, collector_key: str, timeout: float = 2):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Authorization": f"Bearer {collector_key}"},
        )

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _send(self, path, event):
        try:
            response = self.http.post(path, json=event.model_dump(mode="json"))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("allowed"), bool):
                raise ValueError("Invalid decision response")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            # Never turn an unavailable guard into an implicit allow.
            raise SentinelUnavailable("Sentinel did not return a valid decision") from exc

    def observe(self, event: Event):
        return self._send("/v1/events", event)

    def decide(self, event: Event):
        return self._send("/v1/decisions", event)

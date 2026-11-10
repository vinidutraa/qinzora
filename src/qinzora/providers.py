"""Structured model adapters. No tools, credentials or execution rights in prompts."""

import asyncio
import json
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ValidationError


class ModelUnavailable(RuntimeError):
    """The provider failed or did not return a complete, valid structured response."""


class StructuredModel(Protocol):
    """Implement this port to use another model SDK or agent framework."""

    async def generate[T: BaseModel](
        self, system: str, context: dict[str, Any], result_type: type[T]
    ) -> T: ...


class HTTPStructuredModel:
    """Ollama or a chat-completions endpoint supporting JSON Schema.

    The integrator configures the trusted base URL and owns this async lifecycle.
    No retries or implicit model fallback. Not every compatible endpoint/model
    supports structured output; unsupported requests fail explicitly.
    """

    def __init__(
        self,
        provider: Literal["ollama", "chat_completions"],
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 60,
        max_tokens: int = 2048,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = httpx.URL(base_url)
        if provider not in ("ollama", "chat_completions"):
            raise ValueError("Unsupported model protocol")
        if (
            url.scheme not in ("http", "https")
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError("Model base URL must be an HTTP(S) origin/path without credentials")
        if not model.strip() or len(model) > 200:
            raise ValueError("Invalid model name")
        if not 1 <= max_tokens <= 8192 or not 0 < timeout <= 300:
            raise ValueError("Invalid model timeout or output token limit")
        self.provider, self.model, self.max_tokens = provider, model, max_tokens
        self.timeout = timeout
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def __aenter__(self) -> "HTTPStructuredModel":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.http.aclose()

    async def generate[T: BaseModel](
        self, system: str, context: dict[str, Any], result_type: type[T]
    ) -> T:
        schema = result_type.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": system
                + "\nReturn only JSON matching this schema: "
                + json.dumps(schema, ensure_ascii=False),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, allow_nan=False)},
        ]
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if self.provider == "ollama":
            path = "api/chat"
            body.update(
                format=schema,
                think=False,
                options={"temperature": 0, "num_predict": self.max_tokens},
            )
        else:
            # base_url includes /v1 (or a provider-specific prefix), if required.
            path = "chat/completions"
            body.update(
                temperature=0,
                max_tokens=self.max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "qinzora_response", "schema": schema},
                },
            )
        try:
            async with asyncio.timeout(self.timeout):
                async with self.http.stream("POST", path, json=body) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if len(raw) + len(chunk) > 262144:
                            raise ValueError("Model response exceeds limit")
                        raw.extend(chunk)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Invalid model envelope")
            if self.provider == "ollama":
                if data.get("done") is not True or data.get("done_reason", "stop") != "stop":
                    raise ValueError("Incomplete model response")
                content = data["message"]["content"]
            else:
                choice = data["choices"][0]
                if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                    raise ValueError("Invalid model choice")
                if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                    raise ValueError("Incomplete or refused model response")
                content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty model response")
            return result_type.model_validate_json(content)
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            ValidationError,
        ):
            # Provider bodies/errors can contain prompts or credentials. Do not expose them.
            raise ModelUnavailable(
                "Model did not return a complete, valid structured response"
            ) from None

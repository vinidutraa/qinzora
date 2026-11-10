---
title: "Python SDK"
description: "Integrate synchronous or asynchronous Python clients with explicit decisions and failure handling."
---
# Python SDK

Both clients validate `allowed`, the returned `event_id` and the operation `mode`. A response for another event or an observation returned to a decision request raises `QinzoraUnavailable`; it never becomes an implicit allow. The event is serialized before sending so later caller mutation cannot change which response is expected.

`qinzora.client` exports `QinzoraClient`, `AsyncQinzoraClient` and `QinzoraUnavailable`. Both provide `observe(event)` and `decide(event)`. Keep a client for the application lifecycle and close it on shutdown. No FastAPI dependency is imposed on the host; other languages can use HTTP.

```python
from qinzora.client import QinzoraClient
from qinzora.models import Event


def is_allowed(url: str, key: str, event: Event) -> bool:
    with QinzoraClient(url, key) as guard:
        return guard.decide(event)["allowed"]
```

Construct `Event` from verified identity and resource ownership on the server. A false decision prevents the operation; true still requires host authorization. Handle `QinzoraUnavailable` as explicit unavailability, such as HTTP 503 without protected data.

```python
from qinzora.client import AsyncQinzoraClient
from qinzora.models import Event


async def is_allowed(url: str, key: str, event: Event) -> bool:
    async with AsyncQinzoraClient(url, key) as guard:
        return (await guard.decide(event))["allowed"]
```

Default timeout is 2 seconds. Clients disable redirects/environment proxy inheritance and require a boolean `allowed`. Transport, status or invalid-response failures raise `QinzoraUnavailable`. There are no automatic retries or durable queues. An explicit retry after timeout must reuse the same `Event`/`event_id`: the server may already have committed. Async cancellation propagates and does not imply remote rollback. `observe` awaits the HTTP response; it is not a background queue.

See the executable [documents API example](https://github.com/vinidutraa/qinzora/blob/main/examples/documents_api.py) and the [AI adapter contract](ai.md).

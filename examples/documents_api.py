"""Fictional identities demo-a/demo-b; NOT production authentication.

Set SENTINEL_URL and SENTINEL_COLLECTOR_KEY, then run:
uvicorn examples.documents_api:app --port 8766
"""

from api_sentinel.demo_app import create_documents_app

app = create_documents_app()

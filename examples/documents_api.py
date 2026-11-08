"""Fictional identities demo-a/demo-b; NOT production authentication.

Set QINZORA_URL and QINZORA_COLLECTOR_KEY, then run:
uvicorn examples.documents_api:app --port 8766
"""

from qinzora.demo_app import create_documents_app

app = create_documents_app()

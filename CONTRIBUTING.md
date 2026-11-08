# Contribuir

Instale o ambiente pelo README. Use apenas aplicações locais/fictícias nos testes. Não inclua `.env`, chaves, dados pessoais ou bancos de execução em commits.

Antes de propor uma alteração:

```text
python -m ruff check src tests examples scripts
python -m ruff format --check src tests examples scripts
python -m pytest -q
python scripts/http_smoke.py
qinzora demo --live
```

Políticas novas precisam de cenários de fronteira e concordância entre replay e avaliação ao vivo. Mudanças no banco precisam de migração que preserve dados existentes. Resultados de carga devem identificar ambiente, número de requisições e concorrência.

# Usar em outro projeto

## 1. Experimentar primeiro

Baixe o ZIP ou clone o repositório. Siga a instalação do README e execute `sentinel demo --live`. Esse comando cria dois processos locais independentes, usa dados fictícios, testa decisões e encerra os recursos criados. Não precisa de IA para funcionar.

## 2. Instalar o pacote

O código é distribuído como pacote Python. No ambiente virtual de sua aplicação, instale o arquivo `.whl` baixado de Releases:

```text
python -m pip install CAMINHO_DO_ARQUIVO.whl
```

Ou instale diretamente do código baixado com `python -m pip install CAMINHO_DA_PASTA`. A instalação obtém as dependências. Para versões reproduzíveis, instale antes `requirements-lock.txt` conforme o README. O pacote não está no PyPI.

## 3. Executar o serviço

Em uma pasta própria para os dados do Sentinel, execute `sentinel init` e `sentinel serve`. Guarde o `.env` privado. O serviço escuta em `http://127.0.0.1:8765`. Não use as chaves fictícias dos exemplos como autenticação real.

Provisionamento e políticas: siga [OPERACAO.md](OPERACAO.md). Crie uma conta para a integração e guarde separadamente as chaves de gestão e coleta. A chave gestora cria e simula políticas; o código da aplicação usa a chave coletora.

## 4. Consultar antes da operação

```python
from api_sentinel.client import SentinelClient, SentinelUnavailable
from api_sentinel.models import Event

# Em aplicações web, mantenha o cliente no ciclo de vida da aplicação.
with SentinelClient(sentinel_url, collector_key) as guard:
    try:
        decision = guard.decide(Event(
            service="documents",
            route="/documents/{id}",
            subject=verified_user.id,
            actor_tenant=verified_user.company_id,
            resource_tenant=document.company_id,
        ))
    except SentinelUnavailable:
        # Responda indisponibilidade (ex.: HTTP 503), sem executar a operação.
        raise
    if not decision["allowed"]:
        raise PermissionError("Policy denied access")
    # Ainda verifique as permissões próprias da aplicação antes de retornar dados.
```

As variáveis representam dados que sua aplicação já verificou. Não aceite empresa/identidade de headers arbitrários do navegador. Veja a implementação executável em [examples/documents_api.py](../examples/documents_api.py).

## Flexibilidade e limites

- O SDK funciona com aplicações Python, sem obrigar o uso de FastAPI. O exemplo pronto usa FastAPI.
- Outras linguagens podem chamar os mesmos endpoints HTTP/JSON; isso exige implementar a integração correspondente. Não há SDK pronto para cada linguagem.
- Não é necessário reescrever a aplicação inteira. É necessário enviar os eventos, fornecer contexto confiável e aplicar a decisão no ponto certo.
- `/v1/events` apenas observa; `/v1/decisions` registra e decide. Não envie a mesma operação duas vezes.
- Políticas candidatas observam. Para bloquear, revise a simulação e ative explicitamente uma política compatível.
- Para coleta assíncrona de observações em sistemas de maior volume, implemente uma fila na integração. O SDK fornecido é síncrono.
- Reutilização sob licença MIT. O serviço não substitui autenticação/autorização existentes.

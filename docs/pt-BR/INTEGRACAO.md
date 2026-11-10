# Usar em outro projeto

## 1. Experimentar primeiro

Baixe o ZIP ou clone o repositório. Siga a instalação do README e execute `qinzora demo --live`. Esse comando cria dois processos locais independentes, usa dados fictícios, testa decisões e encerra os recursos criados. Não precisa de IA para funcionar.

## 2. Instalar o pacote

O código é distribuído como pacote Python. No ambiente virtual de sua aplicação, instale o arquivo `.whl` baixado de Releases:

```text
python -m pip install CAMINHO_DO_ARQUIVO.whl
```

Ou instale diretamente do código baixado com `python -m pip install CAMINHO_DA_PASTA`. A instalação obtém as dependências. Para versões reproduzíveis, instale antes `requirements-lock.txt` conforme o README. O pacote não está no PyPI.

## 3. Executar o serviço

Em uma pasta própria para os dados do Qinzora, execute `qinzora init` e `qinzora serve`. Guarde o `.env` privado. O serviço escuta em `http://127.0.0.1:8765`. Não use as chaves fictícias dos exemplos como autenticação real.

Provisionamento e políticas: siga [OPERACAO.md](OPERACAO.md). Crie uma conta para a integração e guarde separadamente as chaves de gestão e coleta. A chave gestora cria e simula políticas; o código da aplicação usa a chave coletora.

## 4. Consultar antes da operação

```python
from qinzora.client import QinzoraClient, QinzoraUnavailable
from qinzora.models import Event

# Em aplicações web, mantenha o cliente no ciclo de vida da aplicação.
with QinzoraClient(qinzora_url, collector_key) as guard:
    try:
        decision = guard.decide(Event(
            service="documents",
            route="/documents/{id}",
            subject=verified_user.id,
            actor_tenant=verified_user.company_id,
            resource_tenant=document.company_id,
        ))
    except QinzoraUnavailable:
        # Responda indisponibilidade (ex.: HTTP 503), sem executar a operação.
        raise
    if not decision["allowed"]:
        raise PermissionError("Policy denied access")
    # Ainda verifique as permissões próprias da aplicação antes de retornar dados.
```

As variáveis representam dados que sua aplicação já verificou. Não aceite empresa/identidade de headers arbitrários do navegador. Veja a implementação executável em [examples/documents_api.py](https://github.com/vinidutraa/qinzora/blob/main/examples/documents_api.py).

## Flexibilidade e limites

- O SDK funciona com aplicações Python, sem obrigar o uso de FastAPI. O exemplo pronto usa FastAPI.
- Outras linguagens podem chamar os mesmos endpoints HTTP/JSON; isso exige implementar a integração correspondente. Não há SDK pronto para cada linguagem.
- Não é necessário reescrever a aplicação inteira. É necessário enviar os eventos, fornecer contexto confiável e aplicar a decisão no ponto certo.
- `/v1/events` apenas observa; `/v1/decisions` registra e decide. Não envie a mesma operação duas vezes.
- Políticas candidatas observam. Para bloquear, revise a simulação e ative explicitamente uma política compatível.
- Para coleta assíncrona de observações em sistemas de maior volume, implemente uma fila na integração. O SDK oferece clientes síncrono e assíncrono; não inclui uma fila durável.
- Reutilização sob licença MIT. O serviço não substitui autenticação/autorização existentes.

## Integração assíncrona

Em aplicações com event loop, reutilize `AsyncQinzoraClient` no ciclo de vida da aplicação:

```python
from qinzora.client import AsyncQinzoraClient, QinzoraUnavailable

async with AsyncQinzoraClient(qinzora_url, collector_key) as guard:
    try:
        decision = await guard.decide(event)
    except QinzoraUnavailable:
        raise  # Não execute a operação sem uma decisão válida.
    if not decision["allowed"]:
        raise PermissionError("Policy denied access")
```

`event` é um `Event` com identidade e propriedade verificadas pela aplicação, como no exemplo síncrono. O SDK não faz retentativas automáticas. Se a aplicação repetir uma chamada após timeout, reutilize o mesmo evento e seu `event_id`: o servidor pode ter concluído a primeira chamada mesmo sem entregar a resposta. Cancelamento de uma coroutine é propagado; não significa que a operação remota foi desfeita. `observe` coleta observações, mas continua aguardando a resposta HTTP e não é uma fila em segundo plano.


## Adaptadores de modelo estruturado

O módulo `qinzora.providers` oferece o contrato assíncrono `StructuredModel` e o adaptador `HTTPStructuredModel`. O integrador escolhe o modelo e um dos protocolos disponíveis: `ollama` ou `chat_completions`. Outro SDK ou framework pode implementar `generate(system, context, result_type)` para retornar uma instância Pydantic validada. Esses adaptadores não executam ações de administração; são a camada de inferência para a integração com o executor.

```python
import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict
from qinzora.providers import HTTPStructuredModel

class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["observe", "simulate"]

async def main():
    async with HTTPStructuredModel(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="MODELO_INSTALADO",
    ) as model:
        proposal = await model.generate(
            "Escolha uma das ações disponíveis usando as evidências.",
            {"observed_errors": 12},
            Proposal,
        )
        print(proposal.model_dump_json())

asyncio.run(main())
```

No protocolo `chat_completions`, a URL deve incluir o prefixo exigido pelo servidor, por exemplo `https://servidor/v1`; o adaptador acrescenta `chat/completions`. A chave opcional é passada em `api_key`, pelo código do servidor. O endpoint e o modelo são configuração confiável do integrador, nunca valores escolhidos pelo próprio modelo.

O servidor deve suportar `response_format` com JSON Schema. Compatibilidade com chat não garante suporte a essa opção nem aos mesmos parâmetros de geração. Falhas de protocolo e respostas fora do schema geram `ModelUnavailable`; não há retentativa ou fallback implícito. Cancelamento assíncrono é propagado. O adaptador recusa respostas com término incompleto e limita o envelope recebido a 256 KiB. O modelo ainda pode produzir uma proposta incorreta que corresponda ao schema: validação estrutural não autoriza execução.

O contexto fornecido é enviado ao endpoint configurado. O integrador deve selecionar apenas os dados necessários e avaliar seu destino; o adaptador não remove automaticamente informações sensíveis de um contexto arbitrário. Credenciais de transporte não são incluídas nas mensagens. Utilize TLS para endpoints remotos.

Referências dos protocolos: [saída estruturada do Ollama](https://docs.ollama.com/capabilities/structured-outputs). Os testes locais dos adaptadores utilizam transporte simulado; não comprovam disponibilidade ou qualidade de inferência de um provedor real.

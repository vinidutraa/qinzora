# API Sentinel

[![Python checks](https://github.com/vinidutraa/api-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/vinidutraa/api-sentinel/actions/workflows/ci.yml)

API Sentinel é um serviço back-end em Python para avaliação de políticas de acesso e comportamento de APIs. A aplicação recebe eventos estruturados, identifica violações, registra evidências e calcula o impacto histórico de uma política antes de sua ativação.

O serviço disponibiliza uma API HTTP/JSON, um cliente Python e comandos de terminal. Pode ser executado como processo independente ou por Docker Compose. A licença MIT permite utilização, modificação e integração em outros projetos, observadas as condições de atribuição.

## Finalidade

Uma aplicação integrada pode utilizar o Sentinel para observar tentativas de acesso, verificar limites de requisições e aplicar políticas de isolamento entre organizações. As regras são declaradas explicitamente e avaliadas por código determinístico.

A simulação permite examinar quais eventos previamente registrados seriam afetados por uma política. A ativação exige a identificação de uma simulação correspondente e a confirmação explícita do impacto pelo operador. Políticas ativas possuem prazo de validade e podem ser revogadas.

O Sentinel não intercepta tráfego automaticamente. A aplicação integrada precisa fornecer os eventos e executar a decisão retornada pelo serviço. Sua autenticação e autorização próprias devem permanecer implementadas.

## Requisitos

- Python 3.12 ou superior.
- Acesso à internet durante a instalação das dependências.
- Docker Engine e Compose somente para a execução por contêiner.
- Ollama e um modelo compatível somente para explicações opcionais por modelo de linguagem.

A demonstração básica não exige Docker, Ollama ou conexão com uma aplicação existente. Os testes de integração usam serviços locais e dados fictícios.

## Download

O código pode ser obtido em **Code → Download ZIP**, por clonagem Git ou na [página de versões](https://github.com/vinidutraa/api-sentinel/releases).

```text
git clone https://github.com/vinidutraa/api-sentinel.git
cd api-sentinel
```

Se o código foi obtido por ZIP, extraia o arquivo e abra um terminal na pasta que contém `pyproject.toml`.

Os arquivos `.whl` disponíveis nas versões podem ser instalados com `python -m pip install CAMINHO_DO_ARQUIVO.whl`. O pacote ainda não é distribuído pelo PyPI. A instalação a partir do repositório, descrita abaixo, permite também consultar exemplos e executar os scripts técnicos.

## Instalação e teste no Windows

No PowerShell, a partir da pasta do projeto:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps .
.venv\Scripts\sentinel.exe demo --present
```

Não é necessário ativar o ambiente virtual. Os caminhos explícitos evitam depender da configuração de execução de scripts do PowerShell.

## Instalação e teste no Linux ou macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps .
.venv/bin/sentinel demo --present
```

Os comandos seguintes utilizam `sentinel` e `python` como abreviações dos executáveis do ambiente virtual. No Windows, correspondem a `.venv\Scripts\sentinel.exe` e `.venv\Scripts\python.exe`. No Linux e macOS, correspondem a `.venv/bin/sentinel` e `.venv/bin/python`.

## Verificação funcional

O comando `sentinel demo --present` executa a integração em dois processos independentes: o serviço Sentinel e uma API fictícia de documentos. As etapas e seus resultados são apresentados no terminal.

O cenário verifica:

1. Identificação dos processos independentes e autenticação da API de exemplo.
2. Consulta permitida ao documento da organização do usuário.
3. Identificação de uma tentativa de acesso entre organizações enquanto a política está em observação.
4. Simulação histórica da política de isolamento.
5. Ativação explícita e aplicação da decisão de negação na API integrada.
6. Revogação da política, preservando a autorização própria da aplicação.
7. Aplicação de limite de tentativas por identidade e rota.
8. Resposta HTTP 503, sem documento, quando o Sentinel fica indisponível.
9. Recuperação após reinício, preservando o banco de dados do cenário.

As etapas concluídas aparecem com `[OK]`. Ao final, o relatório JSON contém `"passed": true`. O comando encerra os processos criados e utiliza armazenamento temporário. Não exige criar `.env` nem provisionar credenciais manualmente.

Outros modos disponíveis:

| Comando | Comportamento |
| --- | --- |
| `sentinel demo` | Executa o cenário sintético pela API interna de testes e retorna JSON. |
| `sentinel demo --live` | Executa os dois processos e retorna o relatório de integração em JSON. |
| `sentinel demo --present` | Executa a integração e exibe cada etapa antes do relatório final. |

Os dados são fictícios. Um cenário concluído comprova o comportamento verificado, não uma garantia de eficácia para qualquer aplicação ou carga.

## Executar o serviço continuamente

Para utilizar uma instância persistente:

```text
sentinel init
sentinel serve
```

`init` cria `.env` com um token administrativo aleatório e o caminho do banco. O arquivo não é sobrescrito se já existir. Mantenha-o privado e fora do controle de versão.

Por padrão, o serviço atende em `http://127.0.0.1:8765` e utiliza `data/sentinel.sqlite`. A documentação automática da API fica em `/docs`, o contrato OpenAPI em `/openapi.json` e a verificação de disponibilidade em `/healthz`.

Para alterar o endereço ou a porta, utilize `sentinel serve --host ENDERECO --port PORTA`. A exposição fora da máquina local exige infraestrutura apropriada, incluindo TLS, controle de acesso e limites de conexão.

## Funcionamento das políticas

### Recebimento de eventos

A integração envia um evento com o serviço, o modelo da rota, o método HTTP e um identificador opaco do sujeito. Políticas de isolamento também exigem a organização da identidade e a organização proprietária do recurso.

Esses valores devem ser derivados de informações verificadas pelo servidor. Não devem ser aceitos como declarações arbitrárias do navegador. Corpos de requisição, tokens e parâmetros de consulta não fazem parte do contrato de eventos.

### Observação e decisão

`POST /v1/events` registra e avalia um evento sem aplicar bloqueio. `POST /v1/decisions` registra a tentativa e retorna `allowed` para que a aplicação integrada decida se continua a operação. Não envie a mesma tentativa aos dois endpoints: isso duplicaria a contagem. A reutilização do mesmo identificador em modos diferentes é rejeitada.

Uma resposta `allowed: true` não substitui a autorização própria da aplicação. Ela indica que nenhuma política de bloqueio ativa do Sentinel negou aquela tentativa.

### Simulação e ativação

Uma política é criada no estado candidato. Sua simulação utiliza um snapshot dos eventos retidos, sem repetir as operações reais. O relatório apresenta quantidade de eventos correspondentes, contagens afetadas e uma amostra dos identificadores.

A ativação exige uma simulação da mesma política, realizada há menos de 15 minutos, com eventos correspondentes e confirmação de impacto. Eventos recebidos depois do snapshot não integram aquele relatório. A expiração ou revogação interrompe a aplicação da política.

### Tipos disponíveis

| Política | Avaliação | Pode negar operações após ativação? |
| --- | --- | --- |
| `rate_limit` | Quantidade de tentativas por serviço, rota e sujeito em uma janela. | Sim |
| `tenant_isolation` | Presença e correspondência das organizações da identidade e do recurso. | Sim |
| `error_burst` | Concentração de respostas com status a partir de 400. | Não; observação de respostas concluídas. |
| `latency` | Latência observada superior ao limite configurado. | Não; observação de respostas concluídas. |

## Integração com outras aplicações

O cliente `SentinelClient` pode ser utilizado em aplicações Python sem obrigar o uso de FastAPI. A aplicação de exemplo usa FastAPI. Outras linguagens podem consumir o contrato HTTP/JSON mediante integração própria.

O fluxo de configuração é:

1. Criar uma conta de integração com o token administrativo.
2. Armazenar separadamente as chaves de gestão e coleta retornadas.
3. Criar políticas com a chave de gestão.
4. Enviar eventos ou consultar decisões com a chave de coleta.
5. Simular e revisar uma política antes de ativá-la.
6. Executar a decisão na aplicação e tratar indisponibilidade explicitamente.

O [guia de integração](docs/INTEGRACAO.md) apresenta o uso do SDK. O [guia de operação](docs/OPERACAO.md) descreve provisionamento, políticas, rotação de chaves, exportação e retenção. A implementação de referência está em [examples/documents_api.py](examples/documents_api.py).

## Explicações opcionais por IA

As decisões são determinísticas. A integração opcional com Ollama produz apenas um comentário sobre as evidências e não pode ativar políticas ou autorizar operações.

Configure `SENTINEL_OLLAMA_URL` e `SENTINEL_OLLAMA_MODEL` no ambiente ou em `.env`. O endpoint `POST /v1/incidents/{id}/explain` envia somente categorias conhecidas, significados fixos e contagens.

A resposta mantém a explicação canônica em `explanation`. O comentário do modelo, quando disponível, aparece separadamente em `model_explanation`. Em caso de falha, a explicação determinística permanece disponível. O timeout de inferência é de 60 segundos, com timeout de conexão de 2 segundos. O texto do modelo pode conter interpretações incorretas e deve ser tratado como consultivo.

## Docker Compose

Com Docker Engine e Compose disponíveis, gere a configuração com `sentinel init` e execute:

```text
docker compose up --build -d
docker compose ps
docker compose down
```

O volume `sentinel-data` preserva o banco. O contêiner utiliza usuário sem privilégios de root e filesystem somente leitura, com diretórios de escrita específicos. A publicação padrão é restrita ao loopback. A variável `SENTINEL_PORT` altera a porta externa.

O script `python scripts/docker_smoke.py` verifica a imagem, o fluxo de políticas e a persistência após reinício. Ele cria um projeto Compose exclusivo e remove somente os recursos criados por esse teste.

## Testes e manutenção

Para instalar as ferramentas de desenvolvimento no ambiente virtual:

```text
python -m pip install --require-hashes -r requirements-dev-lock.txt
python -m pip install --no-deps -e .
python -m pytest -q
python -m ruff check src tests examples scripts
python -m ruff format --check src tests examples scripts
python scripts/http_smoke.py
```

A CI executa testes em Windows e Linux com Python 3.12 e 3.14, além do teste Docker em Linux. Os resultados atuais podem ser consultados em [GitHub Actions](https://github.com/vinidutraa/api-sentinel/actions).

O comando `sentinel check examples/baseline.json examples/regression.json` retorna código 1 porque o segundo manifesto remove intencionalmente uma proteção. Comparar `baseline.json` consigo mesmo retorna código 0. O verificador compara controles declarados; não inspeciona toda a lógica de autorização da aplicação.

Os scripts `scripts/benchmark.py` e `scripts/ollama_smoke.py` permitem reproduzir verificações de carga local e inferência real, respectivamente. Seus resultados dependem do ambiente de execução. Consulte [VALIDACAO.md](docs/VALIDACAO.md) para os procedimentos e critérios.

## Limites operacionais

O armazenamento atual utiliza SQLite e transações serializadas. O desenho atende uma instância do serviço e não fornece armazenamento distribuído ou alta disponibilidade. O replay é limitado a 100 mil eventos retidos por conta e falha explicitamente se esse limite for excedido.

O limite da API de controle é de 600 requisições por minuto por chave de cliente. Há limite de 1 MiB para corpos e de 100 políticas por conta. A capacidade de eventos é um limite técnico configurável. A auditoria local não é inviolável.

O SDK é síncrono. Integrações que exigem coleta assíncrona, filas, processamento distribuído ou maior volume precisam implementar e validar esses componentes. O serviço não substitui autenticação, autorização, proteção de borda ou o controle de propriedade dos dados da aplicação integrada.

## Documentação

- [Arquitetura e decisões](docs/ARQUITETURA.md)
- [Integração em outro projeto](docs/INTEGRACAO.md)
- [Operação e manutenção](docs/OPERACAO.md)
- [Procedimentos de validação](docs/VALIDACAO.md)
- [Contribuição](CONTRIBUTING.md)
- [Licença MIT](LICENSE)

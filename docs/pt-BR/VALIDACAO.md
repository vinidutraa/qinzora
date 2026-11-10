# Procedimentos de validação

## Objetivo

A validação verifica o contrato HTTP, as decisões determinísticas, a concordância entre replay e avaliação de eventos, a persistência e o comportamento diante de falhas. Os cenários utilizam identidades, organizações e recursos fictícios.

## Testes automatizados

Execute `python -m pytest -q` após instalar as dependências de desenvolvimento. A suíte cobre autenticação, escopos de chave, isolamento entre contas, idempotência, conflitos de eventos, capacidade de armazenamento, entrada inválida, limites de corpo, rotação, expiração, concorrência, migração de banco e exportação paginada.

Também são verificadas respostas inválidas do serviço, códigos HTTP de erro, timeout do SDK e indisponibilidade do modelo. O resultado esperado é o encerramento da suíte sem falhas. A quantidade de casos pode variar conforme a versão.

## Integração em processos independentes

`qinzora demo --live` inicia o serviço e a aplicação de documentos em processos separados. O teste verifica decisões por HTTP, ativação, revogação, limites de tentativas, indisponibilidade e recuperação com o banco preservado.

O critério de sucesso é um relatório com `passed: true`. A aplicação integrada deve responder 503 e não retornar o documento quando o serviço de políticas estiver indisponível. Sua autorização própria deve continuar impedindo acesso entre organizações após a revogação da política do Qinzora.

`python scripts/http_smoke.py` verifica o serviço diretamente por HTTP em loopback, incluindo provisionamento, observação, simulação, ativação e negação. Os processos e bancos temporários são encerrados ao final.

## Verificação de contêiner

`python scripts/docker_smoke.py` exige Docker Engine e Compose. O procedimento constrói a imagem, aguarda disponibilidade, testa o fluxo de políticas, reinicia o serviço e verifica a preservação dos eventos no volume.

O script utiliza um projeto Compose com identificador exclusivo. Ao encerrar, remove os recursos pertencentes a esse projeto. Não deve ser substituído por comandos globais de limpeza de contêineres ou volumes.

## Carga local

```text
python scripts/benchmark.py --requests 400 --concurrency 8
```

O script cria seu próprio serviço local e registra distribuição dos códigos HTTP, duração, vazão e percentis de latência. Um segundo cenário avalia o motor de replay sobre 100 mil eventos sintéticos.

As medições de replay puro excluem HTTP e persistência. Os resultados não constituem SLA, capacidade garantida ou estimativa de eficácia de proteção em produção. Comparações exigem registrar versão, sistema operacional, concorrência e condições equivalentes.

## Integração opcional com modelo real

```text
python scripts/ollama_smoke.py --model NOME_DO_MODELO
```

Ollama e o modelo informado devem estar disponíveis. O script chama o endpoint autenticado de explicação com evidências fictícias. O resultado só é considerado aprovado se `source` for `ollama` e não houver erro do modelo. O fallback determinístico não é tratado como inferência real bem-sucedida.

Esse procedimento verifica integração, não qualidade ou correção factual de todas as respostas. O comentário gerado é separado da explicação canônica e não altera permissões.

## Integração contínua

O workflow `.github/workflows/ci.yml` executa a suíte em Windows e Linux com Python 3.12 e 3.14, verificações de formatação e dependências, além de um job Docker em Linux. Consulte a [execução correspondente ao commit](https://github.com/vinidutraa/qinzora/actions) antes de afirmar que uma versão foi aprovada.

## Escopo dos resultados

Os testes demonstram os cenários implementados. Não substituem validação da aplicação integrada, testes de carga no ambiente de destino, revisão de políticas, backups ou avaliação de privacidade. Publicar o repositório distribui o código e não hospeda o serviço.

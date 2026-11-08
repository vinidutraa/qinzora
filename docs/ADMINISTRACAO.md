# Administração de políticas por IA

O módulo `qinzora.administration` permite que um modelo proponha ações de administração e que um executor aplique essas ações dentro das permissões definidas pelo integrador. O modelo não recebe conexão de banco, chaves do Qinzora, funções executáveis ou acesso arbitrário ao sistema operacional.

O fluxo disponível administra políticas do Qinzora. Não altera automaticamente código, infraestrutura, autenticação da aplicação ou configurações de qualquer servidor externo. A aplicação integrada continua responsável por consultar e aplicar as decisões de acesso.

## Operações disponíveis

- `stage_policy`: cria uma política candidata, que observa eventos sem bloquear operações.
- `enforce_policy`: cria uma política, executa replay sobre os eventos retidos e a ativa temporariamente se os critérios configurados forem atendidos. Somente isolamento entre organizações e limite de tentativas podem bloquear.
- `revoke_policy`: revoga uma política cujo identificador tenha sido explicitamente autorizado pelo integrador.

Um plano contém até cinco operações. Uma lista vazia representa a decisão de não alterar as políticas. A justificativa é texto informativo, pode conter interpretações incorretas e não é interpretada como comando nem tratada como evidência. Os critérios de execução são calculados pelo código.

## Configuração e execução por terminal

Copie `examples/management.json` para um arquivo local e informe o banco existente, a conta provisionada, o protocolo e o modelo. O caminho do banco é relativo ao diretório atual do terminal. Não use uma cópia independente do banco se a intenção for administrar o serviço em execução.

```text
qinzora manage --config CAMINHO_DO_ARQUIVO.json
```

O comando chama o modelo escolhido e persiste um plano em estado `draft`. Nenhuma política é alterada nessa etapa. A conta precisa existir e estar habilitada. Os eventos devem ter sido coletados previamente pela integração.

Para executar exatamente o plano apresentado, utilizando o identificador retornado:

```text
qinzora manage --config CAMINHO_DO_ARQUIVO.json --plan IDENTIFICADOR --execute
```

Essa execução não faz nova inferência. Para propor e executar em um único ciclo:

```text
qinzora manage --config CAMINHO_DO_ARQUIVO.json --execute
```

O arquivo de exemplo utiliza `allow_enforce: false`. A opção `--execute` não ignora essa restrição. Para autorizar ativação automática, o operador deve configurar `allow_enforce: true` e escolher os demais limites. O acesso ao arquivo e ao banco equivale a acesso de operador local; este comando não é um endpoint público de autenticação.

O protocolo `ollama` utiliza um modelo instalado no endpoint configurado. O protocolo `chat_completions` exige suporte a JSON Schema e utiliza uma URL que já inclua o prefixo necessário, como `/v1`. Para autenticar o provedor, configure `api_key_env` com o nome de uma variável de ambiente que contenha a chave. A chave não deve ser escrita no arquivo de configuração.

## Permissões e critérios de execução

`Authority` é configuração confiável da aplicação, separada de `PlanProposal`, que é a resposta do modelo. `objective` descreve o objetivo operacional definido pelo integrador. O schema enviado ao modelo restringe os tipos de ação disponíveis e os limites de parâmetros de ativação; o executor verifica novamente as permissões. A configuração delimita serviços e rotas, habilitação de criação/ativação, políticas que podem ser revogadas, duração máxima de ativação e parâmetros permitidos para limites de tentativas.

Antes de uma ativação, o executor refaz a simulação com os eventos disponíveis naquele momento. Os padrões exigem pelo menos um exemplo legítimo e uma ocorrência abusiva afetada, nenhum evento desconhecido afetado e taxa de falsos positivos observada igual a zero. Esses valores são configuráveis. As classificações são fornecidas pela aplicação, não descobertas pelo modelo, e precisam de validação pelo integrador. Uma amostra pequena ou incorretamente classificada não demonstra segurança futura.

O plano expira por padrão em cinco minutos. Mudanças nas políticas dentro do escopo ou nas permissões configuradas exigem uma nova proposta. Eventos adicionais não invalidam automaticamente um plano: eles entram na nova simulação e podem impedir a execução. A conta é verificada novamente antes de cada transação.

O contexto enviado ao modelo contém configurações das políticas, permissões e contagens agregadas por escopo. Não contém identidades de eventos, organizações das identidades/recursos, corpos ou queries. Nomes de serviços, rotas, políticas e seus identificadores continuam sendo informações da aplicação e são enviados ao provedor escolhido.

## Transações, repetição e integração Python

`Administrator` recebe uma fábrica de transações vinculada a uma conta, uma implementação de `StructuredModel` e uma instância de `Authority`. A inferência acontece entre transações, sem manter o bloqueio de escrita do SQLite durante a espera pelo modelo.

```python
from functools import partial

from qinzora.administration.contracts import Authority
from qinzora.administration.controller import Administrator
from qinzora.repository import account_transaction

administrator = Administrator(
    repository=partial(account_transaction, store, account_id),
    model=structured_model,
    authority=Authority(
        routes=[{"service": "documents", "route": "/documents/{id}"}],
        allow_enforce=True,
    ),
)
plan = await administrator.propose()
result = administrator.execute(plan["id"])
```

`store` é o `Store` inicializado do serviço; `account_id` é uma conta que a aplicação hospedeira já autorizou o chamador a administrar. `structured_model` implementa o contrato descrito em [Integração](INTEGRACAO.md). O controlador não exige FastAPI, LangChain ou outro framework de agentes.

Para outro armazenamento, a fábrica deve fornecer um `Repository` com commit ao concluir, rollback em caso de erro e serialização das escritas concorrentes. Não use uma implementação sem essas garantias para executar planos.

Na implementação SQLite, todas as ações de um plano são confirmadas na mesma transação. Uma falha na segunda ação desfaz também a primeira. Executar novamente o mesmo plano concluído retorna o resultado armazenado, sem repetir suas ações. Propostas e execuções concluídas geram auditoria. A auditoria local não é inviolável e esse rollback não abrange operações externas à transação.

## Estado da validação

Os testes cobrem ativação aplicada às decisões da API, escopos, limites, expiração, mudança de permissões, isolamento de contas, conta desabilitada, impacto de novos eventos, rollback de múltiplas ações e execução concorrente/idempotente. O ciclo configurado também é testado com o adaptador HTTP de modelo, usando transporte simulado. Isso não equivale a inferência real validada com um provedor nem à administração universal de APIs.


Para validar o ciclo com um modelo real e um serviço HTTP isolado, no repositório:

```text
python scripts/administration_smoke.py --model NOME_DO_MODELO
```

O script cria um banco temporário, provisiona uma conta fictícia, registra exemplos legítimos/abusivos, solicita um plano ao modelo local e verifica uma decisão de negação após a execução. `--base-url`, `--provider` e `--api-key-env` permitem configurar outro endpoint compatível. Uma abstenção do modelo ou uma rejeição do executor não é considerada sucesso desse cenário. Não há fallback para uma resposta simulada. O script não usa o banco normal do operador.


## Monitoramento contínuo

```text
qinzora watch --config CAMINHO_DO_ARQUIVO.json --execute --interval 30 --model-timeout 60
```

Sem `--execute`, o monitor apenas persiste propostas. As permissões do arquivo continuam obrigatórias nos dois modos. `Ctrl+C` encerra o processo, cancela a inferência pendente e tenta liberar sua concessão de execução. Uma chamada remota cancelada pode continuar sendo processada pelo provedor; operações já confirmadas no banco não são desfeitas pela parada do monitor.

O monitor compara eventos retidos, políticas, permissões e estado efetivo de expiração. Não chama o modelo novamente quando esse estado permanece igual, inclusive após reinício. Novos eventos e expiração de políticas provocam reavaliação. O checkpoint mantém o que o modelo efetivamente observou, para não ignorar eventos recebidos durante a inferência.

Uma concessão temporária de execução no banco (`lease`) impede duas instâncias de monitorar simultaneamente o mesmo slot. O adaptador de configuração usa o identificador da conta como slot. Um proprietário cujo lease expirou não pode publicar uma proposta nem executar ações depois de perder a concessão. O mecanismo depende das transações serializadas do adaptador e não é uma garantia de alta disponibilidade distribuída. Em integrações próprias, forneça um slot globalmente único por conta.

Falha/timeout de inferência gera espera progressiva, limitada a cinco minutos, antes de outra tentativa. Rejeições de propostas/impacto aguardam mudança no estado observado. Erros inesperados de programação ou armazenamento encerram o monitor e devem ser tratados pelo processo hospedeiro. Resultados de cada ciclo são emitidos como JSON, com estado e identificador do plano, sem contexto completo ou credenciais.

Uma política equivalente já ativa não é duplicada. Ao executar uma defesa equivalente a uma candidata ou política expirada, o controlador reutiliza seu identificador, registra a configuração anterior em auditoria e refaz a simulação antes de ativar. Isso evita criar indefinidamente novas políticas durante renovações. O monitor não garante que o modelo proponha renovação; uma proposta sem ações continua sendo válida.

O histórico considerado continua limitado aos eventos retidos. Reavaliar após expiração não prova que os eventos antigos representem o tráfego atual. O operador deve definir retenção, rótulos e objetivo adequados ao seu ambiente.

Para verificar um ciclo do monitor com inferência e serviço HTTP reais em um banco temporário:

```text
python scripts/administration_smoke.py --model NOME_DO_MODELO --watch
```

Esse cenário verifica um ciclo seguido de parada. Concorrência, reinício, timeout, perda de lease e mudanças durante inferência também possuem testes automatizados controlados; o teste sintético não constitui validação de operação contínua em produção.

# Operação

1. Operador provisiona cliente: `POST /v1/admin/tenants`, Bearer administrador do `.env`, corpo `{"name":"Minha empresa","event_limit":100000}`. Resposta retorna `manager_key` e `collector_key` uma vez. Guarde em gerenciador de segredos; banco contém apenas hashes das chaves de cliente.
2. Gestor cria política: `POST /v1/policies`, Bearer gestor, corpo `{"name":"Limite consultas","service":"documents","kind":"rate_limit","threshold":30,"window_seconds":60,"ttl_seconds":900}`. `route` é `*` ou igualdade exata com modelo de rota.
3. Integração envia para `/v1/events`, Bearer coletor. Obrigatórios: `service`, `route`, `subject`. Reutilize `event_id` nas retentativas. Horários são de recebimento do servidor. `actor_tenant` e `resource_tenant` devem vir de identidade verificada e propriedade do recurso no servidor.
4. Gestor chama `POST /v1/policies/{id}/simulate`. Retorna snapshot, watermark, contagens por rótulo e IDs afetados (amostra até 100). Máximo 100 mil eventos por replay; acima disso falha explicitamente.
5. Após revisar: `POST /v1/policies/{id}/activate`, corpo `{"simulation_id":"...","acknowledge_impact":true}`. Exige simulação correspondente, eventos relevantes, idade menor que 15 minutos e tipo aplicável. Eventos posteriores ao watermark não integram o relatório. Impacto legítimo não é automaticamente proibido: o gestor deve avaliá-lo.
6. Aplicação consulta `/v1/decisions` antes da operação e aplica `allowed`. Contadores por `(service, route, subject)` incluem tentativas negadas. Isolamento nega contexto ausente ou divergência de empresa. Conta cliente do Qinzora é distinta das empresas internas da aplicação integrada.
7. Gestor chama `/v1/policies/{id}/revoke` para reverter. Expiração faz cessar bloqueio sem agendamento. Para reativar, crie candidata e simule novamente.

Candidatas observam e produzem incidentes, mas não bloqueiam. Políticas ativas de bloqueio combinam por negação: basta uma negar. Latência e surtos de erro nunca são ativados como bloqueios.

## Inspeção/manutenção

- `GET /v1/incidents`, `/v1/audit`: `limit` e `offset`.
- `GET /v1/events`: exportação com cursor `after`, `limit` e `next_cursor`; salve os lotes antes de apagar histórico.
- `GET /v1/usage`: capacidade técnica de eventos retidos por projeto integrado.
- `POST /v1/keys/rotate?role=collector` (ou `manager`): chave gestora, substitui a chave da função imediatamente.
- `PATCH /v1/admin/tenants/{id}` com `{"enabled":false}` desabilita tecnicamente a conta; `true` reabilita.
- `qinzora prune --before 2026-01-01T00:00:00+00:00`: manutenção local offline após exportar. Apaga eventos antigos de todas as contas. Auditoria e incidentes ficam retidos. Replay só conhece eventos restantes. Avalie perda de contadores antes de podar janelas recentes.
- Backup: pare o serviço e copie o diretório do banco, incluindo WAL/SHM presentes, ou use `sqlite3.Connection.backup`. Verifique restauração.

600 requisições/minuto por chave de cliente, corpo até 1 MiB e 100 políticas/conta. Administrador/healthcheck precisam de proteção de borda em exposição pública. Escritas e replay são serializados em transação para consistência. Sem worker distribuído nesta versão.

## Regressões

Manifestos: `method`, `path`, `authenticated`, `tenant_isolation`. Compare baseline aprovado à nova versão. Declarações falsas de proteção não são detectadas automaticamente. Novas rotas sem controles exigem revisão, inclusive rotas públicas intencionais.

## Reutilização

Projeto gratuito sob licença MIT. Consulte [INTEGRACAO.md](INTEGRACAO.md) para usar o serviço em outra aplicação. Os exemplos e as evidências usam somente dados fictícios.

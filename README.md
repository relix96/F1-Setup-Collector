# F1 Setup Collector

Base para recolher setups de vários websites, inspirada na estrutura do
`idealista-extractor`.

## Instalação e execução

```bash
poetry install
$env:F1_SETUP_LAPS_URL="https://www.f1laps.com/f1-26/setups/"
poetry run python main.py
```

Sem `--source`, o `main.py` executa todos os coletores registados. Para executar
apenas um: `poetry run python main.py --source f1_laps`.

Para recolher os setups da Google Sheet configurada (separador `gid=2082870794`):

```powershell
poetry run python main.py --game f1_26 --source excel_file
```

O `main.py` grava sempre no MongoDB de producao configurado em
`MONGODB_PRODUCTION_URI`. Copie `.env.example` para `.env` e substitua
`SERVER_IP`, utilizador e password pelos dados do servidor. A base e a colecao
sao configuradas por `MONGODB_DATABASE` e `MONGODB_COLLECTION`.

Os testes de integracao podem escolher a base sem alterar o codigo:

```powershell
$env:TEST_MONGODB_ENV="sandbox"   # MONGODB_SANDBOX_URI (localhost)
$env:TEST_MONGODB_ENV="production" # MONGODB_PRODUCTION_URI (servidor)
poetry run pytest -m live
```

O valor predefinido para testes e `sandbox`, para impedir escritas acidentais
no servidor de producao.

As tabelas auxiliares da folha estão disponíveis através de
`get_tire_temperatures()`, `get_engine_temperatures()` ou, em conjunto,
`get_reference_data()`.

Cada execução recebe um `collector_run_id`. Todos os registos são inseridos como
observações imutáveis com um `_id` novo e `collector_date` em UTC, mesmo quando
os valores são iguais aos de uma execução anterior.

Em produção, o agendador pode definir `COLLECTOR_RUN_ID`. Se não o fizer, o
collector continua a gerar automaticamente um UUID novo.

## Docker

```bash
docker build -t f1-setup-collector:production .
docker run --rm --env-file .env f1-setup-collector:production
```

O método `run()` emite primeiro os setups e depois os registos
`tire_temperature` e `engine_temperature`. Todos incluem um `source_id` estável
para permitir que a API associe observações do mesmo registo lógico.

O Selenium é usado exclusivamente no teste de integração:

```powershell
poetry run pytest -m selenium -s
```

Esse teste abre o Chrome visível e percorre todas as pistas, páginas dry/wet e
detalhes dos setups. A suíte normal exclui os testes marcados com `selenium`.

O pool de proxies é opcional e está desativado por predefinição. Só a fonte
F1Laps está explicitamente autorizada no código a usar o pool; fontes futuras
têm de declarar essa autorização. O ficheiro local `proxies` nunca é incluído
no Git nem na imagem Docker.

Cada linha usa `host:port`, `host:port:user:password` ou uma URL HTTP(S). Ative
com `PROXY_ENABLED=true` e configure `PROXY_FILE`. `COLLECTOR_CONCURRENCY`
limita as pistas concorrentes, enquanto `MAX_REQUESTS_PER_MINUTE` continua a
ser um teto único para a origem e não aumenta com o número de proxies.

O gestor escolhe o proxy seguinte em round-robin/least-used. Por exemplo, três
pedidos consecutivos podem usar `proxy-001`, `proxy-002` e `proxy-003`, mas cada
aquisição continua sujeita ao intervalo global e ao limite por proxy. Um `429`
coloca esse proxy em cooldown e reduz temporariamente a concorrência global.

## Scheduler em produção

O módulo `collector.scheduler` mantém o collector ativo como serviço da Stack
Portainer. Por predefinição executa às 06:00 e 18:00 em `Europe/Lisbon`, grava o
último slot concluído num volume persistente e recupera uma execução perdida
depois de um restart. Configure através de `COLLECTOR_TIMEZONE`,
`COLLECTOR_SCHEDULE_HOURS` e `COLLECTOR_FAILURE_RETRY_SECONDS`.

O limite global configurado é 100 requests/minuto, com 4 pistas concorrentes, 10
requests/minuto por proxy e 1 pedido concorrente por proxy. Aumente o limite
global apenas de forma gradual e com autorização da fonte. O fallback direto
exige `PROXY_ALLOW_DIRECT_FALLBACK=true`.

## Adicionar um website

1. Criar o módulo do site em `collector/<site>/`, herdando de `BaseCollector`.
2. Criar `collector/mapper/<site>_mapper.py`, devolvendo um `SetupDTO`.
3. Registar a classe em `collector/registry.py`.

Cada scraper fica responsável apenas por paginação e extração específicas do
website. HTTP, rate limiting, sessões e proxy são partilhados.

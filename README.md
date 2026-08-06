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

O Selenium é usado exclusivamente no teste de integração:

```powershell
poetry run pytest -m selenium -s
```

Esse teste abre o Chrome visível e percorre todas as pistas, páginas dry/wet e
detalhes dos setups. A suíte normal exclui os testes marcados com `selenium`.

O proxy é opcional e deve ser configurado através de `PROXY_URL`. O ficheiro
`proxies` contém a lista copiada do projeto de referência, mas a aplicação usa
apenas o proxy indicado na variável de ambiente.

## Adicionar um website

1. Criar o módulo do site em `collector/<site>/`, herdando de `BaseCollector`.
2. Criar `collector/mapper/<site>_mapper.py`, devolvendo um `SetupDTO`.
3. Registar a classe em `collector/registry.py`.

Cada scraper fica responsável apenas por paginação e extração específicas do
website. HTTP, rate limiting, sessões e proxy são partilhados.

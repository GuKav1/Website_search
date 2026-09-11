# Prospector — robot de prospeção de websites

Ferramenta **independente** do robot de emails. Encontra sites por
**categoria + país + palavras-chave** e escreve um `.txt` com 1 domínio por linha.

A única coisa que liga as duas ferramentas é esse ficheiro: o prospector produz a lista,
tu carrega-la no robot quando quiseres. Nenhuma delas precisa da outra para funcionar.

```
~/Desktop/Python/prospector/
├── prospector.py        o motor (linha de comandos)
├── app.py               interface web
├── config.json          quem excluir (ver abaixo)
├── requirements.txt
├── resultados/          listas geradas + histórico
└── .cache/              cache das fontes
```

## Interface web

```bash
cd ~/Desktop/Python/prospector
../.venv/bin/streamlit run app.py --server.port 8502
```

Abre em `http://localhost:8502`: escolhes categoria, país, palavras-chave e fontes,
carregas em **Procurar sites** e vês o log ao vivo. No fim tens a tabela com os scores
e botões de download do `.txt` e do `.csv`.

A interface é só uma casca — quem trabalha é o `prospector.py`, lançado como processo
separado. Por isso **podes fechar o browser a meio que a pesquisa continua**; quando
voltares a abrir a página, ela reencontra a corrida e mostra o log onde ia.

```bash
cd ~/Desktop/Python/prospector
../.venv/bin/python prospector.py --categoria filmes --pais PT --validar --max 1000
```

(usa o `.venv` que já existe; para um ambiente próprio: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)

Saídas (pasta `resultados/`):
- `alvos_<categoria>_<data>.txt` → **carrega isto no robot**
- `detalhe_<categoria>_<data>.csv` → score, fonte, título, idioma, ads.txt, rede de ads
- `_ja_vistos.txt` → memória; execuções seguintes não repetem domínios

## config.json — a única ponte para o robot de emails

```json
{ "exclusoes": ["../enviados.txt", "../urls_extraidos.txt", "../Alvos*.txt"] }
```

Ficheiros com domínios que **já contactaste**, para não voltarem a aparecer. Aceita wildcards
e caminhos relativos a esta pasta. Põe `"exclusoes": []` e o prospector deixa de tocar em
seja o que for fora da sua própria pasta — fica 100% autónomo.

## As 7 fontes (`--fontes`)

| fonte | o que faz | porque é que apanha o que o SimilarWeb não tem |
|---|---|---|
| `busca` | motores à escolha, queries geradas em 17 idiomas, com paginação, `site:.tld`, `intitle:` e **footprints de CMS** (`"Powered by DooPlay"`, `"Kernel Video Sharing"`…) | os footprints devolvem centenas de clones do mesmo nicho que nenhum ranking lista |
| `crtsh` | Certificate Transparency: todo o domínio com HTTPS deixa rasto público | apanha domínios **novos e mirrors** dias depois de existirem |
| `links` | grafo de links: abre cada semente e extrai os domínios externos, N níveis | sites destes nichos linkam-se uns aos outros em massa |
| `mirrors` | gera permutações (`ww1.marca.to`, `marca2.cc`, `marcahd.sbs`…) e testa DNS | encontra mirrors vivos que **não estão em índice nenhum** |
| `crux` | Chrome UX Report por país (dados reais de tráfego do Chrome) | tráfego medido, não estimado, com corte por país |
| `sellers` | `sellers.json` de ~25 SSPs = lista pública de publishers | sites que **já monetizam** — prospect perfeito |
| `commoncrawl` | enumera todos os hosts vistos sob um domínio semente | subdomínios e mirrors históricos |

## Motores de busca

`--motores bing,duckduckgo` (ou o selector na interface). Estado que observei a testar
de um IP residencial:

| motor | estado | nota |
|---|---|---|
| `bing` | ✅ fiável | o que mais rende |
| `duckduckgo` | ✅ fiável | |
| `ddg-lite` · `yandex` | ⚠️ instável | rendem pouco, mas rendem |
| `brave` · `mojeek` · `startpage` · `marginalia` | ⚠️ instável | quase sempre captcha ou 429 |
| `google-api` · `serper` | 🔑 precisa de chave | ver abaixo |

**O google.com normal não é possível.** Não é bloqueio contornável com headers ou cookies:
devolve 92 KB de casca JavaScript, zero links de resultado, sem captcha. Não há HTML para ler.
Para ter Google a sério, uma chave. **Nunca no `config.json`** — esse ficheiro está
versionado e uma chave lá dentro fica publicada no GitHub. Usa uma destas vias:

1. `chaves.json` na pasta (está no `.gitignore`) — copia o `chaves.json.exemplo`
2. variáveis de ambiente `SERPER_API_KEY`, `GOOGLE_CSE_KEY`, `GOOGLE_CSE_CX`
3. na Streamlit Cloud: *Settings → Secrets* da app (o `app.py` passa-as ao motor)

[serper.dev](https://serper.dev) dá 2500 pesquisas grátis; o
[Google Programmable Search](https://developers.google.com/custom-search/v1/overview) dá 100/dia
e cobra a partir daí (~5 USD/1000, tecto de 10 000/dia).

**Cuidado com a quota**: cada *página* conta como uma pesquisa. Os valores por defeito
(40 queries × 3 páginas) são 120 chamadas — mais do que os 100 grátis diários do Google.
Por isso existe o `--max-api` (defeito 90): a corrida pára de usar os motores por API
ao fim desse número de chamadas e continua com os gratuitos.

Os motores correm **em paralelo** e cada um tem disjuntor: 3 respostas vazias seguidas e sai
da corrida. Sem isso, um motor bloqueado custava mais de um minuto por query — 3 queries
demoravam 23 minutos, agora demoram 17 segundos.

## Receitas (linha de comandos)

**Nicho novo num país** (do zero):
```bash
../.venv/bin/python prospector.py --categoria filmes --pais ES --fontes busca,crtsh,crux \
  --queries 60 --paginas 4 --max 2000 --validar --min-score 45
```

**Expandir a partir do que já tens** (o mais produtivo):
```bash
../.venv/bin/python prospector.py --seeds ../Alvos2.txt --fontes links,mirrors,crtsh \
  --profundidade 2 --max 5000 --validar --min-score 40
```

**Caçar quem já monetiza**:
```bash
../.venv/bin/python prospector.py --categoria adulto --pais GLOBAL --fontes sellers,crtsh \
  --keywords "tube,porn,xxx" --max 3000 --validar --min-score 50
```

**Cobertura máxima** (deixa correr uma noite):
```bash
../.venv/bin/python prospector.py --categoria filmes --pais BR --seeds ../Alvos2.txt \
  --fontes busca,crtsh,crux,sellers,links,mirrors,commoncrawl \
  --queries 80 --paginas 5 --profundidade 2 --max 20000 --validar --min-score 35
```

## Score (0–100)

`15 base + relevância (até 35) + sinais de país (até 15) + ads.txt (12–17) + rede de ads (10) + site com conteúdo (5) + HTTP 200 (3)`

**Sem uma única palavra-chave do nicho o score é travado em 22** (`nota = fora do nicho`) —
é isto que impede dicionários e portais genéricos de entrarem na lista. O match é por
radical e com fronteira de palavra (`filmes` apanha *filme/filmes*, mas **não** *filmenu*;
`ver` não apanha *verbos*).

A coluna `nota` do CSV:

| nota | significado |
|---|---|
| *(vazio)* | site normal, lido e pontuado |
| `spa/js` | conteúdo renderizado por JS; só se leu o HTML cru (+8 de compensação) |
| `gateway-js` | muro de fingerprint/redirect à entrada → **score fixo 42**. Não se lê sem browser, mas quem põe um muro destes está a monetizar tráfego: vai para a lista e o teu Playwright resolve |
| `parked/vazio` | domínio estacionado ou à venda → fora |
| `fora do nicho` | vivo mas sem uma única palavra-chave → travado em 22 |

Referência: `≥60` excelente · `45–59` bom · `35–44` duvidoso · `<35` lixo.
O CSV guarda **tudo o que está vivo**, o `.txt` só leva o que passa o `--min-score`,
por isso podes baixar o corte sem correr tudo outra vez.

## Notas

- As exclusões vêm do `config.json` mais o histórico próprio. Extra numa execução:
  `--excluir ficheiro.txt`. Para ignorar o histórico: `--repetir`.
- `--nivel host` (default) mantém `ww1.goojara.to` separado de `goojara.to` — de propósito,
  porque nestes nichos cada mirror é um site independente. `--nivel dominio` agrega na raiz.
- Cache em `.cache/` (crt.sh 48h, CrUX/sellers 1 semana, SERPs 12h) — repetir uma
  execução é quase instantâneo e não martela as fontes.
- `mirrors` gera `marcas × variantes × TLDs × prefixos`, o que cresce depressa: controla com
  `--max-mirror` (default 40000 candidatos, ~40s) e `--mirror-tlds` (default 22 de 51).
- `--tld-pais` só aceita domínios com o ccTLD do país (ex.: só `.pt`).
- **Categorias** (11): filmes, series, anime, manga, desporto, adulto, download, jogos,
  noticias, musica, software.
- **Países** (46 + GLOBAL), em 26 idiomas:
  - *Europa*: PT ES FR DE IT NL BE PL CZ HU RO GR SE AT CH IE UK UA RU
  - *Américas*: BR US CA MX AR CL CO PE
  - *Ásia*: TR IN ID MY PH VN TH JP KR TW PK BD
  - *África / Médio Oriente*: ZA NG KE MA DZ EG SA
  - ⚠️ `SA` é a **Arábia Saudita**. A África do Sul é **`ZA`**.
- O `--pais` não é um filtro rígido, é um **enviesamento**: muda o idioma das queries, o
  ccTLD procurado, a região pedida aos motores e o ficheiro da CrUX descarregado. Um `.com`
  com tráfego local entra à mesma — e ainda bem, porque neste nicho a maioria dos sites
  grandes não usa ccTLD. Para filtro a sério: `--tld-pais`.
- Para acrescentar idiomas/nichos: dicionários `LEXICO`, `NOMES` e `FOOTPRINTS` no topo do ficheiro.

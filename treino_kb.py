"""
treino_kb.py — Sessão de treinamento intensivo da Barretão
Roda até as 23h disparando /ensinar + perguntas de teste de diversas áreas.
"""
import time
import json
import requests
from datetime import datetime

TOKEN = "Jd5UXpEBVy1DH9xjDMjEAz56BEgqqPrho383q_dS9ms"
BASE  = "http://localhost:8787"
HDR   = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def ask(text: str, timeout: int = 90, retries: int = 4) -> str:
    for attempt in range(retries):
        try:
            r = requests.post(f"{BASE}/command", json={"text": text}, headers=HDR, timeout=timeout)
            return r.json().get("answer", "")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < retries - 1:
                wait = 15 * (attempt + 1)
                print(f"\n  ⚠ Hub sem resposta, aguardando {wait}s... (tentativa {attempt+1}/{retries})", end="", flush=True)
                time.sleep(wait)
            else:
                return "ERRO: Hub indisponivel"
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            return f"ERRO: {type(e).__name__}: {e}"
    return "ERRO: falha"

def print_ok(n, total, label, resp):
    short = resp[:300].replace('\n', ' ')
    status = "✗ ERRO" if resp.startswith("ERRO") else "✓"
    color  = "\033[91m" if resp.startswith("ERRO") else "\033[92m"
    reset  = "\033[0m"
    print(f"{color}[{n}/{total}] {status}{reset} [{label}] {short}")

# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 1 — ENSINO DIRETO NO KB (25 tópicos técnicos e culturais)
# ══════════════════════════════════════════════════════════════════════════════
ENSINOS = [
    "/ensinar Recursao: Funcao que chama a si mesma com caso base para parar. Fatorial: n*fat(n-1), base fat(0)=1. Fibonacci: fib(n-1)+fib(n-2). Python limite ~1000 chamadas (sys.setrecursionlimit). Use memoizacao com @lru_cache para eficiencia.",
    "/ensinar Big O Notation: Complexidade de algoritmos. O(1) constante, O(log n) busca binaria, O(n) linear, O(n log n) merge/quick sort, O(n^2) bubble sort, O(2^n) exponencial. Sempre analise o pior caso. Espaco tambem tem complexidade.",
    "/ensinar Git comandos: init, clone, add -A, commit -m msg, push origin main, pull --rebase, fetch, branch -b nova, checkout, merge --no-ff, rebase -i HEAD~3, stash/pop, log --oneline --graph, diff HEAD, reset --soft HEAD~1, revert HASH.",
    "/ensinar Docker: Dockerfile: FROM python:3.11-slim, RUN pip install -r requirements.txt, COPY . /app, WORKDIR /app, EXPOSE 8080, CMD python main.py. Comandos: build -t app:1.0 ., run -d -p 8080:80 --name c1 app, exec -it c1 bash, logs c1, ps, stop c1.",
    "/ensinar HTTP Status Codes: 200 OK, 201 Created, 204 No Content, 301 Moved Permanently, 302 Found, 304 Not Modified, 400 Bad Request, 401 Unauthorized sem autenticar, 403 Forbidden autenticado sem permissao, 404 Not Found, 409 Conflict, 422 Unprocessable Entity, 429 Too Many Requests, 500 Internal Server Error, 503 Service Unavailable.",
    "/ensinar SOLID Principios: S=Single Responsibility cada classe uma unica razao para mudar. O=Open-Closed aberto para extensao fechado para modificacao use heranca-interfaces. L=Liskov Substitution subclasse substituivel sem quebrar. I=Interface Segregation interfaces especificas ao cliente. D=Dependency Inversion dependa de abstracoes nao de implementacoes concretas.",
    "/ensinar Estruturas de dados: Array acesso O(1) insercao O(n), Lista ligada insercao O(1) acesso O(n), Stack LIFO push-pop O(1), Queue FIFO enqueue-dequeue O(1), Hash table busca O(1) media O(n) pior, Arvore binaria busca O(log n) balanceada, Heap min-max insercao O(log n) raiz O(1), Grafo adjacencia para redes e caminhos.",
    "/ensinar Algoritmos de ordenacao: Bubble O(n^2) simples educacional, Selection O(n^2) poucos swaps, Insertion O(n^2) otimo para quase-ordenado, Merge O(n log n) estavel divide-conquista, Quick O(n log n) medio O(n^2) pior in-place, Heap O(n log n) in-place nao-estavel, Counting O(n+k) para inteiros pequenos, Radix O(nk) digitos.",
    "/ensinar Padroes de design GoF: Criacionais=Singleton 1 instancia, Factory Method delegacao, Abstract Factory famílias, Builder construcao complexa, Prototype clone. Estruturais=Adapter interface, Decorator comportamento dinamico, Facade simplifica subsistema, Proxy controle de acesso. Comportamentais=Observer pub-sub, Strategy algoritmo intercambivel, Command encapsula acao, Iterator percorre colecao.",
    "/ensinar REST API boas praticas: URLs com substantivos /users /products nao /getUsers, verbos HTTP corretos GET-POST-PUT-PATCH-DELETE, status codes semanticos, versionamento /api/v1/, paginacao ?page=1&limit=20&sort=name, HATEOAS links nas respostas, idempotencia PUT DELETE, documentacao OpenAPI Swagger.",
    "/ensinar SQL avancado: CTE WITH nome AS (SELECT col FROM tabela WHERE cond), Window functions ROW_NUMBER() RANK() LEAD() LAG() SUM() OVER (PARTITION BY col ORDER BY col), COALESCE para substituir NULL, HAVING filtra apos GROUP BY, EXPLAIN ANALYZE mostra plano de execucao, indices compostos (col1, col2) para queries frequentes.",
    "/ensinar Seguranca web OWASP Top10: 1-Injection use prepared statements, 2-Auth quebrada use JWT+bcrypt, 3-Exposicao dados sensiveis HTTPS encriptacao, 4-XXE desabilite entidades XML, 5-Controle acesso quebrado RBAC, 6-Misconfiguracao remova defaults, 7-XSS escape output use CSP, 8-Desserializacao insegura, 9-Componentes vulneraveis atualize dependencias, 10-Logging insuficiente monitore.",
    "/ensinar Python avancado: list comprehension [x**2 for x in range(10) if x%2==0], dict comprehension {k:v for k,v in d.items()}, generators def gen(): yield valor economia de memoria, context managers class CM: __enter__ __exit__, dataclasses @dataclass(frozen=True), type hints def fn(x: list[int]) -> dict[str,Any], walrus x := expr em condicoes, match-case Python 3.10+.",
    "/ensinar Linux comandos essenciais: ls -lah, cd -, pwd, cp -r src dest, mv arq destino, rm -rf dir, mkdir -p a/b/c, cat arq, grep -rn padrao dir, find . -name *.py -mtime -7, chmod 755 arq, chown user:group arq, ps aux | grep proc, kill -15 PID, top/htop, df -h, du -sh *, tar -czf arq.tar.gz dir, ssh -i key user@host, crontab -e.",
    "/ensinar Redes TCP-IP OSI: 7 camadas: Fisica bits, Enlace MAC frames, Rede IP roteamento, Transporte TCP-UDP segmentos, Sessao controle, Apresentacao formato, Aplicacao HTTP-DNS-FTP. TCP 3-way handshake SYN-SYNACK-ACK garante entrega com retransmissao. UDP connectionless sem garantia mais rapido streaming. DNS hierarquico raiz-TLD-dominio.",
    "/ensinar Machine Learning: Supervisionado tem labels classificacao-regressao algoritmos KNN SVM Arvore Random Forest XGBoost. Nao-supervisionado sem labels clustering K-Means DBSCAN reducao PCA. Deep Learning redes neurais profundas CNN imagens RNN texto LSTM sequencias Transformers atencao LLMs. Overfitting memoriza dados use regularizacao dropout cross-validation.",
    "/ensinar Filosofia da mente: Dualismo Descartes mente e corpo substancias separadas. Fisicalismo monismo tudo e fisico inclusive mente. Funcionalismo mente e software do cerebro estados mentais definidos por funcao nao substrato. Qualia experiencia subjetiva qualitativa ex sentir vermelho dor. Problema dificil da consciencia Chalmers por que existe experiencia subjetiva.",
    "/ensinar Economia comportamental Kahneman: Sistema 1 rapido automatico intuitivo propenso a erros. Sistema 2 lento deliberado analitico cansativo. Vieses: ancoragem primeiro numero ancora decisao, aversao a perda perder doi 2x mais que ganhar, efeito dotacao supervaloriza o que ja possui, desconto hiperbolico prefere recompensa imediata, efeito manada segue multidao.",
    "/ensinar Neurociencia basica: Cerebro tem ~86 bilhoes de neuronios conectados por sinapses eletroquimicas. Potencial de acao dispara apos atingir limiar eletrico, propaga pelo axonio. Neurotransmissores: dopamina recompensa-motivacao, serotonina humor-bem-estar, noradrenalina atencao-alertas, GABA inibidor reduz atividade, glutamato excitador aumenta atividade, acetilcolina memoria-aprendizado. Plasticidade sinaptica base do aprendizado.",
    "/ensinar Genetica molecular: DNA dupla helice antiparalela bases nitrogenadas A-T e G-C pareiam por pontes de hidrogenio. Gene segmento de DNA que codifica proteina. Transcricao DNA para mRNA no nucleo. Traducao mRNA para proteina no ribossomo com tRNA. Mutacao pontual troca de base, delecao insercao causa frameshift. CRISPR-Cas9 edita DNA precisamente como tesoura molecular guiada por RNA.",
    "/ensinar Matematica financeira: Juros simples J=P*i*t montante M=P*(1+i*t). Juros compostos M=P*(1+i)^t crescimento exponencial. VPL valor presente liquido soma fluxos futuros descontados a taxa minima. TIR taxa que torna VPL zero. Payback simples tempo para recuperar investimento. ROI=(ganho-custo)/custo*100. No Brasil: SELIC taxa basica, IPCA inflacao oficial, CDI referencia renda fixa.",
    "/ensinar Biomas e Meio Ambiente: Amazonia 40% territorio brasileiro maior biodiversidade terrestre 10% especies do planeta. Cerrado 2o maior bioma nascentes dos rios Sao Francisco Parana Tocantins. Caatinga unico bioma 100% brasileiro semiarido 27 milhoes de habitantes. Pantanal maior zona umida do mundo 150000 km2 ave-capivara-onca. Mata Atlantica 85% destruida resta 12% ainda rico. CO2 em 2025 ultrapassa 425 ppm.",
    "/ensinar Historia do Brasil resumo: 1500 chegada Cabral, 1822 Independencia Dom Pedro I em 7 de setembro, 1888 Lei Aurea Princesa Isabel aboliu escravidao, 1889 Proclamacao da Republica Deodoro da Fonseca, 1930 Revolucao Getulio Vargas, 1937 Estado Novo ditadura Vargas, 1945 redemocratizacao, 1964 Golpe Militar ditadura 21 anos, 1985 Diretas Ja Tancredo Neves redemocratizacao, 1988 Constituicao Cidada vigente.",
    "/ensinar Astronomia: Sol estrela tipo G 4.6 bilhoes anos funde 600 milhoes ton hidrogenio por segundo. Sistema solar 8 planetas Mercurio Venus Terra Marte Jupiter Saturno Urano Netuno. Jupiter maior tem 79 luas. Buraco negro singularidade onde gravidade e infinita horizonte de eventos ponto sem retorno. Via Lactea ~300 bilhoes de estrelas disco espiral 100000 anos-luz diametro. Universo 13.8 bilhoes anos Big Bang expansao acelerada por energia escura 68%.",
    "/ensinar Saude e Corpo Humano: Coracao bombeia 5L de sangue por minuto 100000 batimentos por dia. Pulmoes tem 300 milhoes de alveólos area de ~70m2. Cerebro consome 20% da energia corporal. Sistema imune: neutrofilos primeiros resposta, linfocitos T matam celulas infectadas, B produzem anticorpos, celulas NK atacam tumores. DNA em cada celula tem ~2 metros se estendido. Intestino grosso tem mais bacterias que celulas no corpo 3.8 trilhoes."
]

# ══════════════════════════════════════════════════════════════════════════════
# BLOCO 2 — PERGUNTAS DE TESTE por domínio
# ══════════════════════════════════════════════════════════════════════════════
PERGUNTAS = [
    # Código
    ("Python - primo",        "Escreva em Python funcao que verifica se numero e primo."),
    ("Python - busca bin",    "Escreva em Python funcao de busca binaria iterativa."),
    ("Python - decorador",    "Escreva decorador Python que mede tempo de execucao de funcao."),
    ("Python - Stack",        "Crie classe Stack em Python com push pop peek e is_empty."),
    ("Python - Fibonacci",    "Fibonacci em Python com memoizacao usando lru_cache."),
    ("Python - async req",    "Python async com aiohttp para buscar dados de API com tratamento de erros."),
    ("Python - quicksort",    "Implemente quicksort em Python recursivo."),
    ("Python - context mgr",  "Crie context manager Python para medir tempo com with statement."),
    ("JS - fetch async",      "JavaScript funcao async-await para buscar JSON de API tratando erros."),
    ("TS - interface",        "TypeScript interface Produto com nome string preco number estoque number e metodo calcularDesconto."),
    ("SQL - top 3",           "SQL para top 3 clientes por total de compras incluindo nome e valor."),
    ("SQL - CTE",             "SQL com CTE para calcular media de vendas por mes nos ultimos 12 meses."),
    ("SQL - window fn",       "SQL com ROW_NUMBER() para rankear produtos por vendas dentro de cada categoria."),
    # Ciência
    ("Fisica - termodin",     "O que e entropia? Explique com exemplo do dia a dia."),
    ("Fisica - quântica",     "Explique dualidade onda-particula e o principio da incerteza de Heisenberg."),
    ("Quimica - DNA",         "Como o DNA codifica proteinas? Explique transcricao e traducao."),
    ("Bio - evolucao",        "Explique a teoria da selecao natural de Darwin em 3 frases."),
    ("Astro - buraco negro",  "Como se forma um buraco negro e o que e horizonte de eventos?"),
    # Math
    ("Math - derivada",       "Qual a derivada de f(x) = 3x^4 - 2x^2 + 5x - 1?"),
    ("Math - integral",       "Calcule a integral definida de x^2 de 0 a 3."),
    ("Math - probabilidade",  "Uma moeda honesta e lancada 3 vezes. Qual probabilidade de exatamente 2 caras?"),
    # História / Filosofia
    ("Historia - 1GM",        "Quais foram as causas da Primeira Guerra Mundial?"),
    ("Filosofia - Kant",      "Explique o imperativo categorico de Kant e de um exemplo."),
    ("Psicologia - vieses",   "Liste 5 vieses cognitivos com uma frase explicando cada."),
    # KB e ensino
    ("KB - Big O",            "O que voce sabe sobre Big O Notation?"),
    ("KB - SOLID",            "Explique cada letra de SOLID com um exemplo pratico."),
    ("KB - recursao",         "Me explique recursao e quando usar vs iteracao."),
    ("KB - Docker",           "Crie um Dockerfile para uma API Python FastAPI."),
    ("KB - HTTP",             "Quais os HTTP status codes mais importantes e quando usar cada um?"),
    ("KB - REST",             "Quais as boas praticas para design de uma API REST?"),
    ("KB - algoritmos sort",  "Compare os algoritmos de ordenacao e suas complexidades."),
    # Verificação final
    ("STATUS", "/kb status"),
    ("LISTA TECH", "/kb listar tecnologia"),
    ("LISTA HIST", "/kb listar historia"),
    ("LISTA CIENC", "/kb listar ciência"),
]

# ══════════════════════════════════════════════════════════════════════════════
DEADLINE = datetime.now().replace(hour=23, minute=0, second=0, microsecond=0)
FMT_G = "\033[92m"   # verde
FMT_Y = "\033[93m"   # amarelo
FMT_R = "\033[91m"   # vermelho
FMT_C = "\033[96m"   # ciano
RST   = "\033[0m"

print(f"\n{'='*60}")
print(f"  TREINO INTENSIVO BARRETÃO — até {DEADLINE.strftime('%H:%M')}")
print(f"{'='*60}\n")

# ── Seed inicial ───────────────────────────────────────────────────────────
print(f"{FMT_C}[INIT] Seedando KB base...{RST}")
r = ask("/kb seed")
print(f"  → {r[:150]}\n")
time.sleep(1)

# ── Lote 1: Ensino direto ──────────────────────────────────────────────────
total_e = len(ENSINOS)
ok_e = 0
print(f"{FMT_Y}{'─'*60}")
print(f"  LOTE 1 — ENSINO DIRETO: {total_e} tópicos")
print(f"{'─'*60}{RST}")

for i, ensino in enumerate(ENSINOS, 1):
    if datetime.now() >= DEADLINE:
        print(f"{FMT_R}[DEADLINE] Chegou às 23h. Encerrando.{RST}")
        break
    topico = ensino.split(":", 1)[1][:50] if ":" in ensino else ensino[:50]
    print(f"{FMT_Y}[E{i}/{total_e}]{RST} {topico}...", end=" ", flush=True)
    resp = ask(ensino, timeout=60)
    if "ERRO" in resp or "❌" in resp:
        print(f"{FMT_R}FALHOU{RST}")
    else:
        ok_e += 1
        print(f"{FMT_G}OK{RST}")
    time.sleep(0.4)

print(f"\n{FMT_G}Ensino: {ok_e}/{total_e} tópicos salvos{RST}\n")
time.sleep(1)

# ── Lote 2: Perguntas de teste ─────────────────────────────────────────────
total_q = len(PERGUNTAS)
ok_q = 0
fail_q = []
print(f"{FMT_C}{'─'*60}")
print(f"  LOTE 2 — TESTES DE CONHECIMENTO: {total_q} perguntas")
print(f"{'─'*60}{RST}")

for i, (label, pergunta) in enumerate(PERGUNTAS, 1):
    if datetime.now() >= DEADLINE:
        print(f"{FMT_R}[DEADLINE] Chegou às 23h. Encerrando.{RST}")
        break
    print(f"\n{FMT_C}[Q{i}/{total_q}][{label}]{RST}")
    print(f"  → {pergunta[:80]}")
    resp = ask(pergunta, timeout=90)
    if "ERRO" in resp or "❌" in resp or len(resp) < 10:
        fail_q.append((label, pergunta))
        print(f"  {FMT_R}✗ FALHOU: {resp[:100]}{RST}")
    else:
        ok_q += 1
        # mostra preview da resposta
        lines = resp.strip().split('\n')
        for l in lines[:6]:
            print(f"  {l[:110]}")
        if len(lines) > 6:
            print(f"  {FMT_G}[...+{len(lines)-6} linhas]{RST}")
    time.sleep(0.6)

# ── Relatório final ────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  RESULTADO FINAL — {datetime.now().strftime('%H:%M')}")
print(f"{'='*60}")
print(f"  Ensino direto KB:  {FMT_G}{ok_e}/{total_e}{RST} tópicos")
print(f"  Perguntas corretas: {FMT_G}{ok_q}/{total_q}{RST}")
total_ok = ok_e + ok_q
total_all = total_e + total_q
pct = round(100 * total_ok / total_all)
print(f"  Taxa geral: {FMT_G}{pct}%{RST} ({total_ok}/{total_all})")
if fail_q:
    print(f"\n  {FMT_R}Perguntas com falha:{RST}")
    for label, _ in fail_q:
        print(f"    - {label}")

# Status final do KB
print(f"\n{FMT_C}[KB FINAL]{RST}")
print(ask("/kb status"))

"""Cérebro compartilhado: servidor MCP com as notas numa pasta git (CEREBRO_RAIZ).

Uma pasta de notas em Markdown, versionada com git, que o Claude Code (e qualquer outra IA
com um token) lê e escreve na hora. Cada escrita vira um commit
com o autor, então nada se perde e dá para ver quem mudou o quê.

Cada IA tem o próprio token (tokens.json, só o hash), com permissão de leitura ou escrita.
Gestão pela linha de comando: tokens.py criar|listar|revogar.
"""
import difflib, fcntl, hashlib, json, os, re, subprocess, time, unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from alerta import alertar

AQUI = Path(__file__).resolve().parent
RAIZ = Path(os.environ.get("CEREBRO_RAIZ", "/root/cerebro")).resolve()
TOKENS = Path(os.environ.get("CEREBRO_TOKENS", str(AQUI / "tokens.json")))
DONO = os.environ.get("CEREBRO_DONO", "").strip() or "dono"
PORTA = int(os.environ.get("CEREBRO_PORTA", "8765"))
BRT = timezone(timedelta(hours=float(os.environ.get("CEREBRO_FUSO", "-3"))))   # fuso das datas (padrão: Brasília)
TRAVA = RAIZ / ".git" / "cerebro.lock"
# Cada uso vira uma linha aqui (quem, ação, notas). A página /ver lê ao vivo para animar o cérebro.
# Não guarda conteúdo de nota, só caminhos e o texto buscado.
ATIVIDADE = Path(os.environ.get("CEREBRO_ATIVIDADE", str(AQUI / "atividade.jsonl")))


def ler_tokens() -> dict:
    """{sha256 do token: {"nome", "permissao": "leitura"|"escrita", "criado", "ultimo_uso"}}"""
    try:
        return json.loads(TOKENS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def gravar_tokens(t: dict):
    tmp = TOKENS.with_suffix(".tmp")
    tmp.write_text(json.dumps(t, indent=1, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(TOKENS)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_uso_gravado = {}


def quem(authorization: str):
    """Dono do token do cabeçalho Authorization (dict com nome e permissão), ou None."""
    if not authorization.startswith("Bearer "):
        return None
    h = hash_token(authorization[7:].strip())
    tokens = ler_tokens()
    dono = tokens.get(h)
    if dono and time.time() - _uso_gravado.get(h, 0) > 3600:   # anota o último uso, no máximo 1x por hora
        _uso_gravado[h] = time.time()
        dono["ultimo_uso"] = datetime.now(BRT).strftime("%Y-%m-%d %H:%M")
        gravar_tokens(tokens)
    return dono


def _quem_chama(ctx: Context) -> dict:
    req = ctx.request_context.request
    dono = quem(req.headers.get("authorization", "")) if req is not None else None
    if not dono:
        raise PermissionError("token não reconhecido")
    return dono


def _atividade(ctx: Context, acao: str, alvos=(), detalhe: str = ""):
    """Anota o uso para a visualização ao vivo. Nunca derruba a ferramenta se der erro."""
    try:
        dono = _quem_chama(ctx)
        linha = json.dumps({"t": time.time(), "quem": dono["nome"], "acao": acao,
                            "alvos": [str(a) for a in list(alvos)[:24]], "detalhe": detalhe[:120]}, ensure_ascii=False)
        with open(ATIVIDADE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
        if ATIVIDADE.stat().st_size > 2_000_000:   # guarda só as 2000 últimas
            linhas = ATIVIDADE.read_text(encoding="utf-8").splitlines()[-2000:]
            ATIVIDADE.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    except Exception:
        pass


def _autor_de_escrita(ctx: Context, autor: str) -> str:
    """Só token de escrita grava. O autor sempre leva o nome do dono do token, para uma IA não assinar como outra."""
    dono = _quem_chama(ctx)
    if dono["permissao"] != "escrita":
        raise PermissionError(f"o token '{dono['nome']}' é só de leitura: não pode escrever no cérebro")
    autor = (autor or "").strip() or dono["nome"]
    return autor if dono["nome"].lower() in autor.lower() else f"{autor} (via {dono['nome']})"

INSTRUCOES = f"""Cérebro compartilhado de {DONO}.
É a memória COMUM das IAs que trabalham para {DONO} (o Claude Code e qualquer outra que ganhar um token).
Cada uma continua com a sua memória própria; aqui fica o que todas precisam saber, e como as coisas são feitas.
Manter o cérebro em dia faz parte de TODO trabalho: consulte no começo e registre ao concluir, sem esperar pedido."""
INSTRUCOES += """

Quando usar:
- No começo de um assunto de trabalho: `recentes` (o que mudou nos últimos dias) e `buscar` pelo projeto/tema.
- Ao terminar algo relevante (entrega, configuração, decisão, método novo): `registrar_diario`.
- Quando um jeito de fazer se firmar: escreva um guia replicável em guias/ (ver `como_usar`).
Regras: nada de senha, token, chave, IP de servidor ou dado pessoal de cliente. Notas em português.
ORGANIZAÇÃO (o servidor cobra): antes de escrever, `buscar` o assunto e `ler` a nota; ajuste a nota que já existe
(reescreva o trecho, junte, tire o que ficou velho) em vez de só acrescentar no fim. Só crie nota nova se não houver
uma sobre o assunto. No diário, um assunto por dia: se já tem entrada de hoje sobre ele, use `complementar_diario`.
Leia `como_usar` na primeira vez."""

mcp = FastMCP("cerebro", instructions=INSTRUCOES, host="127.0.0.1", port=PORTA, stateless_http=True)


def _caminho(rel: str, precisa_existir: bool = False) -> Path:
    rel = (rel or "").strip().lstrip("/")
    p = (RAIZ / rel).resolve()
    if RAIZ not in p.parents and p != RAIZ:
        raise ValueError("caminho fora do cérebro")
    if any(part.startswith(".") for part in p.relative_to(RAIZ).parts):
        raise ValueError("caminho inválido")
    if p != RAIZ and p.suffix and p.suffix != ".md":
        raise ValueError("só arquivos .md")
    if precisa_existir and not p.exists():
        raise ValueError(f"não existe: {rel}")
    return p


def _commit(msg: str):
    subprocess.run(["git", "-C", str(RAIZ), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(RAIZ), "commit", "-q", "-m", msg], capture_output=True)


def _gravar(p: Path, texto: str, modo: str, autor: str, acao: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(TRAVA, "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        with open(p, modo, encoding="utf-8") as f:
            f.write(texto)
        _commit(f"{autor}: {acao} {p.relative_to(RAIZ)}")


# ---------- Organização: ler antes de escrever, sem repetir ----------
# Notas geradas por script ou escritas só pelas ferramentas próprias não passam pelas travas.
LIVRES = ("anexos/", "geral/agentes-", "geral/pedidos-entre-ias.md")
PASTAS_CONTEUDO = ("guias/", "projetos/", "geral/")
LIMITE_NOTA = 40_000


def _normal(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


_VAZIAS = set("a o e de da do das dos em no na nos nas para por com um uma the of and ao aos as os que se".split())


def _parecido(a: str, b: str) -> float:
    """0 a 1: mistura de semelhança de texto e de palavras (sem as vazias)."""
    na, nb = _normal(a), _normal(b)
    pa, pb = set(na.split()) - _VAZIAS, set(nb.split()) - _VAZIAS
    jac = len(pa & pb) / len(pa | pb) if pa and pb else 0
    return max(difflib.SequenceMatcher(None, na, nb).ratio(), jac)


def _titulo_nota(texto: str, rel: str) -> str:
    m = re.search(r"^# (.+)$", texto, re.M)
    return m.group(1) if m else Path(rel).stem.replace("-", " ")


def _leu_depois(dono: str, rel: str, desde: float) -> bool:
    """True se o dono do token leu (ou buscou e achou) essa nota depois de `desde`."""
    try:
        linhas = ATIVIDADE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False
    for l in reversed(linhas):
        try:
            ev = json.loads(l)
        except ValueError:
            continue
        if ev.get("t", 0) < desde:
            return False
        if ev.get("quem") == dono and ev.get("acao") in ("ler", "escrever", "acrescentar", "criar") and rel in ev.get("alvos", []):
            return True
    return False


def _exigir_leitura(ctx: Context, p: Path):
    """Nota que já existe só muda depois de lida (depois da última mudança dela)."""
    rel = str(p.relative_to(RAIZ))
    if not p.exists() or rel.startswith(LIVRES):
        return
    dono = _quem_chama(ctx)["nome"]
    if not _leu_depois(dono, rel, p.stat().st_mtime - 1):
        raise PermissionError(
            f"Leia a nota antes de mexer nela: ler('{rel}'). Ela mudou desde a última vez que você a leu (ou você nunca leu). "
            "Depois ajuste o conteúdo existente (reescreva o trecho, junte o que for do mesmo assunto, tire o que ficou velho) "
            "em vez de só acrescentar no fim.")


def _barrar_repetida(p: Path, conteudo: str, confirmo: bool):
    """Nota nova em guias/projetos/geral: recusa se já existe uma parecida (aponta qual ajustar)."""
    rel = str(p.relative_to(RAIZ))
    if p.exists() or confirmo or not rel.startswith(PASTAS_CONTEUDO):
        return
    titulo = _titulo_nota(conteudo, rel)
    candidatos = []
    for q in (RAIZ / rel.split("/")[0]).glob("*.md"):
        qrel = str(q.relative_to(RAIZ))
        qtit = _titulo_nota(q.read_text(encoding="utf-8")[:2000], qrel)
        nota = max(_parecido(titulo, qtit), _parecido(p.stem, q.stem))
        if nota >= 0.55:
            candidatos.append((nota, qrel, qtit))
    if candidatos:
        lista = "; ".join(f"{c[1]} (\"{c[2][:70]}\")" for c in sorted(candidatos, reverse=True)[:4])
        raise ValueError(
            f"Já existe nota parecida: {lista}. Leia e ajuste a que já existe em vez de criar outra. "
            "Se for mesmo outro assunto, repita com nova_mesmo_assim=true.")


def _aviso_tamanho(texto: str) -> str:
    return (f" Aviso: a nota ficou com {len(texto) // 1000} mil caracteres; considere dividir em notas menores "
            "e ligar uma à outra.") if len(texto) > LIMITE_NOTA else ""


def _entradas_de_hoje(texto: str, dia: str):
    for parte in re.split(r"\n(?=## )", texto):
        cab = parte.split("\n", 1)[0]
        if cab.startswith(f"## {dia}"):
            yield cab, re.sub(r"^## [\d-]+(?: [\d:]+)?\s*[—:-]\s*", "", cab)


@mcp.tool()
def como_usar(ctx: Context) -> str:
    """Regras do cérebro, estrutura das pastas e o modelo de nota replicável. Leia na primeira vez."""
    _atividade(ctx, "como_usar", ["README.md"])
    return (RAIZ / "README.md").read_text(encoding="utf-8")


@mcp.tool()
def listar(ctx: Context, pasta: str = "") -> str:
    """Lista as notas (.md) de uma pasta do cérebro (vazio = tudo), com data da última mudança."""
    base = _caminho(pasta, precisa_existir=True)
    _atividade(ctx, "listar", [], pasta.strip("/") or "tudo")
    linhas = []
    for p in sorted(base.rglob("*.md")):
        if any(part.startswith(".") for part in p.relative_to(RAIZ).parts):
            continue
        dt = datetime.fromtimestamp(p.stat().st_mtime, BRT).strftime("%d/%m %H:%M")
        linhas.append(f"{p.relative_to(RAIZ)}  ({dt}, {p.stat().st_size // 1024 or 1} KB)")
    return "\n".join(linhas) or "(vazio)"


@mcp.tool()
def buscar(texto: str, ctx: Context, pasta: str = "") -> str:
    """Procura um texto (sem diferenciar maiúsculas) nas notas. Devolve arquivo:linha: trecho (até 60)."""
    base = _caminho(pasta, precisa_existir=True)
    r = subprocess.run(["grep", "-rniI", "--include=*.md", "--exclude-dir=.git", "-m", "8", "--", texto, str(base)],
                       capture_output=True, text=True)
    saida = [l.replace(str(RAIZ) + "/", "")[:300] for l in r.stdout.splitlines()]
    achados = list(dict.fromkeys(l.split(":", 1)[0] for l in saida))
    _atividade(ctx, "buscar", achados, texto)
    return "\n".join(saida[:60]) or "nada encontrado"


@mcp.tool()
def ler(caminho: str, ctx: Context) -> str:
    """Lê uma nota inteira. Ex.: 'projetos/meu-projeto.md'."""
    p = _caminho(caminho, precisa_existir=True)
    _atividade(ctx, "ler", [p.relative_to(RAIZ)])
    return p.read_text(encoding="utf-8")


@mcp.tool()
def escrever(caminho: str, conteudo: str, autor: str, ctx: Context, nova_mesmo_assim: bool = False) -> str:
    """Cria uma nota ou SUBSTITUI a nota inteira. Nota que já existe: o servidor exige que você a tenha lido
    (ler) depois da última mudança dela; reescreva ajustando o que já existe. Nota nova: se já houver uma
    parecida, é recusada (nova_mesmo_assim=true só se for outro assunto). autor: 'claude-code' etc."""
    autor = _autor_de_escrita(ctx, autor)
    p = _caminho(caminho)
    novo = not p.exists()
    _exigir_leitura(ctx, p)
    _barrar_repetida(p, conteudo, nova_mesmo_assim)
    _gravar(p, conteudo if conteudo.endswith("\n") else conteudo + "\n", "w", autor, "escreveu")
    _atividade(ctx, "criar" if novo else "escrever", [p.relative_to(RAIZ)])
    return f"ok: {p.relative_to(RAIZ)}" + _aviso_tamanho(conteudo)


@mcp.tool()
def acrescentar(caminho: str, conteudo: str, autor: str, ctx: Context, nova_mesmo_assim: bool = False) -> str:
    """Acrescenta texto no fim de uma nota (cria se não existir). Só para lista que cresce (fila, registro);
    para guia ou nota de projeto, prefira ler e reescrever com escrever, encaixando a informação no lugar certo.
    Nota que já existe precisa ter sido lida depois da última mudança."""
    autor = _autor_de_escrita(ctx, autor)
    p = _caminho(caminho)
    novo = not p.exists()
    _exigir_leitura(ctx, p)
    _barrar_repetida(p, conteudo, nova_mesmo_assim)
    _gravar(p, "\n" + conteudo.strip() + "\n", "a", autor, "acrescentou em")
    _atividade(ctx, "criar" if novo else "acrescentar", [p.relative_to(RAIZ)])
    return f"ok: {p.relative_to(RAIZ)}"


@mcp.tool()
def registrar_diario(autor: str, titulo: str, pedido: str, feito: str, status: str, ctx: Context,
                     padrao_novo: str = "", mesmo_assim: bool = False) -> str:
    """Registra no diário compartilhado algo que foi concluído. status: '✅ ...', '🔸 ...' ou '⚪ ...'.
    padrao_novo: um jeito de fazer que deve ser repetido (opcional). Um assunto por dia: se já existe entrada de
    hoje sobre o mesmo assunto, é recusado; use complementar_diario nela (mesmo_assim=true só se for outro assunto)."""
    autor = _autor_de_escrita(ctx, autor)
    agora = datetime.now(BRT)
    p = RAIZ / "diario" / f"{agora:%Y-%m}.md"
    if p.exists() and not mesmo_assim:
        parecidas = [t for _, t in _entradas_de_hoje(p.read_text(encoding="utf-8"), f"{agora:%Y-%m-%d}")
                     if _parecido(titulo, re.sub(r"\s*\([^)]*\)\s*$", "", t)) >= 0.5]
        if parecidas:
            raise ValueError(
                f"Já existe entrada de hoje sobre esse assunto: \"{parecidas[0]}\". Não crie outra: use "
                "complementar_diario(titulo_existente, ...) para acrescentar o andamento nela. "
                "Se for outro assunto, repita com mesmo_assim=true.")
    entrada = (f"\n## {agora:%Y-%m-%d %H:%M} — {titulo.strip()} ({autor})\n- Pedido: {pedido.strip()}\n"
               f"- Feito: {feito.strip()}\n- Status: {status.strip()}\n")
    if padrao_novo.strip():
        entrada += f"- Padrão novo: {padrao_novo.strip()}\n"
    _gravar(p, entrada, "a", autor, "registrou no diário")
    _atividade(ctx, "registrar_diario", [p.relative_to(RAIZ)], titulo.strip())
    return f"ok: diario/{p.name}"


@mcp.tool()
def complementar_diario(titulo_existente: str, texto: str, ctx: Context, status: str = "") -> str:
    """Acrescenta o andamento numa entrada do diário de HOJE que já existe (mesmo assunto), em vez de criar outra.
    titulo_existente: parte do título da entrada. texto: o que mudou (1 a 3 frases). status: novo status, se mudou."""
    autor = _autor_de_escrita(ctx, "")
    agora = datetime.now(BRT)
    p = RAIZ / "diario" / f"{agora:%Y-%m}.md"
    texto_d = p.read_text(encoding="utf-8") if p.exists() else ""
    partes = re.split(r"\n(?=## )", texto_d)
    melhor, nota = None, 0.0
    for i, parte in enumerate(partes):
        cab = parte.split("\n", 1)[0]
        if cab.startswith(f"## {agora:%Y-%m-%d}"):
            n = max(_parecido(titulo_existente, cab), 1.0 if _normal(titulo_existente) in _normal(cab) else 0)
            if n > nota:
                melhor, nota = i, n
    if melhor is None or nota < 0.4:
        raise ValueError("Não achei entrada de hoje com esse título. Veja as de hoje com recentes() ou use registrar_diario.")
    dono = _quem_chama(ctx)["nome"]
    linha = f"- ({agora:%H:%M}, {dono}) {texto.strip()}"
    if status.strip():
        linha += f" Status agora: {status.strip()}"
    partes[melhor] = partes[melhor].rstrip("\n") + "\n" + linha + "\n"
    with open(TRAVA, "w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        atual = p.read_text(encoding="utf-8")
        if atual != texto_d:
            raise RuntimeError("o diário mudou enquanto eu escrevia; tente de novo")
        p.write_text("\n".join(partes), encoding="utf-8")
        _commit(f"{autor}: complementou o diário {p.relative_to(RAIZ)}")
    _atividade(ctx, "complementar_diario", [p.relative_to(RAIZ)], partes[melhor].split("\n", 1)[0][3:90])
    return f"ok: complementei \"{partes[melhor].split(chr(10), 1)[0][3:120]}\""


@mcp.tool()
def recentes(ctx: Context, dias: int = 7) -> str:
    """O que mudou no cérebro nos últimos N dias (quem mudou o quê) + as últimas entradas do diário."""
    r = subprocess.run(["git", "-C", str(RAIZ), "log", f"--since={int(dias)} days ago", "--date=format:%d/%m %H:%M",
                        "--pretty=format:%ad  %s"], capture_output=True, text=True)
    mudancas = r.stdout.strip() or "(nenhuma mudança)"
    diarios = sorted((RAIZ / "diario").glob("*.md"))
    ultimas = ""
    if diarios:
        partes = re.split(r"\n(?=## )", diarios[-1].read_text(encoding="utf-8"))
        ultimas = "\n".join(partes[-8:])
    _atividade(ctx, "recentes", [diarios[-1].relative_to(RAIZ)] if diarios else [])
    return f"MUDANÇAS ({dias} dias):\n{mudancas}\n\nÚLTIMAS ENTRADAS DO DIÁRIO:\n{ultimas}"


# ---------- Agentes de cada IA e pedidos entre elas ----------
# Cada IA publica o próprio catálogo em geral/agentes-<ia>.md (gerado por script, com um bloco JSON escondido
# num comentário <!-- catalogo-json ... -->). Os pedidos ficam em geral/pedidos-entre-ias.md.
PEDIDOS = "geral/pedidos-entre-ias.md"
_CAB_PEDIDO = re.compile(r"^## (P-[\w-]+) · de (\S+) para (\S+) · agente (.+?) · tipo (\w+)\s*$", re.M)
_CAB_RESPOSTA = re.compile(r"^### R (P-[\w-]+) · (\w+) · por (\S+) · (.+?)\s*$", re.M)
STATUS_RESPOSTA = ("aceito", "em_andamento", "feito", "recusado")


def catalogos() -> dict:
    """{ia: catálogo} lido dos geral/agentes-*.md."""
    saida = {}
    for p in sorted((RAIZ / "geral").glob("agentes-*.md")):
        m = re.search(r"<!-- catalogo-json\s*(\{.*?\})\s*-->", p.read_text(encoding="utf-8"), re.S)
        if m:
            try:
                c = json.loads(m.group(1))
                saida[c.get("ia") or p.stem.replace("agentes-", "")] = c
            except ValueError:
                pass
    return saida


def ler_pedidos() -> list:
    p = RAIZ / PEDIDOS
    if not p.exists():
        return []
    texto = p.read_text(encoding="utf-8")
    pedidos = {}
    for m in _CAB_PEDIDO.finditer(texto):
        corpo = texto[m.end():].split("\n## ", 1)[0].split("\n### ", 1)[0].strip()
        pedidos[m.group(1)] = {"id": m.group(1), "de": m.group(2), "para": m.group(3), "agente": m.group(4),
                               "tipo": m.group(5), "texto": corpo, "status": "aberto", "respostas": []}
    for m in _CAB_RESPOSTA.finditer(texto):
        corpo = re.split(r"\n#{2,3} ", texto[m.end():], 1)[0].strip()
        if m.group(1) in pedidos:
            pedidos[m.group(1)]["respostas"].append({"status": m.group(2), "por": m.group(3), "quando": m.group(4), "texto": corpo})
            pedidos[m.group(1)]["status"] = m.group(2)
    return list(pedidos.values())


def _resumo_pedido(p: dict) -> str:
    linha = f"{p['id']} · de {p['de']} para {p['para']} · agente {p['agente']} · {p['tipo']} · {p['status']}\n  {p['texto'][:400]}"
    for r in p["respostas"][-2:]:
        linha += f"\n  → {r['status']} por {r['por']} ({r['quando']}): {r['texto'][:300]}"
    return linha


@mcp.tool()
def agentes(ctx: Context, ia: str = "") -> str:
    """Catálogo de agentes de cada IA (Claude Code e outras): nome, função, modelo e onde está a definição.
    Use para saber se a outra IA já tem um agente que serve para a sua tarefa. ia vazio = todas."""
    cats = catalogos()
    _atividade(ctx, "agentes", [f"geral/agentes-{k}.md" for k in cats if not ia or k == ia], ia or "todas")
    if not cats:
        return "nenhum catálogo publicado ainda"
    partes = []
    for nome, c in cats.items():
        if ia and nome != ia:
            continue
        partes.append(f"# {c.get('nome', nome)} (atualizado {c.get('atualizado', '?')}) · " +
                      ", ".join(f"{g['nome']}: {len(g['itens'])}" for g in c.get("grupos", [])))
        for g in c.get("grupos", []):
            if g.get("so_contagem"):
                continue
            partes.append(f"## {g['nome']}")
            for it in g["itens"]:
                partes.append(f"- {it['id']}: {it.get('funcao', '')[:160]}" + (f" [{it['modelo']}]" if it.get("modelo") else "") +
                              (f" (definição: {it['definicao']})" if it.get("definicao") else ""))
    return "\n".join(partes) + "\n\nPara usar um agente da outra IA: pedir_agente(para, agente, pedido, tipo='usar'|'copiar')."


@mcp.tool()
def pedir_agente(para: str, agente: str, pedido: str, ctx: Context, tipo: str = "usar") -> str:
    """Pede para a outra IA usar um agente dela numa tarefa sua (tipo 'usar') ou autorizar você a ter uma cópia
    adaptada dele (tipo 'copiar'). para: nome do token da outra IA (ex.: 'claude-code'). A outra IA vê o pedido sozinha e responde."""
    _autor_de_escrita(ctx, "")          # só token de escrita pode pedir
    de = _quem_chama(ctx)["nome"]
    para, tipo = para.strip().lower(), tipo.strip().lower()
    if tipo not in ("usar", "copiar"):
        raise ValueError("tipo deve ser 'usar' ou 'copiar'")
    if para == de:
        raise ValueError("o pedido é para a outra IA, não para você mesma")
    agora = datetime.now(BRT)
    pid = f"P-{agora:%Y%m%d-%H%M%S}-{de[:4]}"
    texto = (f"\n## {pid} · de {de} para {para} · agente {agente.strip()} · tipo {tipo}\n"
             f"- Quando: {agora:%d/%m/%Y %H:%M}\n- Pedido: {pedido.strip()}\n")
    p = RAIZ / PEDIDOS
    if not p.exists():
        texto = ("# Pedidos entre as IAs\n\nUma IA pede para a outra usar um agente dela (ou copiar). Escreva só pelas "
                 "ferramentas pedir_agente e responder_pedido do MCP, para o formato não quebrar.\n" + texto)
    _gravar(p, texto, "a", de, "pediu agente em")
    _atividade(ctx, "pedir", [f"geral/agentes-{para}.md", PEDIDOS], f"{agente} ({para})")
    return f"ok: pedido {pid} registrado para {para}. Acompanhe com pedidos()."


@mcp.tool()
def pedidos(ctx: Context, para: str = "", abertos: bool = True) -> str:
    """Lista os pedidos de agente entre as IAs. para: filtra quem deve atender (ex.: 'claude-code'). abertos=True mostra
    só os que ainda não foram 'feito' nem 'recusado'."""
    lista = [p for p in ler_pedidos() if (not para or p["para"] == para.lower())
             and (not abertos or p["status"] not in ("feito", "recusado"))]
    _atividade(ctx, "pedidos", [PEDIDOS], para or "todos")
    return "\n".join(_resumo_pedido(p) for p in lista) or "nenhum pedido" + (" aberto" if abertos else "")


@mcp.tool()
def responder_pedido(id: str, status: str, resposta: str, ctx: Context) -> str:
    """Responde um pedido de agente. status: 'aceito', 'em_andamento', 'feito' ou 'recusado'.
    Em 'feito', diga onde está o resultado; em 'recusado', o motivo."""
    por = _quem_chama(ctx)["nome"]
    _autor_de_escrita(ctx, por)
    status = status.strip().lower().replace(" ", "_")
    if status not in STATUS_RESPOSTA:
        raise ValueError(f"status deve ser um de {STATUS_RESPOSTA}")
    if not any(p["id"] == id for p in ler_pedidos()):
        raise ValueError(f"pedido não encontrado: {id}")
    agora = datetime.now(BRT)
    _gravar(RAIZ / PEDIDOS, f"\n### R {id} · {status} · por {por} · {agora:%d/%m/%Y %H:%M}\n{resposta.strip()}\n",
            "a", por, f"respondeu {id} em")
    _atividade(ctx, "responder", [PEDIDOS], f"{id} {status}")
    return f"ok: {id} marcado como {status}"


class Autenticacao(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        aut = request.headers.get("authorization", "")
        if not quem(aut):
            if aut.startswith("Bearer "):   # alguém tem um token, mas ele é inválido ou foi revogado
                ip = request.headers.get("x-forwarded-for", "?").split(",")[0].strip()
                alertar(f"token-invalido-{ip}", f"alguém tentou usar o cérebro (MCP) com um token inválido ou revogado, "
                        f"do IP {ip}. O acesso foi negado. Se não foi uma IA sua com token antigo, me avise.")
            return JSONResponse({"erro": "não autorizado"}, status_code=401)
        return await call_next(request)


if __name__ == "__main__":
    app = mcp.streamable_http_app()
    app.add_middleware(Autenticacao)
    uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")

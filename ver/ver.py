"""Visualização do cérebro compartilhado: rede de notas, busca e leitura.

Serve a página /ver e uma API só de leitura sobre a pasta de notas (CEREBRO_RAIZ), lida ao vivo a cada pedido.
Fica atrás do Caddy (HTTPS); escuta só em 127.0.0.1:8766. O login é próprio: tela /ver/entrar,
sessão em cookie assinado (180 dias) e troca de senha pela página. Criar usuário ou senha esquecida:
    venv/bin/python ver.py --definir-senha <usuario>
"""
import base64, getpass, hashlib, hmac, json, os, re, secrets, subprocess, sys, time, unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn

sys.path.insert(0, os.environ.get("CEREBRO_MCP_DIR", "/opt/cerebro-mcp"))
try:
    from alerta import alertar
except ImportError:   # rodando fora da VPS (teste local): sem avisos
    def alertar(*a, **k):
        pass
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

RAIZ = Path(os.environ.get("CEREBRO_RAIZ", "/root/cerebro")).resolve()
AQUI = Path(__file__).parent
BRT = timezone(timedelta(hours=float(os.environ.get("CEREBRO_FUSO", "-3"))))
DONO = os.environ.get("CEREBRO_DONO", "").strip()
PORTA = int(os.environ.get("CEREBRO_PORTA_VER", "8766"))

# Grupo (cor) de cada nota. Além destes fixos, cada categoria do índice do README (*Categoria*) vira um grupo.
GRUPOS = {"guias": "Guias", "projetos": "Projetos", "geral": "Geral", "diario": "Diário",
          "filas": "Filas de trabalho", "anexos": "Anexos"}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _notas():
    for p in sorted(RAIZ.rglob("*.md")):
        rel = p.relative_to(RAIZ)
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield str(rel), p


def _indice_readme(texto: str):
    """Do índice do README: caminho do guia -> (categoria, descrição)."""
    cat, saida = None, {}
    for linha in texto.splitlines():
        m = re.match(r"^\*([^*]+)\*\s*$", linha.strip())
        if m:
            cat = m.group(1).strip()
            continue
        m = re.match(r"^- `([^`]+\.md)`:\s*(.+)$", linha.strip())
        if m and cat:
            saida[m.group(1)] = (cat, m.group(2).strip())
    return saida


def _chave_cat(nome: str) -> str:
    return "cat-" + (re.sub(r"[^a-z0-9]+", "-", _sem_acento(nome)).strip("-") or "x")


def _grupos(cats: dict) -> dict:
    """Grupos das categorias do índice do README (na ordem em que aparecem) + os fixos."""
    g = {}
    for cat, _ in cats.values():
        g.setdefault(_chave_cat(cat), cat)
    g.update(GRUPOS)
    return g


def _grupo(rel: str, cats: dict) -> str:
    topo = rel.split("/")[0]
    if rel in cats:
        return _chave_cat(cats[rel][0])
    if topo.startswith("fila-"):
        return "filas"
    if topo in GRUPOS:
        return topo
    return "geral"


def _titulo(texto: str, rel: str) -> str:
    for linha in texto.splitlines():
        if linha.startswith("# "):
            return linha[2:].strip()
    return Path(rel).stem.replace("-", " ")


def _carregar():
    notas = {}
    for rel, p in _notas():
        try:
            texto = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        notas[rel] = {"texto": texto, "mtime": p.stat().st_mtime}
    return notas


def _grafo():
    notas = _carregar()
    cats = _indice_readme(notas.get("README.md", {}).get("texto", ""))
    nos, ligacoes, vistos = [], [], set()

    def ligar(a, b, tipo):
        chave = tuple(sorted((a, b)))
        if a != b and chave not in vistos:
            vistos.add(chave)
            ligacoes.append({"source": a, "target": b, "tipo": tipo})

    # Hubs: o centro, um por grupo, e um por pasta dos anexos.
    grupos = _grupos(cats)
    nos.append({"id": "#cerebro", "titulo": "Cérebro", "grupo": "centro", "hub": True})
    for k, nome in grupos.items():
        nos.append({"id": f"#{k}", "titulo": nome, "grupo": k, "hub": True})
        ligar("#cerebro", f"#{k}", "hub")

    # Padrões para achar citações: caminho completo, [[caminho]] ou nome do arquivo com hífen.
    alvos = []
    for rel in notas:
        stem = rel[:-3]
        nomes = {re.escape(rel), re.escape(stem)}
        base = Path(rel).stem
        if rel.startswith(("guias/", "projetos/", "geral/")):
            nomes.add(re.escape(Path(rel).name))
            if "-" in base:
                nomes.add(re.escape(base))
        alvos.append((rel, re.compile(r"(?<![\w/.-])(?:" + "|".join(sorted(nomes, key=len, reverse=True)) + r")(?![\w-])")))

    for rel, n in notas.items():
        texto = n["texto"]
        grupo = _grupo(rel, cats)
        desc = cats.get(rel, (None, ""))[1]
        if not desc:
            for linha in texto.splitlines():
                l = linha.strip()
                if l and not l.startswith(("#", "```", "|", "---")):
                    desc = re.sub(r"[*`_]", "", l)[:180]
                    break
        nos.append({"id": rel, "titulo": _titulo(texto, rel), "grupo": grupo, "desc": desc,
                    "kb": max(1, len(texto.encode()) // 1024),
                    "mudou": datetime.fromtimestamp(n["mtime"], BRT).strftime("%d/%m/%Y %H:%M")})
        if rel == "README.md":
            ligar("#cerebro", rel, "hub")
        elif rel.startswith("anexos/"):
            pasta = str(Path(rel).parent)
            partes = pasta.split("/")
            # anexos/<ia>/skills/<skill>/... vira um hub por skill; o resto, por pasta.
            hub_dir = "/".join(partes[:4]) if len(partes) >= 4 and partes[2] in ("skills", "skills-proprias") else pasta
            hid = f"#dir:{hub_dir}"
            if hid not in {x["id"] for x in nos}:
                nos.append({"id": hid, "titulo": hub_dir.split("/")[-1], "grupo": "anexos", "hub": True, "sub": True})
                ligar("#anexos", hid, "hub")
            ligar(hid, rel, "pasta")
        else:
            ligar(f"#{grupo}", rel, "grupo")

    for rel, n in notas.items():
        if rel.startswith("anexos/") or rel == "README.md":
            continue  # anexos citam por acaso e o README é o índice (já liga tudo pelo centro)
        for alvo, padrao in alvos:
            if alvo != rel and padrao.search(n["texto"]):
                ligar(rel, alvo, "cita")

    return {"nos": nos, "ligacoes": ligacoes, "grupos": grupos}


def _buscar(q: str):
    termos = [t for t in _sem_acento(q).split() if len(t) > 1]
    if not termos:
        return []
    notas = _carregar()
    resultados = []
    for rel, n in notas.items():
        texto = n["texto"]
        norm = _sem_acento(texto)
        titulo = _sem_acento(_titulo(texto, rel))
        caminho = _sem_acento(rel)
        if not all(t in norm or t in caminho for t in termos):
            continue
        pontos = 0
        for t in termos:
            pontos += 30 * (t in titulo) + 15 * (t in caminho) + min(norm.count(t), 20)
        if rel.startswith("guias/"):
            pontos *= 1.4  # quem procura quer "como fazer": guia primeiro
        elif rel.startswith("anexos/"):
            pontos *= 0.5
        linhas = texto.splitlines()
        trechos = []
        for i, linha in enumerate(linhas):
            if any(t in _sem_acento(linha) for t in termos):
                trechos.append({"linha": i + 1, "texto": linha.strip()[:220]})
                if len(trechos) == 3:
                    break
        resultados.append({"id": rel, "titulo": _titulo(texto, rel), "pontos": round(pontos, 1), "trechos": trechos})
    resultados.sort(key=lambda r: -r["pontos"])
    return resultados[:40]


# Mesma política do Caddy, repetida aqui para valer mesmo se alguém acessar sem passar por ele.
CABECALHOS_HTML = {
    "Cache-Control": "no-cache", "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                                "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'self'; object-src 'none'"),
}

# ---------- Login ----------
USUARIOS = AQUI / "usuarios.json"      # {"<usuario>": {"hash": "scrypt$...", "versao": 1}}  (permissão 600)
SEGREDO_ARQ = AQUI / "segredo.key"      # chave que assina os cookies (permissão 600)
COOKIE = "cerebro_sessao"
VALIDADE = 180 * 24 * 3600
_falhas = {}                            # ip -> instantes das tentativas erradas


def _ler_usuarios() -> dict:
    try:
        return json.loads(USUARIOS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _gravar_usuarios(u: dict):
    tmp = USUARIOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(u, indent=1, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(USUARIOS)


def _segredo() -> bytes:
    if not SEGREDO_ARQ.exists():
        SEGREDO_ARQ.write_bytes(secrets.token_bytes(32))
        os.chmod(SEGREDO_ARQ, 0o600)
    return SEGREDO_ARQ.read_bytes()


def _hash(senha: str, sal: bytes = None) -> str:
    sal = sal or secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(sal).decode() + "$" + base64.b64encode(h).decode()


def _confere(senha: str, guardado: str) -> bool:
    try:
        _, sal, _h = guardado.split("$")
        return hmac.compare_digest(_hash(senha, base64.b64decode(sal)), guardado)
    except ValueError:
        return False


def _definir_senha(usuario: str, senha: str) -> int:
    u = _ler_usuarios()
    # versão nova derruba as sessões antigas; usa o relógio para um usuário apagado e recriado não reviver sessões velhas
    versao = max(u.get(usuario, {}).get("versao", 0) + 1, int(time.time()))
    u[usuario] = {"hash": _hash(senha), "versao": versao}
    _gravar_usuarios(u)
    return versao


def _assinar(dados: str) -> str:
    return hmac.new(_segredo(), dados.encode(), hashlib.sha256).hexdigest()


def _cookie(usuario: str, versao: int) -> str:
    dados = f"{usuario}|{int(time.time()) + VALIDADE}|{versao}"
    return base64.urlsafe_b64encode(dados.encode()).decode() + "." + _assinar(dados)


def _sessao(request):
    """Usuário logado, ou None."""
    try:
        b64, assinatura = request.cookies.get(COOKIE, "").rsplit(".", 1)
        dados = base64.urlsafe_b64decode(b64.encode()).decode()
        if not hmac.compare_digest(_assinar(dados), assinatura):
            return None
        usuario, expira, versao = dados.split("|")
        if int(expira) < time.time() or _ler_usuarios().get(usuario, {}).get("versao") != int(versao):
            return None
        return usuario
    except Exception:
        return None


def _ip(request) -> str:
    return request.client.host if request.client else "?"


def _bloqueado(ip: str) -> bool:
    agora = time.time()
    for k in list(_falhas):
        _falhas[k] = [t for t in _falhas[k] if agora - t < 900]
        if not _falhas[k]:
            del _falhas[k]
    total = sum(len(v) for v in _falhas.values())
    return len(_falhas.get(ip, [])) >= 8 or total >= 40      # 8 erros por IP ou 40 no total em 15 min


def _com_cookie(resp, usuario: str, versao: int, request):
    seguro = request.url.scheme == "https"
    resp.set_cookie(COOKIE, _cookie(usuario, versao), max_age=VALIDADE, httponly=True, secure=seguro,
                    samesite="lax", path="/ver")
    return resp


def exige_login(funcao):
    async def envolta(request):
        if not _sessao(request):
            if request.url.path.startswith("/ver/api/"):
                return JSONResponse({"erro": "entre de novo"}, status_code=401)
            return RedirectResponse("/ver/entrar", status_code=303)
        return await funcao(request)
    return envolta


async def _json(request) -> dict:
    # Só aceita JSON: um formulário de outro site não consegue mandar isso sem permissão do navegador.
    if "application/json" not in request.headers.get("content-type", ""):
        return {}
    try:
        d = await request.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


async def tela_entrar(request):
    if _sessao(request):
        return RedirectResponse("/ver", status_code=303)
    return FileResponse(AQUI / "entrar.html", headers=CABECALHOS_HTML)


async def api_entrar(request):
    ip = _ip(request)
    if _bloqueado(ip):
        alertar(f"trava-{ip}", f"a página do cérebro bloqueou o IP {ip} por excesso de senhas erradas (15 min). "
                "Se não foi você, alguém está tentando adivinhar a senha.")
        return JSONResponse({"erro": "Muitas tentativas. Espere 15 minutos."}, status_code=429)
    d = await _json(request)
    usuario, senha = str(d.get("usuario", "")).strip().lower(), str(d.get("senha", ""))
    conta = _ler_usuarios().get(usuario)
    if not conta:
        _hash(senha)   # gasta o mesmo tempo de uma senha errada: não dá para descobrir quais usuários existem
    if not conta or not _confere(senha, conta["hash"]):
        _falhas.setdefault(ip, []).append(time.time())
        return JSONResponse({"erro": "Usuário ou senha errados."}, status_code=401)
    _falhas.pop(ip, None)
    ua = request.headers.get("user-agent", "")
    aparelho = ("iPhone" if "iPhone" in ua else "Android" if "Android" in ua else "Windows" if "Windows" in ua
                else "Mac" if "Mac OS" in ua else "outro aparelho")
    alertar(f"login-{usuario}-{ip}", f"'{usuario}' entrou na página do cérebro ({aparelho}, IP {ip}). "
            "Se não foi você, troque a senha e use 'Sair de todos os aparelhos'.", intervalo=600)
    return _com_cookie(JSONResponse({"ok": True}), usuario, conta["versao"], request)


async def api_sair(request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/ver")
    return resp


@exige_login
async def api_sair_todos(request):
    """Derruba as sessões de todos os aparelhos (inclusive este), sem trocar a senha."""
    usuario = _sessao(request)
    u = _ler_usuarios()
    u[usuario]["versao"] = max(u[usuario]["versao"] + 1, int(time.time()))
    _gravar_usuarios(u)
    alertar(f"sair-todos-{usuario}", f"'{usuario}' desconectou todos os aparelhos da página do cérebro.", intervalo=1)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/ver")
    return resp


@exige_login
async def api_eu(request):
    return JSONResponse({"usuario": _sessao(request)})


@exige_login
async def api_senha(request):
    usuario, ip = _sessao(request), _ip(request)
    if _bloqueado(ip):
        return JSONResponse({"erro": "Muitas tentativas. Espere 15 minutos."}, status_code=429)
    d = await _json(request)
    atual, nova = str(d.get("atual", "")), str(d.get("nova", ""))
    if not _confere(atual, _ler_usuarios()[usuario]["hash"]):
        _falhas.setdefault(ip, []).append(time.time())
        return JSONResponse({"erro": "A senha atual está errada."}, status_code=400)
    if len(nova) < 8:
        return JSONResponse({"erro": "A senha nova precisa de pelo menos 8 caracteres."}, status_code=400)
    versao = _definir_senha(usuario, nova)
    alertar(f"senha-{usuario}", f"a senha de '{usuario}' na página do cérebro foi trocada. Os outros aparelhos saíram.", intervalo=1)
    return _com_cookie(JSONResponse({"ok": True}), usuario, versao, request)


MANIFESTO = {"name": f"Cérebro de {DONO}" if DONO else "Cérebro", "short_name": "Cérebro", "start_url": "/ver", "scope": "/ver",
             "display": "standalone", "background_color": "#09060f", "theme_color": "#09060f",
             "icons": [{"src": "/ver/icone.svg", "sizes": "any", "type": "image/svg+xml"}]}
ICONE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><radialGradient id="g" cx="50%" cy="45%" r="60%">
<stop offset="0" stop-color="#9f7bff"/><stop offset=".55" stop-color="#5867ff"/><stop offset="1" stop-color="#ff6fc0"/></radialGradient></defs>
<rect width="64" height="64" rx="14" fill="#09060f"/><ellipse cx="32" cy="33" rx="22" ry="15" fill="url(#g)" opacity=".9"/>
<path d="M32 19v28" stroke="#09060f" stroke-width="2"/></svg>"""


async def manifesto(request):
    return JSONResponse(MANIFESTO, media_type="application/manifest+json")


async def icone(request):
    return Response(ICONE, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


@exige_login
async def pagina(request):
    return FileResponse(AQUI / "index.html", headers=CABECALHOS_HTML)


@exige_login
async def api_grafo(request):
    return JSONResponse(_grafo())


@exige_login
async def api_nota(request):
    rel = request.query_params.get("c", "").lstrip("/")
    p = (RAIZ / rel).resolve()
    if RAIZ not in p.parents or p.suffix != ".md" or not p.is_file() or \
            any(part.startswith(".") for part in p.relative_to(RAIZ).parts):
        return JSONResponse({"erro": "nota não encontrada"}, status_code=404)
    r = subprocess.run(["git", "-C", str(RAIZ), "log", "-1", "--date=format:%d/%m/%Y %H:%M",
                        "--pretty=format:%ad|%s", "--", rel], capture_output=True, text=True)
    quando, _, msg = r.stdout.partition("|")
    return JSONResponse({"id": rel, "texto": p.read_text(encoding="utf-8"),
                         "ultima": {"quando": quando, "msg": msg}})


@exige_login
async def api_buscar(request):
    return JSONResponse(_buscar(request.query_params.get("q", "")))


# ---------- Ao vivo: o que as IAs estão fazendo no cérebro ----------
ATIVIDADE = Path(os.environ.get("CEREBRO_ATIVIDADE", os.path.join(os.environ.get("CEREBRO_MCP_DIR", "/opt/cerebro-mcp"), "atividade.jsonl")))


def _ultimas_atividades(n: int) -> list:
    try:
        linhas = ATIVIDADE.read_text(encoding="utf-8").splitlines()[-n:]
    except FileNotFoundError:
        return []
    saida = []
    for l in linhas:
        try:
            saida.append(json.loads(l))
        except ValueError:
            pass
    return saida


def _quem_norm(autor: str) -> str:
    a = autor.lower()
    m = re.search(r"\(via ([\w-]+)\)", a)      # "x (via token)" conta para o dono do token
    if m:
        return m.group(1)
    if "claude" in a:
        return "claude-code"
    return re.sub(r"[^a-z0-9]+", "-", a).strip("-") or "?"


def _historico_git(dias: int) -> list:
    """Escritas registradas no git (existem desde o começo do cérebro)."""
    r = subprocess.run(["git", "-C", str(RAIZ), "log", f"--since={dias} days ago", "--name-only",
                        "--format=\x1e%at\x1f%s"], capture_output=True, text=True)
    saida = []
    for bloco in r.stdout.split("\x1e")[1:]:
        cab, _, arqs = bloco.partition("\n")
        try:
            t, assunto = cab.split("\x1f", 1)
        except ValueError:
            continue
        autor, _, resto = assunto.partition(": ")
        alvos = [a for a in arqs.split("\n") if a.endswith(".md")]
        if resto.startswith("escreveu"):
            acao = "escrever"
        elif resto.startswith("acrescentou em"):
            acao = "acrescentar"
        elif resto.startswith("registrou no diário"):
            acao = "registrar_diario"
        elif "cópia diária" in resto:
            acao = "copia"
        else:
            acao = "mudar"
        detalhe = autor if _quem_norm(autor) not in (autor.lower(),) else ""
        if acao in ("mudar", "copia"):
            detalhe = (resto[:120] + (f" · {autor}" if detalhe else "")).strip()
        saida.append({"t": int(t), "quem": _quem_norm(autor), "acao": acao, "alvos": alvos[:24],
                      "detalhe": detalhe, "n": len(alvos), "fonte": "git"})
    return saida


def _saude():
    """Problemas de manutenção das notas (sem contar anexos e diário)."""
    notas = _carregar()
    cats = _indice_readme(notas.get("README.md", {}).get("texto", ""))
    r = subprocess.run(["git", "-C", str(RAIZ), "log", "--name-only", "--format=\x1e%at"], capture_output=True, text=True)
    ultima = {}
    for bloco in r.stdout.split("\x1e")[1:]:
        t, _, arqs = bloco.partition("\n")
        for a in arqs.split("\n"):
            if a.endswith(".md") and a not in ultima:
                ultima[a] = int(t)          # o log vem do mais novo para o mais velho
    principais = [rel for rel in notas if rel.startswith(("guias/", "projetos/", "geral/"))]
    agora = time.time()
    ref = re.compile(r"(?<![\w/.-])((?:guias|projetos|geral)/[\w.-]+\.md)")
    quebradas, citadas = [], {}
    for rel, n in notas.items():
        if rel.startswith(("anexos/",)):
            continue
        for alvo in set(ref.findall(n["texto"])):
            if Path(alvo).stem.lower() in ("x", "y", "z", "nome", "exemplo", "tarefa", "projeto", "assunto"):
                continue   # nome de exemplo usado para explicar o formato, não citação de verdade
            if alvo not in notas:
                quebradas.append({"id": rel, "detalhe": f"cita {alvo}, que não existe"})
            elif alvo != rel and rel != "README.md":
                citadas.setdefault(alvo, set()).add(rel)
                citadas.setdefault(rel, set()).add(alvo)
    grafo = _grafo()   # ligações por nome do arquivo também contam
    for l in grafo["ligacoes"]:
        if l["tipo"] == "cita":
            citadas.setdefault(l["source"], set()).add(l["target"])
            citadas.setdefault(l["target"], set()).add(l["source"])

    def dias(rel):
        return int((agora - ultima.get(rel, notas[rel]["mtime"])) // 86400)

    paradas = sorted(({"id": rel, "detalhe": f"sem mudança há {dias(rel)} dias"} for rel in principais if dias(rel) >= 45),
                     key=lambda x: -int(x["detalhe"].split("há ")[1].split()[0]))
    fora_indice = [{"id": rel, "detalhe": "guia fora do índice do README (cai num grupo chutado)"}
                   for rel in principais if rel.startswith("guias/") and rel not in cats]
    sem_revisao = [{"id": rel, "detalhe": "guia sem a linha **Última revisão:**"}
                   for rel in principais if rel.startswith("guias/") and "Última revisão" not in notas[rel]["texto"]]
    isoladas = [{"id": rel, "detalhe": "nenhuma outra nota cita ou é citada por ela"}
                for rel in principais if not citadas.get(rel)]
    grupos = [
        {"chave": "quebradas", "titulo": "Citações quebradas", "dica": "Uma nota aponta para outra que não existe (renomeada ou apagada).", "itens": quebradas, "peso": 6},
        {"chave": "fora_indice", "titulo": "Guias fora do índice", "dica": "Faltam no índice do README, por isso ficam na região errada do cérebro.", "itens": fora_indice, "peso": 4},
        {"chave": "paradas", "titulo": "Notas paradas há 45+ dias", "dica": "Podem estar desatualizadas; vale conferir se ainda são verdade.", "itens": paradas, "peso": 2},
        {"chave": "sem_revisao", "titulo": "Guias sem data de revisão", "dica": "O modelo de guia pede a linha Última revisão.", "itens": sem_revisao, "peso": 1},
        {"chave": "isoladas", "titulo": "Notas isoladas", "dica": "Não citam nem são citadas por nenhuma outra; talvez falte ligar.", "itens": isoladas, "peso": 1},
    ]
    pontos = max(0, 100 - sum(min(len(g["itens"]) * g["peso"], 30) for g in grupos))
    return {"nota": pontos, "total": len(principais), "grupos": grupos}


def _agentes():
    """Catálogos de agentes de cada IA (bloco JSON das notas geral/agentes-*.md) e pedidos entre elas."""
    cats = []
    for p in sorted((RAIZ / "geral").glob("agentes-*.md")):
        m = re.search(r"<!-- catalogo-json\s*(\{.*?\})\s*-->", p.read_text(encoding="utf-8"), re.S)
        if m:
            try:
                c = json.loads(m.group(1))
                c["nota"] = str(p.relative_to(RAIZ))
                cats.append(c)
            except ValueError:
                pass
    pedidos = []
    arq = RAIZ / "geral" / "pedidos-entre-ias.md"
    if arq.exists():
        texto = arq.read_text(encoding="utf-8")
        cab = re.compile(r"^## (P-[\w-]+) · de (\S+) para (\S+) · agente (.+?) · tipo (\w+)\s*$", re.M)
        resp = re.compile(r"^### R (P-[\w-]+) · (\w+) · por (\S+) · (.+?)\s*$", re.M)
        status = {}
        for m in resp.finditer(texto):
            status[m.group(1)] = {"status": m.group(2), "por": m.group(3), "quando": m.group(4),
                                  "texto": re.split(r"\n#{2,3} ", texto[m.end():], 1)[0].strip()[:300]}
        for m in cab.finditer(texto):
            corpo = texto[m.end():].split("\n## ", 1)[0].split("\n### ", 1)[0]
            pm = re.search(r"- Pedido:\s*(.+)", corpo)
            qm = re.search(r"- Quando:\s*(.+)", corpo)
            r = status.get(m.group(1), {})
            pedidos.append({"id": m.group(1), "de": m.group(2), "para": m.group(3), "agente": m.group(4), "tipo": m.group(5),
                            "pedido": (pm.group(1) if pm else "")[:300], "quando": qm.group(1).strip() if qm else "",
                            "status": r.get("status", "aberto"), "resposta": r.get("texto", "")})
    cats.sort(key=lambda c: c.get("nome", ""))
    return {"ias": cats, "pedidos": pedidos[::-1][:30]}


@exige_login
async def api_agentes(request):
    return JSONResponse(_agentes())


@exige_login
async def api_saude(request):
    return JSONResponse(_saude())


@exige_login
async def api_historico(request):
    """Usos (desde que o ao vivo existe) + escritas do git de antes disso, do mais novo para o mais velho."""
    dias = max(1, min(int(request.query_params.get("dias", 30)), 365))
    usos = _ultimas_atividades(2000)
    inicio = usos[0]["t"] if usos else time.time()
    corte = time.time() - dias * 86400
    git = [e for e in _historico_git(dias) if e["t"] < inicio]
    tudo = [e for e in usos if e["t"] >= corte] + git
    tudo.sort(key=lambda e: -e["t"])
    return JSONResponse({"eventos": tudo[:3000], "usos_desde": inicio})


@exige_login
async def api_atividade(request):
    return JSONResponse(_ultimas_atividades(min(int(request.query_params.get("n", 30)), 200)))


@exige_login
async def api_ao_vivo(request):
    """Server-Sent Events: cada linha nova do arquivo de atividade vira um evento na hora."""
    import asyncio
    from starlette.responses import StreamingResponse

    async def fluxo():
        try:
            pos = ATIVIDADE.stat().st_size
        except FileNotFoundError:
            pos = 0
        yield "retry: 3000\n\n"
        ultimo_ping = time.time()
        while not await request.is_disconnected():
            try:
                tam = ATIVIDADE.stat().st_size
            except FileNotFoundError:
                tam = 0
            if tam < pos:          # o arquivo foi encurtado (rotação): recomeça do fim
                pos = tam
            if tam > pos:
                with open(ATIVIDADE, encoding="utf-8") as f:
                    f.seek(pos)
                    novo = f.read()
                    pos = f.tell()
                for l in novo.splitlines():
                    if l.strip():
                        yield f"data: {l}\n\n"
            if time.time() - ultimo_ping > 15:   # mantém a conexão aberta no celular e nos proxies
                ultimo_ping = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.4)

    return StreamingResponse(fluxo(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def saude(request):
    return PlainTextResponse("ok")


app = Starlette(routes=[
    Route("/ver", pagina), Route("/ver/", pagina),
    Route("/ver/entrar", tela_entrar), Route("/ver/api/entrar", api_entrar, methods=["POST"]),
    Route("/ver/api/sair", api_sair, methods=["POST"]), Route("/ver/api/eu", api_eu),
    Route("/ver/api/senha", api_senha, methods=["POST"]),
    Route("/ver/api/grafo", api_grafo), Route("/ver/api/nota", api_nota),
    Route("/ver/api/buscar", api_buscar), Route("/ver/saude", saude),
    Route("/ver/api/atividade", api_atividade), Route("/ver/api/ao-vivo", api_ao_vivo),
    Route("/ver/api/historico", api_historico), Route("/ver/api/saude-notas", api_saude), Route("/ver/api/agentes", api_agentes), Route("/ver/api/sair-todos", api_sair_todos, methods=["POST"]),
    Route("/ver/manifest.webmanifest", manifesto), Route("/ver/icone.svg", icone),
])

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--definir-senha":
        senha = getpass.getpass(f"Nova senha para {sys.argv[2]}: ")
        if len(senha) < 8 or senha != getpass.getpass("Repita: "):
            sys.exit("senha curta (mínimo 8) ou as duas não batem")
        _definir_senha(sys.argv[2].strip().lower(), senha)
        print("ok: senha definida; as sessões antigas desse usuário caíram")
    else:
        _segredo()
        # proxy_headers: o Caddy (127.0.0.1) informa o IP real e o https, usados na trava e no cookie seguro
        uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning", proxy_headers=True, forwarded_allow_ips="127.0.0.1")

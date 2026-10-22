"""Gancho SessionStart do Claude Code para o cérebro compartilhado.

1) Mostra (no contexto da conversa) os pedidos de agente que outra IA deixou para o Claude Code.
2) Em segundo plano, publica o catálogo de agentes do Claude Code no cérebro (geral/agentes-claude-code.md e
   as definições em anexos/claude-code/), só quando algo mudou.
Uso manual: python cerebro_inicio.py --publicar   (publica agora e mostra o resultado)
O endereço e o token vêm do servidor "cerebro" no ~/.claude.json (o mesmo que o `claude mcp add` gravou).
Nunca trava a conversa: qualquer erro é engolido.
"""
import hashlib, json, os, re, subprocess, sys, urllib.request
from datetime import datetime, timedelta, timezone

CASA = os.path.expanduser("~")
AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(AQUI, "estado-agentes.json")
BRT = timezone(timedelta(hours=-3))
SEGREDO = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|cbr_[A-Za-z0-9_-]{30,}|xox[bpa]-[\w-]{10,}|"
                     r"AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY)")


def _config():
    return json.load(open(os.path.join(CASA, ".claude.json"), encoding="utf-8"))["mcpServers"]["cerebro"]


def chamar(ferramenta, args, timeout=20):
    corpo = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": ferramenta, "arguments": args}}).encode()
    cfg = _config()
    req = urllib.request.Request(cfg["url"], corpo, {"Authorization": cfg["headers"]["Authorization"], "Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream"})
    bruto = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
    r = json.loads(next(l[6:] for l in bruto.splitlines() if l.startswith("data: ")) if "data: " in bruto else bruto)["result"]
    if r.get("isError"):
        raise RuntimeError(r["content"][0]["text"])
    return r["content"][0]["text"]


def frontmatter(texto):
    m = re.match(r"^---\s*\n(.*?)\n---", texto, re.S)
    campos = {}
    if not m:
        return campos
    linhas, chave = m.group(1).splitlines(), None
    for l in linhas:
        mm = re.match(r"^([\w-]+):\s*(.*)$", l)
        if mm:
            chave, valor = mm.group(1), mm.group(2).strip()
            campos[chave] = "" if valor in (">", "|", ">-", "|-") else valor.strip('"').strip("'")
        elif chave and l.startswith((" ", "\t")):
            campos[chave] = (campos[chave] + " " + l.strip()).strip()
    return campos


def curto(t, n=220):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def montar_catalogo():
    arquivos = {}       # caminho no cérebro -> conteúdo da definição
    agentes, squads, skills = [], [], []
    pasta = os.path.join(CASA, ".claude", "agents")
    for f in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        if not f.endswith(".md"):
            continue
        texto = open(os.path.join(pasta, f), encoding="utf-8").read()
        fm, nome = frontmatter(texto), f[:-3]
        destino = f"anexos/claude-code/agentes/{nome}.md"
        agentes.append({"id": nome, "nome": fm.get("name", nome), "funcao": curto(fm.get("description")),
                        "modelo": fm.get("model", ""), "definicao": destino})
        arquivos[destino] = texto
    pasta = os.path.join(CASA, ".claude", "skills")
    for d in sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []:
        sk = os.path.join(pasta, d, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        texto = open(sk, encoding="utf-8").read()
        fm = frontmatter(texto)
        desc = fm.get("description", "")
        if re.search(r"\bsquad\b", desc, re.I):
            destino = f"anexos/claude-code/squads/{d}.md"
            squads.append({"id": d, "nome": d.capitalize(), "funcao": curto(desc), "modelo": "vários", "definicao": destino})
            arquivos[destino] = texto
        else:
            skills.append({"id": d, "nome": d, "funcao": curto(desc, 160)})
    cat = {
        "ia": "claude-code", "nome": "Claude Code", "cor": "#ff9d6b",
        "lider": {"nome": "Claude Code", "funcao": "Assistente no computador (desktop e terminal). Orquestra subagentes e skills."},
        "contagem": {"agentes": len(agentes) + len(squads), "subagentes": len(agentes), "squads": len(squads),
                     "skills": len(skills)},
        "grupos": [
            {"nome": "Squads (vários agentes juntos)", "itens": squads},
            {"nome": "Subagentes", "itens": agentes},
            {"nome": "Skills (habilidades)", "itens": skills},
        ],
        "como_pedir": "Para usar um destes, a outra IA chama pedir_agente(para='claude-code', agente='<id>', pedido='...'). "
                      "O Claude Code vê o pedido ao abrir a próxima conversa e o usuário decide se atende.",
    }
    return cat, arquivos


def nota(cat):
    c = cat["contagem"]
    linhas = [f"# Agentes do {cat['nome']}", "",
              f"**{c['agentes']} agentes** ({c['subagentes']} subagentes + {c['squads']} squads) · {c['skills']} skills.",
              "", "Nota gerada automaticamente pelo Claude Code (gancho de início de conversa). Não edite à mão: muda na próxima publicação.",
              "Para usar um agente daqui, a outra IA usa a ferramenta `pedir_agente` do MCP (ver `geral/pedidos-entre-ias.md`).", ""]
    for g in cat["grupos"]:
        linhas += [f"## {g['nome']}", ""]
        for it in g["itens"]:
            extra = f" · modelo {it['modelo']}" if it.get("modelo") else ""
            defin = f" · definição: `{it['definicao']}`" if it.get("definicao") else ""
            linhas.append(f"- **{it['nome']}** (`{it['id']}`){extra}{defin}: {it.get('funcao', '')}")
        linhas.append("")
    linhas.append("<!-- catalogo-json\n" + json.dumps(cat, ensure_ascii=False) + "\n-->")
    return "\n".join(linhas) + "\n"


def publicar(verboso=False):
    cat, arquivos = montar_catalogo()
    try:
        estado = json.load(open(ESTADO, encoding="utf-8"))
    except Exception:
        estado = {}
    mudou = 0
    for destino, texto in arquivos.items():
        if SEGREDO.search(texto):
            if verboso:
                print("pulado (parece ter segredo):", destino)
            continue
        h = hashlib.sha256(texto.encode()).hexdigest()
        if estado.get(destino) != h:
            chamar("escrever", {"caminho": destino, "conteudo": texto, "autor": "claude-code"}, timeout=60)
            estado[destino] = h
            mudou += 1
    cat_sem_data = json.dumps(cat, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(cat_sem_data.encode()).hexdigest()
    if estado.get("catalogo") != h:
        cat["atualizado"] = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
        chamar("escrever", {"caminho": "geral/agentes-claude-code.md", "conteudo": nota(cat), "autor": "claude-code"}, timeout=60)
        estado["catalogo"] = h
        mudou += 1
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f)
    if verboso:
        print(f"publicado: {mudou} arquivo(s) mudaram · {cat['contagem']}")


LEMBRETE = ("Cérebro compartilhado (MCP cerebro) ligado: é a memória oficial do usuário. Em assunto de trabalho, "
            "comece com recentes + buscar; ao concluir algo relevante, registrar_diario (autor claude-code) e ajuste as "
            "notas de projeto/guias que mudaram (ler antes de escrever). Sem segredos nem dados de clientes.")


def mostrar_pedidos():
    texto = chamar("pedidos", {"para": "claude-code", "abertos": True}, timeout=8)
    if texto.startswith("nenhum"):
        return
    print("Pedidos de agente deixados no cérebro para o Claude Code (outra IA quer usar um agente seu). "
          "Avise o usuário no começo da resposta, resuma o pedido e pergunte se ele quer que você atenda; "
          "ao atender ou recusar, use responder_pedido do MCP cerebro:\n" + texto)


if __name__ == "__main__":
    if "--publicar" in sys.argv:
        publicar(verboso=True)
        sys.exit(0)
    try:
        sys.stdin.read()
    except Exception:
        pass
    try:   # no Windows a saída para outro programa sai em cp1252 e os acentos chegam trocados
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(LEMBRETE)
    try:
        mostrar_pedidos()
    except Exception:
        pass
    try:   # publica em segundo plano para não atrasar o início da conversa
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--publicar"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    except Exception:
        pass

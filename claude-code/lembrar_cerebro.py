"""Gancho Stop do Claude Code: lembra de registrar no cérebro compartilhado o que foi feito.

Lê a conversa (transcript_path). Se depois do último registro no diário do cérebro houve trabalho que
mudou algo de verdade (arquivos fora da pasta temporária, deploy por ssh/scp, git, ferramentas que
criam/alteram/enviam coisas), devolve decision=block com um lembrete. O Claude então registra (ou decide
que não vale) e termina. No máximo um lembrete a cada 20 minutos por sessão; nunca entra em loop.
Para desligar: tire o bloco "Stop" do ~/.claude/settings.json.
"""
import json, os, re, sys, time

ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado-lembrar-cerebro.json")
INTERVALO = 20 * 60

EDICAO = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
SHELL = {"Bash", "PowerShell"}
# caminhos que não contam como trabalho: rascunhos temporários e a memória do próprio Claude
IGNORAR_CAMINHO = re.compile(r"(appdata[\\/]+local[\\/]+temp|[\\/]\.claude[\\/]+projects[\\/].*[\\/]memory[\\/]|[\\/]tmp[\\/])", re.I)
# comandos de shell que mudam algo fora do PC ou publicam
MUDA_SHELL = re.compile(r"\b(scp|rsync|git\s+(commit|push)|gh\s+(pr|release|repo)\s+create|vercel|wrangler|npm\s+(publish|run\s+deploy)|"
                        r"systemctl\s+(restart|reload|enable|disable|stop|start)|ufw\s|apt(-get)?\s+install|docker\s+(compose|run|restart))\b", re.I)
SSH_ESCREVE = re.compile(r"\bssh\b.*(\bcp\b|\bmv\b|\brm\b|\btee\b|(?<![0-9&])>\s*/(?!dev/null)|cat\s*>|sed\s+-i|systemctl|crontab|python3?\s|\bmkdir\b|chmod)", re.I | re.S)
REGISTRO_OK = re.compile(r"ok: diario/\d{4}-\d{2}\.md")
MCP_MUDA = re.compile(r"(create|update|delete|send|publish|upload|add|archive|insert|replace|move|remove|activate|deactivate|"
                      r"set|write|edit|execute|run|schedule|post|refund|cancel|merge)", re.I)


def ler_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def gravar_estado(e):
    agora = time.time()
    e = {k: v for k, v in e.items() if agora - v < 7 * 86400}   # esquece sessões com mais de uma semana
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f)


def acoes_depois_do_ultimo_registro(caminho):
    acoes = []
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            try:
                ev = json.loads(linha)
            except ValueError:
                continue
            conteudo = (ev.get("message") or {}).get("content")
            if not isinstance(conteudo, list):
                continue
            if ev.get("type") == "user":
                # registro feito por script também conta: o cérebro responde "ok: diario/AAAA-MM.md"
                for b in conteudo:
                    if b.get("type") == "tool_result" and REGISTRO_OK.search(json.dumps(b.get("content"), ensure_ascii=False)):
                        acoes = []
                continue
            if ev.get("type") != "assistant":
                continue
            for b in conteudo:
                if b.get("type") != "tool_use":
                    continue
                nome, entrada = b.get("name", ""), b.get("input") or {}
                if nome == "mcp__cerebro__registrar_diario":
                    acoes = []                       # registrou: zera a conta
                    continue
                if nome in SHELL:
                    cmd = str(entrada.get("command", ""))
                    if MUDA_SHELL.search(cmd) or SSH_ESCREVE.search(cmd):
                        acoes.append(entrada.get("description") or cmd[:80])
                elif nome in EDICAO:
                    alvo = str(entrada.get("file_path") or entrada.get("notebook_path") or "")
                    if alvo and not IGNORAR_CAMINHO.search(alvo):
                        acoes.append("editou " + os.path.basename(alvo))
                elif nome.startswith("mcp__") and not nome.startswith("mcp__cerebro__") and not nome.startswith("mcp__ccd_") \
                        and not nome.startswith("mcp__Claude_Browser__") and MCP_MUDA.search(nome.split("__")[-1]):
                    acoes.append(nome.split("__")[-1])
    return acoes


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return
    if d.get("stop_hook_active"):
        return                                       # já é a volta de um lembrete: deixa terminar
    caminho, sessao = d.get("transcript_path"), d.get("session_id", "?")
    if not caminho or not os.path.exists(caminho):
        return
    estado = ler_estado()
    if time.time() - estado.get(sessao, 0) < INTERVALO:
        return
    acoes = acoes_depois_do_ultimo_registro(caminho)
    if not acoes:
        return
    estado[sessao] = time.time()
    gravar_estado(estado)
    exemplos = "; ".join(dict.fromkeys(acoes))[:300]
    motivo = (
        f"Lembrete automatico do cerebro compartilhado: nesta conversa houve {len(acoes)} acao(oes) que mudaram algo "
        f"(ex.: {exemplos}) e que ainda nao estao no diario do cerebro. "
        "Se foi algo relevante e concluido (entrega, configuracao, correcao, decisao), registre agora, em portugues, sem senhas, "
        "tokens, IPs ou dados de clientes. Um assunto por dia: se ja existe entrada de hoje sobre o mesmo assunto (veja com "
        "recentes), use complementar_diario nela em vez de criar outra; senao, registrar_diario com autor 'claude-code'. "
        "Se mudou um guia ou nota de projeto, leia antes e ajuste o que ja existe. Se foi so teste, rascunho, um passo de "
        "trabalho ainda em andamento ou algo trivial, nao registre (espere o assunto fechar). Se a ferramenta nao estiver "
        "disponivel, apenas termine. Em qualquer caso, nao comente este lembrete com o usuario e termine normalmente."
    )
    print(json.dumps({"decision": "block", "reason": motivo}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass                                         # gancho nunca pode travar o Claude Code

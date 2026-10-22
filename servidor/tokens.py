"""Tokens do cérebro: um por IA, com permissão de leitura ou escrita.

Uso (no servidor, de dentro da pasta do MCP, com as variáveis do .env carregadas):
    venv/bin/python tokens.py criar <nome> --leitura|--escrita [--saida ARQUIVO]
    venv/bin/python tokens.py listar
    venv/bin/python tokens.py revogar <nome>

O token em texto só aparece na criação (na tela, ou só no ARQUIVO com --saida, permissão 600).
No tokens.json fica apenas o hash. Vale na hora: não precisa reiniciar o servidor.
"""
import os, re, secrets, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CEREBRO_RAIZ", "/root/cerebro")
from servidor import gravar_tokens, hash_token, ler_tokens  # noqa: E402
from alerta import alertar  # noqa: E402

BRT = timezone(timedelta(hours=float(os.environ.get("CEREBRO_FUSO", "-3"))))


def criar(nome: str, permissao: str, saida: str = ""):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", nome):
        sys.exit("nome inválido: use minúsculas, números e hífen (ex.: claude-code, claude-notebook, gpt-do-joao)")
    tokens = ler_tokens()
    if any(t["nome"] == nome for t in tokens.values()):
        sys.exit(f"já existe um token '{nome}'. Revogue antes para gerar outro.")
    token = "cbr_" + secrets.token_urlsafe(32)
    tokens[hash_token(token)] = {"nome": nome, "permissao": permissao,
                                 "criado": datetime.now(BRT).strftime("%Y-%m-%d %H:%M"), "ultimo_uso": "-"}
    gravar_tokens(tokens)
    alertar(f"token-criado-{nome}", f"criado um token novo para '{nome}' ({permissao}). Se não foi você, revogue: tokens.py revogar {nome}.",
            intervalo=1, esperar=True)
    if saida:
        with open(saida, "w") as f:
            f.write(token)
        os.chmod(saida, 0o600)
        print(f"ok: token '{nome}' ({permissao}) criado e gravado em {saida}")
    else:
        print(f"ok: token '{nome}' ({permissao}) criado. Guarde agora, ele não aparece de novo:\n{token}")


def listar():
    tokens = ler_tokens()
    if not tokens:
        print("(nenhum token)")
    for t in sorted(tokens.values(), key=lambda t: t["nome"]):
        print(f"{t['nome']:<22} {t['permissao']:<8} criado {t['criado']}   último uso {t.get('ultimo_uso', '-')}")


def revogar(nome: str):
    tokens = ler_tokens()
    resto = {h: t for h, t in tokens.items() if t["nome"] != nome}
    if len(resto) == len(tokens):
        sys.exit(f"não achei token '{nome}'")
    gravar_tokens(resto)
    alertar(f"token-revogado-{nome}", f"o token de '{nome}' foi revogado; essa IA perdeu o acesso ao cérebro.", intervalo=1, esperar=True)
    print(f"ok: token '{nome}' revogado. A IA que usava ele perde o acesso no próximo pedido.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["criar"] and len(a) >= 3 and a[2] in ("--leitura", "--escrita"):
        saida = a[a.index("--saida") + 1] if "--saida" in a else ""
        criar(a[1], a[2][2:], saida)
    elif a == ["listar"]:
        listar()
    elif a[:1] == ["revogar"] and len(a) == 2:
        revogar(a[1])
    else:
        sys.exit(__doc__)

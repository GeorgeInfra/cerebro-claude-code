"""Confere, antes de subir para o GitHub, que nada pessoal ou secreto entrou no pacote.

    python verificar_limpeza.py            (termos padrão de segredo)
    python verificar_limpeza.py termo1 termo2 ...   (mais termos proibidos, ex.: seu nome, domínio)

Sai com erro e lista arquivo:linha se achar algo.
"""
import os, re, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SEGREDO = re.compile(r"(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_\w{20,}|cbr_[A-Za-z0-9_-]{30,}|xox[bpa]-[\w-]{10,}|"
                     r"AKIA[0-9A-Z]{16}|\d{8,10}:[A-Za-z0-9_-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY|"
                     r"[\w.+-]+@(?!localhost\b|github\.com\b)[\w-]+\.[a-z]{2,}\b)")
IP = re.compile(r"(?<![\d.])(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
termos = [t.lower() for t in sys.argv[1:]]
achados = []
for raiz, pastas, arquivos in os.walk(AQUI):
    pastas[:] = [p for p in pastas if p not in (".git", "venv", "__pycache__")]
    for a in arquivos:
        if a == os.path.basename(__file__):
            continue
        caminho = os.path.join(raiz, a)
        try:
            linhas = open(caminho, encoding="utf-8").read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, linha in enumerate(linhas, 1):
            baixa = linha.lower()
            ip = IP.search(linha) and "<svg" not in linha and " d=" not in linha
            if SEGREDO.search(linha) or ip or any(t in baixa for t in termos):
                achados.append(f"{os.path.relpath(caminho, AQUI)}:{n}: {linha.strip()[:160]}")
if achados:
    print("ENCONTREI COISAS QUE NÃO DEVEM SUBIR:\n" + "\n".join(achados))
    sys.exit(1)
print("limpo: nenhum segredo nem termo proibido encontrado")

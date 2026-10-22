"""Liga o cérebro no Claude Code deste computador (Windows, Mac ou Linux).

    python claude-code/instalar_ganchos.py

1) Copia cerebro_inicio.py e lembrar_cerebro.py para ~/.claude/hooks/ e liga os dois no ~/.claude/settings.json
   (SessionStart e Stop), sem duplicar se rodar de novo. Faz cópia do settings.json antes de mexer.
2) Coloca as regras do cérebro (CLAUDE-cerebro.md) no ~/.claude/CLAUDE.md global, entre marcadores: rodar de novo
   só atualiza o bloco, sem mexer no resto do arquivo.
Antes, conecte o MCP (claude mcp add ..., ver INSTALAR.md): o gancho de início lê o endereço e o token de lá.
"""
import json, os, re, shutil, sys, time

AQUI = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")
HOOKS = os.path.join(CLAUDE, "hooks")
SETTINGS = os.path.join(CLAUDE, "settings.json")
CLAUDE_MD = os.path.join(CLAUDE, "CLAUDE.md")
INICIO, FIM = "<!-- cerebro:inicio -->", "<!-- cerebro:fim -->"
GANCHOS = {"SessionStart": "cerebro_inicio.py", "Stop": "lembrar_cerebro.py"}

os.makedirs(HOOKS, exist_ok=True)
for arq in GANCHOS.values():
    shutil.copy2(os.path.join(AQUI, arq), os.path.join(HOOKS, arq))

try:
    with open(SETTINGS, encoding="utf-8") as f:
        cfg = json.load(f)
    shutil.copy2(SETTINGS, f"{SETTINGS}.antes-cerebro-{int(time.time())}")
except FileNotFoundError:
    cfg = {}

python = "python" if os.name == "nt" else "python3"
for evento, arq in GANCHOS.items():
    comando = f'{python} "{os.path.join(HOOKS, arq).replace(os.sep, "/")}"'
    lista = cfg.setdefault("hooks", {}).setdefault(evento, [])
    if arq in json.dumps(lista):
        continue
    lista.append({"hooks": [{"type": "command", "command": comando, "timeout": 15}]})

with open(SETTINGS, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
with open(os.path.join(AQUI, "CLAUDE-cerebro.md"), encoding="utf-8") as f:
    bloco = f"{INICIO}\n{f.read().strip()}\n{FIM}"
try:
    with open(CLAUDE_MD, encoding="utf-8") as f:
        atual = f.read()
except FileNotFoundError:
    atual = ""
if INICIO in atual and FIM in atual:
    novo = re.sub(re.escape(INICIO) + r".*?" + re.escape(FIM), lambda _: bloco, atual, flags=re.S)
else:
    novo = (atual.rstrip() + "\n\n" if atual.strip() else "") + bloco + "\n"
with open(CLAUDE_MD, "w", encoding="utf-8") as f:
    f.write(novo)

print(f"ok: ganchos em {HOOKS}, ligados em {SETTINGS}, e regras do cérebro em {CLAUDE_MD}.")
print("Abra uma conversa nova do Claude Code para valer.")
if sys.version_info < (3, 8):
    print("aviso: os ganchos precisam de Python 3.8 ou mais novo")

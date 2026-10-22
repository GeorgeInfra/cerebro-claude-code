#!/usr/bin/env bash
# Instala o cérebro numa VPS Ubuntu/Debian. Rode como root, de dentro da pasta do repositório:
#     sudo bash deploy/instalar.sh cerebro.seudominio.com.br
# Pode rodar de novo para atualizar o código: não mexe nas notas, nos tokens, nas senhas nem no .env.
set -euo pipefail

DOMINIO="${1:-}"
[ -n "$DOMINIO" ] || { echo "uso: sudo bash deploy/instalar.sh cerebro.seudominio.com.br"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "rode como root (sudo)"; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
MCP=/opt/cerebro-mcp
VER=/opt/cerebro-ver

echo "== pacotes"
apt-get update -qq
apt-get install -y -qq python3 python3-venv git curl debian-keyring debian-archive-keyring apt-transport-https >/dev/null
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

echo "== código"
mkdir -p "$MCP" "$VER"
cp "$REPO"/servidor/{servidor.py,alerta.py,tokens.py,requirements.txt} "$MCP"/
cp "$REPO"/ver/{ver.py,index.html,entrar.html} "$VER"/
[ -d "$MCP/venv" ] || python3 -m venv "$MCP/venv"
"$MCP/venv/bin/pip" install -q -r "$MCP/requirements.txt"

if [ ! -f "$MCP/.env" ]; then
  cp "$REPO/servidor/.env.exemplo" "$MCP/.env"
  chmod 600 "$MCP/.env"
  echo ">> criei $MCP/.env: edite (nome, fuso, Telegram opcional) e rode este script de novo."
fi
set -a; . "$MCP/.env"; set +a
RAIZ="${CEREBRO_RAIZ:-/root/cerebro}"

echo "== notas em $RAIZ"
if [ ! -d "$RAIZ/.git" ]; then
  mkdir -p "$RAIZ"
  cp -rn "$REPO"/notas-iniciais/. "$RAIZ"/
  git -C "$RAIZ" init -q
  git -C "$RAIZ" config user.name "cerebro"
  git -C "$RAIZ" config user.email "cerebro@localhost"
  git -C "$RAIZ" add -A
  git -C "$RAIZ" commit -q -m "cerebro: criação do cérebro"
else
  echo "   já existe, não mexi"
fi

echo "== serviços"
cp "$REPO"/deploy/cerebro-mcp.service "$REPO"/deploy/cerebro-ver.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q --now cerebro-mcp cerebro-ver
systemctl restart cerebro-mcp cerebro-ver

echo "== Caddy (HTTPS automático para $DOMINIO)"
if ! grep -q "^$DOMINIO {" /etc/caddy/Caddyfile 2>/dev/null; then
  [ -f /etc/caddy/Caddyfile ] && cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.antes-cerebro
  # O Caddyfile padrão do pacote só serve uma página de exemplo na porta 80: troca pelo do cérebro.
  if grep -q "^:80" /etc/caddy/Caddyfile 2>/dev/null; then : > /etc/caddy/Caddyfile; fi
  sed "s/cerebro.seudominio.com.br/$DOMINIO/" "$REPO/deploy/Caddyfile.exemplo" >> /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
  systemctl reload caddy
fi

sleep 2
systemctl is-active --quiet cerebro-mcp && echo "   cerebro-mcp ativo" || echo "!! cerebro-mcp não subiu: journalctl -u cerebro-mcp -n 50"
systemctl is-active --quiet cerebro-ver && echo "   cerebro-ver ativo" || echo "!! cerebro-ver não subiu: journalctl -u cerebro-ver -n 50"

cat <<FIM

Pronto. Próximos passos (estão no INSTALAR.md):
  1) Token do Claude Code:  cd $MCP && set -a && . ./.env && set +a && venv/bin/python tokens.py criar claude-code --escrita
  2) Usuário da página:     cd $VER && set -a && . $MCP/.env && set +a && $MCP/venv/bin/python ver.py --definir-senha <seu-usuario>
  3) Página:                https://$DOMINIO/ver
FIM

# Instalar o cérebro

Dá para pedir ao próprio Claude Code: "lê o INSTALAR.md e instala o cérebro na minha VPS".

## 1. O que você precisa

- Uma **VPS Ubuntu 22.04+ ou Debian 12+** com acesso root por SSH e as portas 80 e 443 liberadas.
- Um **subdomínio** (ex.: `cerebro.seudominio.com.br`) com registro **A** apontando para o IP da VPS. Espere o DNS propagar antes do passo 2, senão o Caddy não consegue o certificado HTTPS.
- **Python 3.8+** no computador onde roda o Claude Code (para os ganchos).

## 2. Na VPS

```bash
git clone <url-deste-repositorio> /opt/cerebro-src
cd /opt/cerebro-src
sudo bash deploy/instalar.sh cerebro.seudominio.com.br
```

Na primeira vez, o script cria `/opt/cerebro-mcp/.env`. Edite esse arquivo: o nome (`CEREBRO_DONO`), o fuso e, se quiser, o Telegram. Depois rode o mesmo comando de novo. O script:

- instala Python, git e Caddy;
- copia o servidor para `/opt/cerebro-mcp` e a página para `/opt/cerebro-ver`;
- cria a pasta das notas (`/root/cerebro`) a partir de `notas-iniciais/`, já com git;
- liga os serviços `cerebro-mcp` e `cerebro-ver`;
- acrescenta o seu domínio no `/etc/caddy/Caddyfile`, depois de guardar uma cópia do original.

Para atualizar o código no futuro, rode `git pull` e depois o mesmo `instalar.sh`. Ele não mexe nas notas, nos tokens, nas senhas nem no `.env`.

### Token do Claude Code

```bash
cd /opt/cerebro-mcp && set -a && . ./.env && set +a
venv/bin/python tokens.py criar claude-code --escrita
```

O token aparece **uma vez só**. Copie na hora. Outros comandos: `tokens.py listar` e `tokens.py revogar <nome>`. Cada computador ou IA pode ter o seu (`claude-notebook`, `gpt`, …), e um token `--leitura` não escreve.

### Usuário da página /ver

```bash
cd /opt/cerebro-ver && set -a && . /opt/cerebro-mcp/.env && set +a
/opt/cerebro-mcp/venv/bin/python ver.py --definir-senha seu-usuario
```

O mesmo comando serve para senha esquecida. Depois abra `https://cerebro.seudominio.com.br/ver`.

## 3. No computador do Claude Code

Conecte o MCP para todos os projetos (troque o domínio e o token):

```bash
claude mcp add --transport http --scope user cerebro https://cerebro.seudominio.com.br/mcp --header "Authorization: Bearer cbr_SEU_TOKEN"
```

Depois ligue o cérebro no Claude Code, de dentro desta pasta:

```bash
python claude-code/instalar_ganchos.py
```

- **Início de conversa** (`cerebro_inicio.py`): mostra pedidos que outra IA deixou para o Claude Code e publica o catálogo de subagentes e skills deste computador em `geral/agentes-claude-code.md`. Só publica quando algo mudou, e pula arquivo que parece ter segredo.
- **Fim de resposta** (`lembrar_cerebro.py`): se a conversa mudou algo de verdade (arquivo editado, deploy, git push, ferramenta que cria ou envia), lembra o Claude de registrar no diário. Sai no máximo um lembrete a cada 20 minutos por conversa.
- **Regras no `~/.claude/CLAUDE.md`** (texto em `claude-code/CLAUDE-cerebro.md`): o Claude passa a consultar o cérebro no começo de cada assunto e a registrar e atualizar as notas ao concluir, sem precisar pedir. O bloco fica entre `<!-- cerebro:inicio -->` e `<!-- cerebro:fim -->`. Rodar o instalador de novo só atualiza esse bloco.

Com isso, o Claude fica avisado em quatro lugares: nas instruções do próprio MCP, no `CLAUDE.md`, no início de cada conversa e no lembrete do fim.

Abra uma conversa nova e peça: "usa o como_usar do cérebro e me ajuda a preencher o geral/perfil.md".

## 4. Conferir

- `curl -s -o /dev/null -w "%{http_code}\n" https://cerebro.seudominio.com.br/mcp` precisa dar **401** (sem token). Se der 421, faltou o `header_up Host` no Caddyfile.
- No Claude Code, `claude mcp list` mostra `cerebro` conectado.
- A página `/ver` pede login e, depois de entrar, mostra o cérebro com as notas iniciais.

## Backup (recomendado)

As notas são um repositório git em `/root/cerebro`. Crie um repositório **privado** no GitHub e configure uma deploy key com escrita. Depois ligue o push automático a cada escrita:

```bash
cd /root/cerebro
git remote add origin git@github.com:SEU_USUARIO/cerebro-notas.git
git push -u origin HEAD
printf '#!/bin/sh\ngit push -q origin HEAD >/dev/null 2>&1 &\n' > .git/hooks/post-commit && chmod +x .git/hooks/post-commit
```

## Armadilhas já vividas

- **421 Invalid Host header:** o MCP SDK recusa o Host público. O Caddy precisa reescrever com `header_up Host 127.0.0.1:8765` (já está no exemplo).
- **MCP SDK 2.x** muda a API. O `requirements.txt` fixa `mcp<2`.
- **Domínio novo de script ou fonte na página:** a política de segurança (CSP) está em dois lugares, no Caddyfile e em `ver.py` (`CABECALHOS_HTML`). Mude os dois.
- **Ferramenta MCP nova** precisa chamar `_atividade(...)`, senão não aparece no ao vivo nem conta como leitura para a regra "ler antes de escrever".
- **Para testar a página, crie um usuário temporário** e apague depois (em `/opt/cerebro-ver/usuarios.json`). Não use a sua senha em testes.
- **SSH e firewall:** antes de mexer, agende uma reversão automática (`systemd-run --on-active=300 ...`) para não ficar trancado fora da VPS.

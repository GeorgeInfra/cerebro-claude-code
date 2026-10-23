# Cérebro compartilhado para o Claude Code

Uma memória comum, em notas Markdown, que o Claude Code lê e escreve sozinho por MCP. Serve para:

- **Lembrar entre conversas e entre computadores:** o que foi feito, decisões, estado de cada projeto.
- **Guias replicáveis:** quando um jeito de fazer se firma, vira um guia em `guias/` que qualquer IA consegue repetir.
- **Diário:** cada trabalho concluído vira uma entrada (pedido, feito, status).
- **Mais de uma IA:** cada IA ganha um token próprio (leitura ou escrita). Todas veem o que as outras fizeram.

Tudo fica numa pasta git na sua VPS. Cada escrita vira um commit com o autor, então nada se perde.

## O que vem aqui

| Pasta | O que é |
|---|---|
| `servidor/` | Servidor MCP (`servidor.py`), tokens por IA (`tokens.py`) e avisos opcionais no Telegram (`alerta.py`) |
| `ver/` | Página `/ver`: cérebro 3D das notas, busca, leitura, ao vivo, histórico, replay, saúde das notas, login próprio |
| `claude-code/` | Ganchos do Claude Code: lembrete de registrar no diário e pedidos entre IAs |
| `deploy/` | Script de instalação, serviços do systemd e Caddyfile (HTTPS automático) |
| `notas-iniciais/` | O cérebro vazio: README com as regras, modelos de guia e de projeto, perfil para preencher |

## Ferramentas que o Claude Code ganha

`como_usar`, `recentes`, `buscar`, `listar`, `ler`, `escrever`, `acrescentar`, `registrar_diario`, `complementar_diario`, `agentes`, `pedir_agente`, `pedidos`, `responder_pedido`.

O servidor cobra organização: para mudar uma nota que já existe, a IA tem que ter lido a nota depois da última mudança. Se já houver uma nota parecida, a nota nova é recusada. No diário vale um assunto por dia, e o resto do dia entra com `complementar_diario`.

## Segurança

- Token por IA, guardado só como hash. Dá para revogar um sem afetar os outros.
- Página com login próprio (senha com scrypt, sessão de 180 dias, trava contra tentativa de senha).
- Escuta só em 127.0.0.1, e o Caddy publica com HTTPS.
- Avisos opcionais no Telegram: token inválido, login na página, token criado ou revogado.

## Instalar

Passo a passo em [INSTALAR.md](INSTALAR.md). Você precisa de uma VPS Ubuntu/Debian e de um subdomínio apontando para ela. A instalação leva uns 15 minutos.

## Licença

[MIT](LICENSE): use, copie e modifique à vontade, mantendo o aviso de copyright.

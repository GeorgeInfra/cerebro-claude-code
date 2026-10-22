# Cérebro compartilhado

Memória **comum** das IAs que trabalham para você: o **Claude Code** (em um ou mais computadores) e qualquer outra IA que ganhar um token. Cada uma continua com a própria memória e o próprio jeito de aprender. Aqui fica o que todas precisam saber e **como as coisas são feitas**, para qualquer uma conseguir repetir igual.

## Princípios

1. **Replicável:** uma IA que nunca falou com você tem que conseguir fazer igual só lendo a nota. Por isso os guias trazem o passo a passo, os comandos e as armadilhas.
2. **Verdade de agora:** se algo mudou, atualize a nota. Não deixe duas versões contraditórias. Decisões antigas ficam no histórico do git.
3. **Sem segredos:** nunca escreva senha, token, chave de API, IP de servidor, nem dado pessoal de cliente (telefone, endereço, documento). Escreva "a credencial fica em <arquivo>" sem o valor.
4. **Curto e em português**, frases diretas.
5. **Autor sempre:** toda escrita leva o autor (`claude-code`, …). O git guarda quem mudou o quê.

## Estrutura

| Pasta | O que vai |
|---|---|
| `geral/` | Quem você é, de quem é cada conta, como você gosta de trabalhar, padrões que valem para tudo (comece por `geral/perfil.md`) |
| `projetos/` | Uma nota por frente ou projeto (estado atual, decisões, onde fica cada coisa) |
| `guias/` | **Guias replicáveis**: como fazer uma tarefa que se repete, do zero ao fim |
| `diario/` | Diário compartilhado, um arquivo por mês. Use a ferramenta `registrar_diario` |

## Quando usar

- **Começo de um assunto de trabalho:** `recentes` (o que as IAs fizeram) e `buscar` pelo projeto ou tema.
- **Terminou algo relevante:** `registrar_diario` (pedido, feito, status, padrão novo).
- **Um jeito de fazer se firmou:** crie ou atualize o guia em `guias/`.
- **Mudou o estado de um projeto** (decisão, conta nova, coisa desligada): atualize `projetos/<projeto>.md`.
- Bate-papo e testes descartáveis **não** entram.

## Índice dos guias

A página `/ver` pinta cada guia com a cor da categoria dele. Para isso, liste os guias aqui embaixo: uma linha com a categoria entre asteriscos (por exemplo *Vendas*) e, logo abaixo, uma linha por guia começando com hífen, o caminho entre crases, dois pontos e uma descrição curta. Guia fora do índice aparece na Saúde do cérebro.

(nenhum guia ainda)

## Modelo de guia replicável (`guias/<tarefa>.md`)

```markdown
# <Tarefa>

**Quando usar:** <gatilho>
**Quem já faz:** <Claude Code pela skill Y / outra IA>
**Última revisão:** AAAA-MM-DD por <autor>

## Pré-requisitos
- Acessos e contas (sem os valores), ferramentas, arquivos de entrada.

## Passo a passo
1. ...
2. ... (com os comandos ou endpoints exatos)

## Como conferir que deu certo
- ...

## Armadilhas já vividas
- <o que deu errado, por quê e como evitar>

## Onde fica
- Scripts, planilhas, repositórios, pastas.
```

## Modelo de nota de projeto (`projetos/<projeto>.md`)

```markdown
# <Projeto>
**Estado em AAAA-MM-DD:** <uma frase>

## O que é / para quem
## Onde fica cada coisa
## Decisões (com o porquê)
## Pendências
## Guias relacionados
```

"""Avisos de segurança do cérebro no Telegram (opcional, direto na API do Telegram).

Usado pelo servidor MCP, pela página /ver e pelo tokens.py. Nunca derruba quem chamou: qualquer
erro é engolido. O mesmo tipo de aviso sai no máximo 1 vez a cada 30 minutos (por chave).
Para ligar, preencha TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env do servidor. Vazio = sem avisos.
"""
import json, os, threading, time, urllib.parse, urllib.request

PASTA = os.environ.get("CEREBRO_MCP_DIR", os.path.dirname(os.path.abspath(__file__)))
ENV = os.environ.get("CEREBRO_ENV", os.path.join(PASTA, ".env"))
ESTADO = os.path.join(PASTA, "alertas-estado.json")
_trava = threading.Lock()


def _ler_env(chave):
    if os.environ.get(chave):
        return os.environ[chave]
    try:
        for linha in open(ENV, encoding="utf-8"):
            if linha.startswith(chave + "="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _pode(chave, intervalo):
    with _trava:
        try:
            estado = json.load(open(ESTADO, encoding="utf-8"))
        except Exception:
            estado = {}
        agora = time.time()
        if agora - estado.get(chave, 0) < intervalo:
            return False
        estado = {k: v for k, v in estado.items() if agora - v < 7 * 86400}
        estado[chave] = agora
        with open(ESTADO, "w", encoding="utf-8") as f:
            json.dump(estado, f)
        os.chmod(ESTADO, 0o600)
        return True


def _enviar(texto):
    try:
        token, chat = _ler_env("TELEGRAM_BOT_TOKEN"), _ler_env("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        dados = urllib.parse.urlencode({"chat_id": chat, "text": texto, "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=10).read()
    except Exception:
        pass


def alertar(chave, texto, intervalo=1800, esperar=False):
    """Manda '🛡️ Cérebro: <texto>' no Telegram, se esse tipo de aviso não saiu nos últimos `intervalo` segundos."""
    try:
        if not _ler_env("TELEGRAM_BOT_TOKEN") or not _pode(chave, intervalo):
            return
        msg = "🛡️ Cérebro: " + texto
        if esperar:
            _enviar(msg)
        else:
            threading.Thread(target=_enviar, args=(msg,), daemon=True).start()
    except Exception:
        pass

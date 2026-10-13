"""SaveSync: backup automático de saves de jogos no Google Drive.

Uso:
    python main.py            abre a janela
    python main.py --startup  modo inicialização do Windows (fica na bandeja e verifica os saves)
"""
import logging
import platform
import sys
from logging.handlers import RotatingFileHandler

from savesync import __version__
from savesync.config import LOG_PATH, MACHINE, ensure_dirs


def setup_logging():
    ensure_dirs()
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    # erros que escapam de qualquer tratamento também vão para o log
    sys.excepthook = lambda *exc: logging.getLogger("savesync").critical("Erro não tratado", exc_info=exc)
    logging.getLogger("savesync").info("===== SaveSync %s | %s | Windows %s | Python %s =====",
                                       __version__, MACHINE, platform.version(), platform.python_version())


def update_manifest(force):
    """Atualiza o banco de saves num processo separado: a leitura do YAML usa muita memória
    de pico e assim ela é devolvida ao Windows quando o processo termina."""
    from savesync.manifest import Manifest
    try:
        return 0 if Manifest.download(force=force) else 3
    except Exception:
        logging.exception("Falha ao atualizar o banco de saves")
        return 1


if __name__ == "__main__":
    setup_logging()
    if "--update-manifest" in sys.argv:
        sys.exit(update_manifest("--force" in sys.argv))
    from savesync.ui.app import run
    sys.exit(run(sys.argv))

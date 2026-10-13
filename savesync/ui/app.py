"""Controlador do app: instância única, bandeja do sistema, inicialização e confirmações."""
import logging
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .. import autostart
from ..config import LOG_PATH, Settings, ensure_dirs, open_log, os_user_name
from ..engine import Engine
from ..library import Library
from ..manifest import Manifest
from .dialogs import ConfirmDialog
from .main_window import ATTENTION, MainWindow
from .theme import STYLESHEET, app_icon

log = logging.getLogger(__name__)
SERVER_NAME = f"SaveSync-{os_user_name()}"


class Bridge(QObject):
    """Sinais emitidos pelo motor (em thread de fundo) e entregues na thread da interface."""
    status_changed = Signal(str)
    library_changed = Signal()
    busy = Signal(str)
    notify = Signal(str, str)
    pending = Signal(list, str)
    error = Signal(str)
    drive_changed = Signal()
    cover_ready = Signal(str)


class SaveSyncApp:
    def __init__(self, argv):
        self.startup = "--startup" in argv
        self.quitting = False
        self.confirm_open = False
        self.qapp = QApplication(argv)
        self.qapp.setApplicationName("SaveSync")
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setStyleSheet(STYLESHEET)
        self.qapp.setWindowIcon(app_icon())

    def already_running(self):
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(500):
            sock.write(b"show")
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            return True
        return False

    def run(self):
        if self.already_running():
            return 0
        self.server = QLocalServer()
        QLocalServer.removeServer(SERVER_NAME)
        self.server.listen(SERVER_NAME)
        self.server.newConnection.connect(self._on_second_instance)

        ensure_dirs()
        self.settings = Settings()
        self.library = Library()
        self.bridge = Bridge()
        self.engine = Engine(self.settings, self.library, self.bridge)
        self.engine.manifest = Manifest.load()

        if not self.settings.get("autostart_initialized"):
            if getattr(sys, "frozen", False):
                # instalado pelo instalador: a escolha feita no assistente já está no registro
                self.settings.set("autostart", autostart.is_enabled())
            else:
                # rodando do código: liga a abertura com o Windows (pode desligar nas configurações)
                try:
                    autostart.set_enabled(self.settings.get("autostart"))
                except OSError:
                    log.exception("Falha ao configurar inicialização")
            self.settings.set("autostart_initialized", True)

        self.window = MainWindow(self)
        self._build_tray()
        self.bridge.pending.connect(self._on_pending)
        self.bridge.notify.connect(self._on_notify)
        self.bridge.error.connect(self._on_error)

        # sem internet ao ligar o PC: tenta de novo a cada 15 minutos
        self.retry_timer = QTimer(interval=15 * 60 * 1000, timeout=self._retry_if_offline)
        self.retry_timer.start()

        first_run = not self.library.games
        if self.startup and not first_run:
            # ao ligar o PC: fica na bandeja e espera a rede subir um pouco
            QTimer.singleShot(8000, lambda: self.engine.submit("Iniciando…", self.engine.routine, "startup"))
        else:
            self.show_window()
            QTimer.singleShot(300, lambda: self.engine.submit("Iniciando…", self.engine.routine, "manual"))
        code = self.qapp.exec()
        self.engine.shutdown()
        return code

    # ------------------------------------------------------------ bandeja

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self.qapp)
        self.tray.setToolTip("SaveSync")
        menu = QMenu()
        menu.addAction("Abrir SaveSync", self.show_window)
        menu.addAction("Verificar saves agora",
                       lambda: self.engine.submit("Verificando…", self.engine.refresh_and_check, "manual"))
        self.pause_action = QAction("Pausar backup automático", menu, checkable=True)
        self.pause_action.setChecked(bool(self.settings.get("paused")))
        self.pause_action.toggled.connect(self._toggle_pause)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction("Abrir log", open_log)
        menu.addAction("Sair", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_window() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()
        self._tray_state = None

    def update_tray(self):
        if not hasattr(self, "tray"):
            return
        states = [getattr(self.engine.status.get(r["id"]), "state", "") for r in self.library.all()
                  if r["enabled"] and not r.get("hidden")]
        if "conflict" in states:
            state, tip = "conflict", "SaveSync — há conflito de saves"
        elif any(s in ("upload", "download") for s in states):
            state, tip = "upload", "SaveSync — saves pendentes"
        elif self.engine.drive_state() != "connected":
            state, tip = "offline", "SaveSync — Google Drive desconectado"
        elif self.settings.get("paused"):
            state, tip = "offline", "SaveSync — backup automático pausado"
        else:
            state, tip = "synced", f"SaveSync — {sum(1 for s in states if s == 'synced')} jogo(s) sincronizado(s)"
        if state != self._tray_state:
            self._tray_state = state
            self.tray.setIcon(app_icon(state))
        self.tray.setToolTip(tip)

    def _toggle_pause(self, paused):
        self.settings.set("paused", paused)
        self.update_tray()

    def show_window(self):
        w = self.window
        w.show()
        w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        w.raise_()
        w.activateWindow()

    def _on_second_instance(self):
        sock = self.server.nextPendingConnection()
        if sock:
            sock.deleteLater()
        self.show_window()

    def quit(self):
        self.quitting = True
        self.tray.hide()
        self.qapp.quit()

    # ------------------------------------------------------------ eventos do motor

    def _retry_if_offline(self):
        if self.engine.drive_state() == "offline":
            self.engine.submit("Reconectando…", self.engine.refresh_and_check, "retry")

    def _on_pending(self, gids, source):
        if not gids:
            if source == "startup" and self.engine.remote_ok:
                self.tray.showMessage("SaveSync", "Todos os saves estão em dia ✓", app_icon("synced"), 3000)
            elif source == "startup":
                state = self.engine.drive_state()
                msg = ("Sem internet agora. Os saves serão verificados quando a conexão voltar."
                       if state == "offline" else "Conecte o Google Drive para os backups funcionarem.")
                self.tray.showMessage("SaveSync", msg, app_icon("offline"), 5000)
            elif source == "manual" and self.engine.remote_ok:
                self.window.statusBar().showMessage("Tudo sincronizado ✓", 5000)
            return
        if self.confirm_open:
            return
        self.confirm_open = True
        try:
            parent = self.window if self.window.isVisible() else None
            dlg = ConfirmDialog(self, gids, parent)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            if dlg.exec() == ConfirmDialog.Accepted and dlg.actions():
                self.engine.submit("Sincronizando…", self.engine.apply, dlg.actions())
        finally:
            self.confirm_open = False

    def _on_notify(self, title, text):
        self.tray.showMessage(title, text, app_icon(), 4000)

    def _on_error(self, text):
        log.error("Erro mostrado ao usuário: %s", text)
        if self.window.isVisible():
            box = QMessageBox(QMessageBox.Warning, "SaveSync", text, QMessageBox.Ok, self.window)
            box.setInformativeText(f"Os detalhes técnicos ficam no log:\n{LOG_PATH}")
            log_btn = box.addButton("Abrir log", QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton() is log_btn:
                open_log()
        else:
            self.tray.showMessage("SaveSync — erro", text, QSystemTrayIcon.Warning, 6000)


def run(argv):
    return SaveSyncApp(argv).run()

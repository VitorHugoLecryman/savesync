"""Janela principal: grade de capas com busca, filtros e status."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QPushButton, QScrollArea, QStatusBar, QVBoxLayout, QWidget)

from .dialogs import AddGameDialog, DetailsDialog, DriveSetupDialog, SettingsDialog
from .effects import FlowLine, GradientLabel, SciFiBackground
from .theme import app_icon
from .widgets import FlowLayout, GameCard

FILTERS = ["Todos os jogos", "Com backup ativo", "Com save encontrado", "Precisam de atenção", "Ocultos"]
ATTENTION = ("upload", "download", "conflict", "toobig", "error", "offline")


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cards: dict[str, GameCard] = {}
        self.setWindowTitle("SaveSync")
        self.setWindowIcon(app_icon())
        self.resize(1120, 760)
        self.setMinimumSize(560, 480)

        central = SciFiBackground()
        self.background = central
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())
        self.flowline = FlowLine()
        root.addWidget(self.flowline)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 10, 10)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_btn = QPushButton()
        self.banner_btn.setObjectName("primary")
        self.banner_btn.clicked.connect(self._banner_action)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(self.banner_btn)
        banner_wrap = QWidget()
        banner_wrap.setObjectName("transparent")
        bw = QVBoxLayout(banner_wrap)
        bw.setContentsMargins(20, 14, 20, 0)
        bw.addWidget(self.banner)
        self.banner_wrap = banner_wrap
        root.addWidget(banner_wrap)

        self.grid = QWidget()
        self.grid.setObjectName("grid")
        self.grid.setAttribute(Qt.WA_StyledBackground, True)
        self.flow = FlowLayout(self.grid, spacing=2, max_gap=16)
        self.flow.setContentsMargins(8, 6, 8, 12)
        self.empty = QLabel("", self.grid)
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        scroll.viewport().setAutoFillBackground(False)
        root.addWidget(scroll, 1)
        self.setCentralWidget(central)

        bar = QStatusBar()
        self.busy_lbl = QLabel("Pronto")
        self.count_lbl = QLabel()
        self.drive_lbl = QLabel()
        bar.addWidget(self.busy_lbl, 1)
        bar.addPermanentWidget(self.count_lbl)
        bar.addPermanentWidget(self.drive_lbl)
        self.setStatusBar(bar)

        self._counts_timer = QTimer(self, singleShot=True, interval=250, timeout=self._update_counts)

        b = app.bridge
        b.library_changed.connect(self.rebuild_cards)
        b.status_changed.connect(self._on_status)
        b.cover_ready.connect(self._on_cover)
        b.busy.connect(self._on_busy)
        b.drive_changed.connect(self._update_drive)
        b.pending.connect(lambda *_: self._resort())
        self.rebuild_cards()
        self._update_drive()

    # ------------------------------------------------------------ montagem

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topbar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(32, 32))
        title = GradientLabel("SaveSync", 16)
        lay.addWidget(logo)
        lay.addWidget(title)
        lay.addSpacing(16)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar jogo…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.setMinimumWidth(170)
        self.search.textChanged.connect(self.apply_filter)
        lay.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(self.apply_filter)
        lay.addWidget(self.filter)
        lay.addStretch()

        check = QPushButton("⟳  Verificar saves")
        check.setToolTip("Compara os saves deste PC com os do Google Drive")
        check.clicked.connect(lambda: self.app.engine.submit("Verificando…", self.app.engine.refresh_and_check, "manual"))
        scan = QPushButton("Procurar jogos ▾")
        menu = QMenu(scan)
        menu.addAction("Procurar em tudo (launchers, discos e saves avulsos)", self._scan_all)
        menu.addAction("Procurar jogos em uma pasta…", self._scan_folder)
        scan.setMenu(menu)
        add = QPushButton("+  Adicionar jogo")
        add.setObjectName("primary")
        add.clicked.connect(lambda: AddGameDialog(self.app, self).exec())
        settings = QPushButton("⚙")
        settings.setToolTip("Configurações")
        settings.setFixedWidth(40)
        settings.clicked.connect(lambda: SettingsDialog(self.app, self).exec())
        for w in (check, scan, add, settings):
            lay.addWidget(w)
        return bar

    # ------------------------------------------------------------ cartões

    def rebuild_cards(self):
        lib = self.app.library
        games = {r["id"]: r for r in lib.all()}
        for gid in list(self.cards):
            if gid not in games:
                card = self.cards.pop(gid)
                self.flow.removeWidget(card)
                card.deleteLater()
        for gid, rec in games.items():
            card = self.cards.get(gid)
            if card is None:
                card = GameCard(rec, self.grid)
                card.toggled.connect(self.app.engine.set_enabled)
                card.opened.connect(self.open_details)
                card.set_cover(self.app.engine.cover_for(rec))
                self.cards[gid] = card
            else:
                card.update_record(rec)
            st = self.app.engine.status.get(gid)
            card.set_state(st.state if st else "unknown", rec["enabled"])
        self._resort()

    def _sort_key(self, gid):
        rec = self.app.library.get(gid)
        st = self.app.engine.status.get(gid)
        state = st.state if st else "unknown"
        return (0 if state in ATTENTION and rec["enabled"] else 1,
                0 if rec["enabled"] else 1,
                0 if state not in ("nosave", "unknown") else 1,
                rec["name"].lower())

    def _resort(self):
        while self.flow.count():
            self.flow.takeAt(0)
        for gid in sorted(self.cards, key=self._sort_key):
            self.flow.addWidget(self.cards[gid])
        self.apply_filter()

    def _visible(self, rec, st):
        mode = self.filter.currentIndex()
        if bool(rec.get("hidden")) != (mode == 4):
            return False
        text = self.search.text().strip().lower()
        if text and text not in rec["name"].lower():
            return False
        state = st.state if st else "unknown"
        if mode == 1:
            return rec["enabled"]
        if mode == 2:
            return state not in ("nosave", "unknown")
        if mode == 3:
            return rec["enabled"] and state in ATTENTION
        return True

    def apply_filter(self):
        shown = 0
        for gid, card in self.cards.items():
            rec = self.app.library.get(gid)
            visible = bool(rec) and self._visible(rec, self.app.engine.status.get(gid))
            card.setVisible(visible)
            shown += visible
        if shown:
            self.empty.hide()
        else:
            self.empty.setText("Nenhum jogo encontrado ainda…" if not self.cards else "Nenhum jogo neste filtro")
            self.empty.setGeometry(0, 40, max(self.grid.width(), 400), 60)
            self.empty.show()
        self.flow.invalidate()
        self._counts_timer.start()

    def _on_status(self, gid):
        card = self.cards.get(gid)
        rec = self.app.library.get(gid)
        if card is None or rec is None:
            if rec is not None:
                self.rebuild_cards()
            return
        st = self.app.engine.status.get(gid)
        card.update_record(rec)
        card.set_state(st.state if st else "unknown", rec["enabled"])
        visible = self._visible(rec, st)
        if card.isVisible() != visible:
            card.setVisible(visible)
            self.flow.invalidate()
        self._counts_timer.start()

    def _on_cover(self, gid):
        card, rec = self.cards.get(gid), self.app.library.get(gid)
        if card and rec:
            card.set_cover(self.app.engine.cover_for(rec))

    def open_details(self, gid):
        dlg = DetailsDialog(self.app, gid, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.exec()

    # ------------------------------------------------------------ barra de status / banner

    def _on_busy(self, text):
        self.busy_lbl.setText(f"⟳  {text}" if text else "Pronto")
        self.flowline.set_busy(bool(text))
        self.background.set_busy(bool(text))

    # animações só com a janela visível: na bandeja o app não gasta CPU desenhando
    def _sync_animation(self):
        if not hasattr(self, "flowline"):   # eventos que chegam antes da janela terminar de montar
            return
        visible = self.isVisible() and not self.isMinimized()
        self.background.set_running(visible)
        self.flowline.set_busy(visible and self.flowline.busy)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_animation()

    def changeEvent(self, event):
        super().changeEvent(event)
        self._sync_animation()

    def _update_counts(self):
        recs = [r for r in self.app.library.all() if not r.get("hidden")]
        enabled = sum(r["enabled"] for r in recs)
        attention = sum(1 for r in recs if r["enabled"] and getattr(self.app.engine.status.get(r["id"]), "state", "") in ATTENTION)
        txt = f"{len(recs)} jogos · {enabled} com backup"
        if attention:
            txt += f" · {attention} pendente(s)"
        self.count_lbl.setText(txt + "   ")
        self.app.update_tray()

    def _update_drive(self):
        state = self.app.engine.drive_state()
        email = self.app.engine.drive.email
        self.drive_lbl.setText(f"Google Drive: {email}" if state == "connected" else
                               {"offline": "Google Drive: sem internet", "auth": "Google Drive: login expirado",
                                "connecting": "Google Drive: conectando…"}
                               .get(state, "Google Drive: não conectado"))
        banners = {
            "nocreds": ("Conecte seu Google Drive para começar a fazer backup dos saves.", "Conectar Google Drive", "banner"),
            "notconnected": ("Conecte seu Google Drive para começar a fazer backup dos saves.", "Conectar Google Drive", "banner"),
            "auth": ("O login do Google Drive expirou. Conecte de novo para continuar os backups.", "Conectar de novo", "bannerWarn"),
            "offline": ("Sem conexão com o Google Drive. Os saves serão verificados quando a internet voltar.", "Tentar de novo", "bannerWarn"),
        }
        info = banners.get(state)
        self.banner_wrap.setVisible(info is not None)
        if info:
            self.banner_text.setText(info[0])
            self.banner_btn.setText(info[1])
            self.banner.setObjectName(info[2])
            self.banner.style().unpolish(self.banner)
            self.banner.style().polish(self.banner)
        self._banner_state = state
        self.app.update_tray()

    def _banner_action(self):
        state = getattr(self, "_banner_state", "")
        eng = self.app.engine
        if state == "offline":
            eng.submit("Conectando…", eng.refresh_and_check, "manual")
        elif state in ("auth", "notconnected") and eng.drive.has_credentials_file():
            # já existe credencial (do usuário ou embutida): abre direto o login do Google no navegador
            eng.submit("Aguardando autorização no navegador…", eng.connect_and_check)
        else:
            DriveSetupDialog(self.app, self).exec()

    # ------------------------------------------------------------ ações

    def _scan_all(self):
        eng = self.app.engine
        eng.submit("Procurando jogos…", eng.scan, True)
        eng.submit("Verificando…", eng.check, "manual")
        eng.submit("Atualizando observador…", eng.rebuild_watches)

    def _scan_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta onde você guarda jogos")
        if not folder:
            return
        folders = list(dict.fromkeys((self.app.settings.get("scan_folders") or []) + [folder.replace("/", "\\")]))
        self.app.settings.set("scan_folders", folders)
        self._scan_all()

    def closeEvent(self, event):
        if self.app.quitting:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.app.settings.get("tray_hint_shown"):
            self.app.settings.set("tray_hint_shown", True)
            self.app.tray.showMessage("SaveSync continua rodando",
                                      "Os backups continuam automáticos. Clique no ícone perto do relógio para abrir.",
                                      app_icon(), 5000)

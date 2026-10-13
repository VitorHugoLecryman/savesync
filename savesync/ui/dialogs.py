"""Janelas: detalhes do jogo, confirmação de saves, configurações, adicionar jogo e Google Drive."""
import json
import os
import shutil
import subprocess
from datetime import datetime

from PySide6.QtCore import QStringListModel, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import autostart
from ..config import APP_DIR, open_log
from ..drive import BUNDLED_CREDENTIALS, CREDENTIALS_PATH, credentials_path
from .theme import STATE_INFO, STORE_NAMES, placeholder_cover, rounded_cover
from .widgets import NeonSwitch


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def fmt_time(ts):
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts)
    today = datetime.now().date()
    if dt.date() == today:
        return f"hoje às {dt:%H:%M}"
    if (today - dt.date()).days == 1:
        return f"ontem às {dt:%H:%M}"
    return f"{dt:%d/%m/%Y %H:%M}"


def muted(text, wrap=True):
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(wrap)
    return lbl


def manifest_completer(app, parent):
    model = QStringListModel(sorted(app.engine.manifest.games.keys(), key=str.lower), parent)
    comp = QCompleter(model, parent)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    comp.setMaxVisibleItems(12)
    return comp


# ====================================================================== detalhes do jogo

class DetailsDialog(QDialog):
    def __init__(self, app, gid, parent=None):
        super().__init__(parent)
        self.app, self.gid = app, gid
        self.setWindowTitle("Detalhes do jogo")
        self.resize(760, 560)
        rec = app.library.get(gid)

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.setSpacing(18)
        self.cover = QLabel()
        self.cover.setFixedSize(140, 210)
        top.addWidget(self.cover, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(6)
        self.title = QLabel()
        self.title.setObjectName("h2")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.store = muted("")
        info.addWidget(self.store)
        self.state_lbl = QLabel()
        info.addWidget(self.state_lbl)
        self.local_lbl = QLabel()
        self.remote_lbl = QLabel()
        self.sync_lbl = muted("")
        self.hint_lbl = muted("")
        for w in (self.local_lbl, self.remote_lbl, self.sync_lbl, self.hint_lbl):
            w.setWordWrap(True)
            info.addWidget(w)
        self.enabled = NeonSwitch("Backup automático (enviar sempre que o save mudar)")
        self.enabled.setChecked(rec["enabled"])
        self.enabled.toggled.connect(lambda on: self.app.engine.set_enabled(self.gid, on))
        info.addWidget(self.enabled)
        info.addStretch()
        top.addLayout(info, 1)
        root.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Arquivo de save", "Tamanho", "Modificado"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda item: self._open_folder(item.data(0, Qt.UserRole)))
        root.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.btn_up = QPushButton("↑  Enviar agora")
        self.btn_up.clicked.connect(self._upload)
        self.btn_down = QPushButton("↓  Baixar da nuvem")
        self.btn_down.clicked.connect(self._download)
        btn_folder = QPushButton("Abrir pasta do save")
        btn_folder.clicked.connect(lambda: self._open_folder(None))
        btn_add = QPushButton("+ Pasta de save…")
        btn_add.setToolTip("Use quando o programa não achar o save sozinho")
        btn_add.clicked.connect(self._add_path)
        more = QPushButton("Mais ▾")
        menu = QMenu(more)
        menu.addAction("Definir pasta de instalação do jogo…", self._set_install_dir)
        menu.addAction("Escolher o jogo no banco de dados…", self._pick_manifest)
        menu.addAction("Limpar pastas de save adicionadas", self._clear_paths)
        menu.addSeparator()
        menu.addAction("Abrir backups locais", lambda: self._open_path(APP_DIR / "backups_locais"))
        menu.addAction("Ocultar este jogo", self._hide)
        if rec["store"] in ("manual", "found"):
            menu.addAction("Remover da lista", self._remove)
        more.setMenu(menu)
        for b in (self.btn_up, self.btn_down, btn_folder, btn_add):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(more)
        root.addLayout(buttons)

        app.bridge.status_changed.connect(self._on_status)
        app.bridge.cover_ready.connect(self._on_status)
        self.refresh()
        app.engine.submit("Lendo save…", app.engine.compute_status, gid)

    def _on_status(self, gid):
        if gid == self.gid:
            self.refresh()

    def refresh(self):
        rec = self.app.library.get(self.gid)
        if rec is None:
            self.close()
            return
        st = self.app.engine.status.get(self.gid)
        path = self.app.engine.cover_for(rec)
        dpr = self.devicePixelRatioF()
        pm = QPixmap(path) if path else None
        self.cover.setPixmap(rounded_cover(pm, 140, 210, dpr) if pm and not pm.isNull()
                             else placeholder_cover(rec["name"], 140, 210, dpr))
        self.title.setText(rec["name"])
        store = STORE_NAMES.get(rec["store"], rec["store"])
        if rec.get("install_dir"):
            store += f"  ·  {rec['install_dir']}"
        if rec.get("manifest_name") and rec["manifest_name"] != rec["name"]:
            store += f"\nNo banco de dados: {rec['manifest_name']}"
        self.store.setText(store)
        state = st.state if st else "unknown"
        symbol, color, text = STATE_INFO.get(state, STATE_INFO["unknown"])
        if st and st.message:
            text += f" — {st.message}"
        self.state_lbl.setText(f'<span style="color:{color}; font-weight:600">{symbol}  {text}</span>')

        files = st.files if st else []
        if files:
            self.local_lbl.setText(f"<b>Neste PC:</b> {len(files)} arquivo(s), {fmt_size(st.local_size)}, "
                                   f"modificado {fmt_time(st.local_mtime)}")
        else:
            self.local_lbl.setText("<b>Neste PC:</b> nenhum arquivo de save encontrado")
        if st and st.remote:
            r = st.remote
            self.remote_lbl.setText(f"<b>No Google Drive:</b> {fmt_size(r.size)} (compactado), "
                                    f"enviado {fmt_time(r.saved_at)} pelo PC {r.machine}")
        elif self.app.engine.remote_ok:
            self.remote_lbl.setText("<b>No Google Drive:</b> ainda não enviado")
        else:
            self.remote_lbl.setText("<b>No Google Drive:</b> sem conexão")
        last = rec["sync"].get("last_sync")
        self.sync_lbl.setText(f"Última sincronização neste PC: {fmt_time(last)}" if last else "")
        hints = []
        if not rec.get("manifest_name") and not rec["custom_paths"]:
            hints.append("Este jogo não está no banco de dados de saves. Use “+ Pasta de save…” para indicar onde ele salva.")
        clouds = self.app.engine.manifest.cloud(rec.get("manifest_name"))
        if rec["store"] in clouds:
            hints.append(f"ℹ Este jogo já tem nuvem própria na {STORE_NAMES.get(rec['store'], rec['store'])}.")
        self.hint_lbl.setText("\n".join(hints))
        self.hint_lbl.setVisible(bool(hints))
        self.enabled.blockSignals(True)
        self.enabled.setChecked(rec["enabled"])
        self.enabled.blockSignals(False)

        self.tree.clear()
        for f in files[:2000]:
            item = QTreeWidgetItem([f.path, fmt_size(f.size), fmt_time(f.mtime)])
            item.setData(0, Qt.UserRole, f.path)
            item.setToolTip(0, f.path)
            self.tree.addTopLevelItem(item)
        busy = state == "busy"
        self.btn_up.setEnabled(bool(files) and self.app.engine.remote_ok and not busy)
        self.btn_down.setEnabled(bool(st and st.remote) and not busy)

    def _confirm_overwrite(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes

    def _upload(self):
        st = self.app.engine.status.get(self.gid)
        if st and st.state in ("conflict", "download") and not self._confirm_overwrite(
                "Substituir save da nuvem?",
                "O save na nuvem é diferente e pode ser mais novo. Enviar o save deste PC vai substituí-lo.\n\n"
                "Continuar? (o Drive guarda a versão anterior por 30 dias)"):
            return
        self.app.engine.submit("Enviando…", self.app.engine.upload, self.gid, True)

    def _download(self):
        st = self.app.engine.status.get(self.gid)
        if st and st.files and not self._confirm_overwrite(
                "Substituir save deste PC?",
                "O save deste PC será substituído pelo da nuvem.\n\n"
                "Uma cópia do save atual será guardada em “backups locais” antes. Continuar?"):
            return
        self.app.engine.submit("Baixando…", self.app.engine.download, self.gid)

    def _open_path(self, path):
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self, path):
        st = self.app.engine.status.get(self.gid)
        if path is None and st and st.files:
            path = st.files[0].path
        if path:
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            QMessageBox.information(self, "Sem save", "Nenhum arquivo de save foi encontrado para este jogo.")

    def _changed(self):
        self.app.library.save()
        self.app.engine.submit("Lendo save…", self.app.engine.compute_status, self.gid)
        self.app.engine.submit("Atualizando observador…", self.app.engine.rebuild_watches)
        self.refresh()

    def _add_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Escolha a pasta onde o jogo guarda o save")
        if folder:
            rec = self.app.library.get(self.gid)
            rec["custom_paths"] = list(dict.fromkeys(rec["custom_paths"] + [os.path.normpath(folder)]))
            self._changed()

    def _clear_paths(self):
        self.app.library.get(self.gid)["custom_paths"] = []
        self._changed()

    def _set_install_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Escolha a pasta de instalação do jogo")
        if folder:
            self.app.library.get(self.gid)["install_dir"] = os.path.normpath(folder)
            self._changed()

    def _pick_manifest(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Escolher jogo no banco de dados")
        lay = QVBoxLayout(dlg)
        lay.addWidget(muted("Digite o nome do jogo. O banco diz onde cada jogo guarda o save."))
        edit = QLineEdit(self.app.library.get(self.gid).get("manifest_name") or "")
        edit.setCompleter(manifest_completer(self.app, edit))
        lay.addWidget(edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(420, 120)
        if dlg.exec() == QDialog.Accepted:
            hit = self.app.engine.manifest.find(edit.text().strip())
            if not hit:
                QMessageBox.warning(self, "Não encontrado", "Esse nome não está no banco de dados.")
                return
            self.app.library.update(self.gid, save=False, manifest_name=hit, manifest_locked=True)
            self._changed()

    def _hide(self):
        self.app.library.update(self.gid, hidden=True, enabled=False)
        self.app.bridge.library_changed.emit()
        self.app.engine.submit("Atualizando observador…", self.app.engine.rebuild_watches)
        self.close()

    def _remove(self):
        if self._confirm_overwrite("Remover jogo", "Remover este jogo da lista? (o save na nuvem não é apagado)"):
            self.app.library.remove(self.gid)
            self.app.bridge.library_changed.emit()
            self.app.engine.submit("Atualizando observador…", self.app.engine.rebuild_watches)
            self.close()


# ====================================================================== confirmação

class ConfirmDialog(QDialog):
    """Lista os saves desatualizados para o usuário confirmar o que enviar/baixar."""

    def __init__(self, app, gids, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("SaveSync — saves para sincronizar")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(720, min(180 + 82 * len(gids), 640))
        self.rows = []

        root = QVBoxLayout(self)
        head = QLabel(f"{len(gids)} save(s) precisam de atenção")
        head.setObjectName("h2")
        root.addWidget(head)
        root.addWidget(muted("Confira e confirme. Nada é enviado nem substituído sem a sua confirmação."))

        body = QWidget()
        body.setObjectName("grid")
        body.setAttribute(Qt.WA_StyledBackground, True)
        grid = QGridLayout(body)
        grid.setColumnStretch(2, 1)
        grid.setVerticalSpacing(10)
        dpr = self.devicePixelRatioF()
        for row, gid in enumerate(gids):
            rec = app.library.get(gid)
            st = app.engine.status.get(gid)
            if not rec or not st:
                continue
            check = QCheckBox()
            check.setObjectName("plain")
            check.setChecked(True)
            grid.addWidget(check, row, 0)

            thumb = QLabel()
            path = app.engine.cover_for(rec)
            pm = QPixmap(path) if path else None
            thumb.setPixmap(rounded_cover(pm, 44, 66, dpr) if pm and not pm.isNull()
                            else placeholder_cover(rec["name"], 44, 66, dpr))
            grid.addWidget(thumb, row, 1)

            symbol, color, text = STATE_INFO[st.state]
            local_t, remote = fmt_time(st.local_mtime), st.remote
            remote_t = f"{fmt_time(remote.saved_at)} (PC {remote.machine})" if remote else ""
            box = QVBoxLayout()
            box.setSpacing(2)
            name = QLabel(f"<b>{rec['name']}</b>")
            box.addWidget(name)
            status = QLabel(f'<span style="color:{color}">{symbol} {text}</span>')
            box.addWidget(status)
            choice = None
            if st.state == "upload":
                box.addWidget(muted(f"Enviar o save deste PC (modificado {local_t})"
                                    + (f" · nuvem: {remote_t}" if remote else " · ainda não existe na nuvem")))
                action = "upload"
            elif st.state == "download":
                box.addWidget(muted(f"Baixar o save da nuvem, de {remote_t}"
                                    + (f" · este PC: {local_t}" if st.files else " · não há save neste PC")))
                action = "download"
            else:
                action = None
                choice = QComboBox()
                local_newer = st.local_mtime >= (remote.saved_at if remote else 0)
                choice.addItem(f"Manter o deste PC (modificado {local_t}) e enviar", "upload")
                choice.addItem(f"Manter o da nuvem ({remote_t}) e baixar", "download")
                choice.setCurrentIndex(0 if local_newer else 1)
                box.addWidget(choice)
            wrap = QWidget()
            wrap.setLayout(box)
            grid.addWidget(wrap, row, 2)
            self.rows.append((gid, check, action, choice))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        later = QPushButton("Agora não")
        later.clicked.connect(self.reject)
        ok = QPushButton("Confirmar")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(later)
        btns.addWidget(ok)
        root.addLayout(btns)

    def actions(self):
        out = []
        for gid, check, action, choice in self.rows:
            if check.isChecked():
                out.append((gid, action or choice.currentData()))
        return out


# ====================================================================== adicionar jogo

class AddGameDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Adicionar jogo")
        self.resize(520, 260)
        lay = QVBoxLayout(self)
        lay.addWidget(muted("Para jogos sem launcher, piratas, emuladores… Digite o nome: se ele estiver no "
                            "banco de dados, o programa já sabe onde fica o save. Se não, escolha a pasta do save."))
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Ex.: Hollow Knight")
        self.name.setCompleter(manifest_completer(app, self.name))
        self.name.textChanged.connect(self._update_hint)
        form.addRow("Nome do jogo", self.name)
        self.install = self._path_row(form, "Pasta do jogo (opcional)")
        self.save_dir = self._path_row(form, "Pasta do save (opcional)")
        lay.addLayout(form)
        self.hint = muted("")
        lay.addWidget(self.hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Adicionar")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _path_row(self, form, label):
        row = QHBoxLayout()
        edit = QLineEdit()
        btn = QPushButton("Procurar…")

        def browse():
            folder = QFileDialog.getExistingDirectory(self, label)
            if folder:
                edit.setText(os.path.normpath(folder))

        btn.clicked.connect(browse)
        row.addWidget(edit, 1)
        row.addWidget(btn)
        form.addRow(label, row)
        return edit

    def _update_hint(self, text):
        hit = self.app.engine.manifest.find(text.strip()) if text.strip() else None
        self.hint.setText("✓ Jogo encontrado no banco de dados: o local do save é conhecido." if hit
                          else "Jogo não está no banco: informe a pasta do save." if text.strip() else "")

    def _accept(self):
        name = self.name.text().strip()
        save_dir = self.save_dir.text().strip()
        install = self.install.text().strip()
        if not name:
            return
        if not self.app.engine.manifest.find(name) and not save_dir:
            QMessageBox.warning(self, "Falta a pasta do save",
                                "Esse jogo não está no banco de dados. Escolha a pasta onde ele guarda o save.")
            return
        self.app.engine.add_manual(name, install, save_dir)
        self.accept()


# ====================================================================== Google Drive

class DriveSetupDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Conectar ao Google Drive")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        title = QLabel("Conectar ao Google Drive")
        title.setObjectName("h2")
        lay.addWidget(title)
        steps = QLabel(
            "<p>O Google exige que cada pessoa crie uma “chave” gratuita para programas próprios. "
            "Isso é feito <b>uma única vez</b> (uns 10 minutos):</p>"
            "<ol style='margin-left:-20px'>"
            "<li>Clique em <b>Abrir Google Cloud Console</b> e crie um projeto (ex.: <i>SaveSync</i>).</li>"
            "<li>Em <b>APIs e serviços → Biblioteca</b>, procure <b>Google Drive API</b> e clique em <b>Ativar</b>.</li>"
            "<li>Em <b>Google Auth Platform</b> (tela de permissão OAuth), clique em <b>Começar</b>: "
            "nome do app <i>SaveSync</i>, seu e-mail, público <b>Externo</b>.</li>"
            "<li>Em <b>Público-alvo</b>, clique em <b>Publicar app</b>. "
            "<span style='color:#d29922'>Importante: se ficar “em teste”, o login expira a cada 7 dias.</span></li>"
            "<li>Em <b>Clientes → Criar cliente</b>, escolha <b>App para computador</b>, crie e clique em "
            "<b>Baixar JSON</b>.</li>"
            "<li>Aqui embaixo, clique em <b>Selecionar credentials.json</b> e depois em <b>Conectar</b>. "
            "O navegador vai abrir para você autorizar. Se aparecer “o Google não verificou este app”, clique em "
            "<b>Avançado → Acessar SaveSync</b> (o app é seu).</li></ol>"
            "<p style='color:#8b93a1'>O SaveSync só consegue ver os arquivos que ele mesmo cria no seu Drive "
            "(pasta <b>SaveSync</b>). Nada mais do seu Drive fica acessível.</p>")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        lay.addWidget(steps)
        self.creds_lbl = QLabel()
        lay.addWidget(self.creds_lbl)
        lay.addStretch()
        row = QHBoxLayout()
        console = QPushButton("Abrir Google Cloud Console")
        console.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://console.cloud.google.com/apis/library/drive.googleapis.com")))
        pick = QPushButton("Selecionar credentials.json…")
        pick.clicked.connect(self._pick)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self._connect)
        row.addWidget(console)
        row.addWidget(pick)
        row.addStretch()
        row.addWidget(self.connect_btn)
        lay.addLayout(row)
        self._refresh()

    def _refresh(self):
        path = credentials_path()
        ok = path is not None
        if path == BUNDLED_CREDENTIALS:
            text = ('<span style="color:#34f5a0">✓ Credencial já incluída no programa: é só clicar em '
                    '<b>Conectar</b> e entrar com a sua conta Google.</span>')
        elif ok:
            text = '<span style="color:#34f5a0">✓ credentials.json instalado</span>'
        else:
            text = '<span style="color:#8b93a1">credentials.json ainda não selecionado</span>'
        self.creds_lbl.setText(text)
        self.connect_btn.setEnabled(ok)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecione o arquivo baixado do Google Cloud", "",
                                              "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            QMessageBox.warning(self, "Arquivo inválido", "Não consegui ler esse arquivo JSON.")
            return
        if "installed" not in data:
            QMessageBox.warning(self, "Tipo errado",
                                "Esse arquivo não é de um cliente do tipo “App para computador”. "
                                "Crie um cliente desse tipo e baixe o JSON de novo.")
            return
        APP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, CREDENTIALS_PATH)
        self._refresh()

    def _connect(self):
        self.app.engine.submit("Aguardando autorização no navegador…", self.app.engine.connect_and_check)
        self.accept()


# ====================================================================== configurações

class SettingsDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        s = app.settings
        self.setWindowTitle("Configurações")
        self.resize(560, 620)
        lay = QVBoxLayout(self)

        general = QGroupBox("Geral")
        form = QFormLayout(general)
        self.autostart = QCheckBox("Abrir o SaveSync quando o Windows iniciar")
        self.autostart.setObjectName("plain")
        self.autostart.setChecked(autostart.is_enabled())
        form.addRow(self.autostart)
        self.include_config = QCheckBox("Incluir arquivos de configuração (gráficos, controles) além dos saves")
        self.include_config.setObjectName("plain")
        self.include_config.setChecked(s.get("include_config"))
        form.addRow(self.include_config)
        self.debounce = self._spin(5, 600, s.get("debounce_seconds"), " s")
        form.addRow("Esperar depois do jogo salvar", self.debounce)
        self.max_mb = self._spin(10, 20480, s.get("max_save_mb"), " MB")
        form.addRow("Tamanho máximo por jogo", self.max_mb)
        self.keep = self._spin(1, 50, s.get("local_backups_keep"), "")
        form.addRow("Cópias locais antes de substituir", self.keep)
        lay.addWidget(general)

        drive = QGroupBox("Google Drive")
        dl = QVBoxLayout(drive)
        self.drive_lbl = QLabel()
        dl.addWidget(self.drive_lbl)
        row = QHBoxLayout()
        setup = QPushButton("Configurar / conectar…")
        setup.clicked.connect(lambda: DriveSetupDialog(self.app, self).exec())
        self.disc = QPushButton("Desconectar")
        self.disc.setObjectName("danger")
        self.disc.clicked.connect(self._disconnect)
        row.addWidget(setup)
        row.addWidget(self.disc)
        row.addStretch()
        dl.addLayout(row)
        lay.addWidget(drive)

        folders = QGroupBox("Pastas extras para procurar jogos")
        fl = QVBoxLayout(folders)
        fl.addWidget(muted("Todos os discos já são varridos (até 3 níveis). Adicione pastas onde você guarda "
                           "jogos mais fundo, ex.: D:\\Coisas\\Jogos\\PC"))
        self.folders = QListWidget()
        self.folders.addItems(s.get("scan_folders") or [])
        self.folders.setMaximumHeight(90)
        fl.addWidget(self.folders)
        frow = QHBoxLayout()
        add = QPushButton("Adicionar…")
        add.clicked.connect(self._add_folder)
        rem = QPushButton("Remover")
        rem.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i)) for i in self.folders.selectedItems()])
        frow.addWidget(add)
        frow.addWidget(rem)
        frow.addStretch()
        fl.addLayout(frow)
        lay.addWidget(folders)

        extra = QGroupBox("Capas e banco de dados")
        el = QFormLayout(extra)
        self.sgdb = QLineEdit(s.get("steamgriddb_key"))
        self.sgdb.setPlaceholderText("opcional: capas para jogos fora da Steam")
        self.sgdb.setEchoMode(QLineEdit.Password)
        el.addRow("Chave SteamGridDB", self.sgdb)
        brow = QHBoxLayout()
        upd = QPushButton("Atualizar banco de saves agora")
        upd.clicked.connect(lambda: self.app.engine.submit("Atualizando banco…", self.app.engine.ensure_manifest, True))
        data = QPushButton("Abrir pasta de dados")
        data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_DIR))))
        log_btn = QPushButton("Abrir log")
        log_btn.setToolTip("Registro do que o SaveSync fez e dos erros (útil para diagnosticar problemas)")
        log_btn.clicked.connect(open_log)
        brow.addWidget(upd)
        brow.addWidget(data)
        brow.addWidget(log_btn)
        brow.addStretch()
        el.addRow(brow)
        lay.addWidget(extra)

        lay.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Salvar")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        app.bridge.drive_changed.connect(self._refresh_drive)
        self._refresh_drive()

    def _spin(self, lo, hi, value, suffix):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(int(value))
        sp.setSuffix(suffix)
        return sp

    def _refresh_drive(self):
        state = self.app.engine.drive_state()
        email = self.app.engine.drive.email
        texts = {
            "connected": f'<span style="color:#3fb950">✓ Conectado</span> {email or ""}',
            "nocreds": "Não configurado",
            "notconnected": "Não conectado",
            "auth": '<span style="color:#d29922">O login expirou, conecte de novo</span>',
            "offline": '<span style="color:#8b93a1">Sem internet no momento</span>',
        }
        self.drive_lbl.setText(texts.get(state, state))
        self.disc.setEnabled(self.app.engine.drive.has_token())

    def _disconnect(self):
        self.app.engine.submit("Desconectando…", self.app.engine.disconnect_drive)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta com jogos")
        if folder:
            self.folders.addItem(os.path.normpath(folder))

    def _save(self):
        s = self.app.settings
        old_config = s.get("include_config")
        s.update({
            "autostart": self.autostart.isChecked(),
            "include_config": self.include_config.isChecked(),
            "debounce_seconds": self.debounce.value(),
            "max_save_mb": self.max_mb.value(),
            "local_backups_keep": self.keep.value(),
            "scan_folders": [self.folders.item(i).text() for i in range(self.folders.count())],
            "steamgriddb_key": self.sgdb.text().strip(),
        })
        try:
            autostart.set_enabled(self.autostart.isChecked())
        except OSError as e:
            QMessageBox.warning(self, "Inicialização", f"Não consegui alterar a inicialização automática: {e}")
        if old_config != s.get("include_config"):
            self.app.engine.submit("Verificando saves…", self.app.engine.check, "manual")
            self.app.engine.submit("Atualizando observador…", self.app.engine.rebuild_watches)
        self.accept()

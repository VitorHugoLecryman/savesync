"""Visual sci-fi: cores neon, estilo (QSS), logotipo e capas geradas."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)

BG = "#060a18"
BG_2 = "#0b1430"
SURFACE = "#0d1530"
SURFACE_2 = "#121d3d"
BORDER = "#1f2f5a"
TEXT = "#e6efff"
MUTED = "#7d8bb5"
CYAN = "#22d3ee"
VIOLET = "#8b5cf6"
PINK = "#ec4899"
ACCENT = CYAN

# estado -> (símbolo, cor neon, texto)
STATE_INFO = {
    "synced": ("✓", "#34f5a0", "Sincronizado"),
    "upload": ("↑", "#fbbf24", "Save novo para enviar"),
    "download": ("↓", "#38bdf8", "A nuvem tem um save mais novo"),
    "conflict": ("!", "#fb4778", "Conflito: os dois mudaram"),
    "nosave": ("–", "#3b4a73", "Nenhum save encontrado"),
    "local": ("●", "#7d8bb5", "Save encontrado"),
    "offline": ("?", "#7d8bb5", "Sem conexão com o Drive"),
    "toobig": ("!", "#fbbf24", "Save grande demais"),
    "busy": ("⟳", CYAN, "Sincronizando…"),
    "error": ("!", "#fb4778", "Erro ao ler o save"),
    "unknown": ("…", "#3b4a73", "Verificando…"),
}

STORE_NAMES = {
    "steam": "Steam", "epic": "Epic Games", "gog": "GOG", "uplay": "Ubisoft",
    "folder": "Pasta no disco", "rpcs3": "RPCS3 · PS3", "found": "Achado pelo save", "manual": "Adicionado por você",
}

GRAD_H = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {VIOLET})"
GRAD_H_HOVER = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #67e8f9, stop:1 #a78bfa)"

STYLESHEET = f"""
* {{ font-family: "Segoe UI"; font-size: 10pt; color: {TEXT}; }}
QMainWindow {{ background: {BG}; }}
QDialog {{ background: qlineargradient(x1:0, y1:0, x2:0.4, y2:1, stop:0 {BG_2}, stop:1 {BG}); }}
QWidget#grid, QWidget#transparent {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; }}

QFrame#topbar {{ background: rgba(6, 10, 26, 0.88); border: none; }}
QLabel#muted, QLabel.muted {{ color: {MUTED}; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 600; color: #f0f6ff; }}
QFrame#banner {{ background: rgba(34, 211, 238, 0.07); border: 1px solid rgba(34, 211, 238, 0.40); border-radius: 10px; }}
QFrame#bannerWarn {{ background: rgba(251, 191, 36, 0.07); border: 1px solid rgba(251, 191, 36, 0.40); border-radius: 10px; }}

QLineEdit, QComboBox, QSpinBox {{
    background: rgba(13, 21, 48, 0.85); border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: rgba(34, 211, 238, 0.45);
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #2c4380; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {CYAN}; background: rgba(13, 24, 56, 0.95); }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid #26396b; outline: none;
    selection-background-color: rgba(34, 211, 238, 0.25); selection-color: white; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QSpinBox::up-button, QSpinBox::down-button {{ background: transparent; border: none; width: 16px; }}

QPushButton {{
    background: rgba(18, 29, 61, 0.85); border: 1px solid #26396b; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {CYAN}; color: #c9f7ff; background: rgba(22, 40, 84, 0.9); }}
QPushButton:pressed {{ background: #0c1633; }}
QPushButton:disabled {{ color: #4a5880; border-color: #1a2850; }}
QPushButton#primary {{ background: {GRAD_H}; border: none; color: white; font-weight: 600; padding: 8px 16px; }}
QPushButton#primary:hover {{ background: {GRAD_H_HOVER}; }}
QPushButton#primary:pressed {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5c4, stop:1 #6d40d9); }}
QPushButton#primary:disabled {{ background: rgba(18, 29, 61, 0.85); border: 1px solid #1a2850; color: #4a5880; font-weight: 400; }}
QPushButton#danger:hover {{ border-color: #fb4778; color: #ffc2d1; }}
QPushButton::menu-indicator {{ width: 0; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox#plain::indicator {{ width: 16px; height: 16px; border-radius: 4px; background: rgba(13, 21, 48, 0.9); border: 1px solid #2c4380; }}
QCheckBox#plain::indicator:hover {{ border-color: {CYAN}; }}
QCheckBox#plain::indicator:checked {{ background: {GRAD_H}; border: 1px solid {CYAN}; }}

QTreeWidget, QTableWidget, QListWidget {{
    background: rgba(10, 17, 40, 0.85); border: 1px solid {BORDER}; border-radius: 8px;
    alternate-background-color: rgba(18, 29, 61, 0.75); outline: none;
    selection-background-color: rgba(34, 211, 238, 0.22); selection-color: white;
}}
QHeaderView::section {{ background: #0f1938; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; color: {MUTED}; }}
QStatusBar {{ background: rgba(6, 10, 24, 0.95); border-top: 1px solid #16234a; color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; }}
QStatusBar::item {{ border: none; }}
QMenu {{ background: {SURFACE}; border: 1px solid #26396b; padding: 5px; border-radius: 8px; }}
QMenu::item {{ padding: 7px 20px; border-radius: 6px; }}
QMenu::item:selected {{ background: {GRAD_H}; color: white; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {CYAN}; padding: 5px; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
QScrollBar::handle:vertical {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(34,211,238,0.35), stop:1 rgba(139,92,246,0.35)); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {CYAN}, stop:1 {VIOLET}); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: transparent; }}
QGroupBox {{ border: 1px solid rgba(34, 211, 238, 0.22); border-radius: 10px; margin-top: 14px; padding: 10px;
    background: rgba(13, 21, 48, 0.45); }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {CYAN}; }}
"""


# ---------------------------------------------------------------- logotipo neon

def app_icon(state=None) -> QIcon:
    """Nuvem digital em neon. 'state' acrescenta um ponto colorido (ícone da bandeja)."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(size, state))
    return icon


def _cloud_path(s):
    cloud = QPainterPath()
    cloud.addEllipse(QRectF(11 * s, 27 * s, 18 * s, 18 * s))
    cloud.addEllipse(QRectF(21 * s, 16 * s, 23 * s, 23 * s))
    cloud.addEllipse(QRectF(35 * s, 26 * s, 18 * s, 18 * s))
    cloud.addRoundedRect(QRectF(16 * s, 33 * s, 32 * s, 12 * s), 5 * s, 5 * s)
    return cloud.simplified()


def _icon_pixmap(size, state=None):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    small = size <= 24

    bg = QLinearGradient(0, 0, 0, size)
    bg.setColorAt(0, QColor("#101c42"))
    bg.setColorAt(1, QColor("#050916"))
    edge = QLinearGradient(0, 0, size, size)
    edge.setColorAt(0, QColor(CYAN))
    edge.setColorAt(1, QColor(VIOLET))
    p.setBrush(bg)
    p.setPen(QPen(edge, max(1.0, 2.2 * s)))
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)

    cloud = _cloud_path(s)
    neon = QLinearGradient(10 * s, 0, 54 * s, 0)
    neon.setColorAt(0, QColor(CYAN))
    neon.setColorAt(1, QColor(VIOLET))
    if small:
        p.setPen(Qt.NoPen)
        p.setBrush(neon)
        p.drawPath(cloud)
    else:
        # brilho: traços largos e transparentes por baixo do traço fino
        for width, alpha in ((9, 35), (6, 60), (3.5, 120)):
            glow = QColor(CYAN)
            glow.setAlpha(alpha)
            p.setPen(QPen(glow, width * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(cloud)
        fill = QColor(CYAN)
        fill.setAlpha(28)
        p.setBrush(fill)
        p.setPen(QPen(neon, 2.2 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(cloud)
        # "pacotes de dados" saindo da nuvem
        p.setPen(Qt.NoPen)
        for x, y, r, a in ((47, 15, 2.2, 230), (53, 10, 1.6, 170), (57, 17, 1.2, 120)):
            c = QColor("#a5f3fc")
            c.setAlpha(a)
            p.setBrush(c)
            p.drawEllipse(QPointF(x * s, y * s), r * s, r * s)

    arrow = QColor("white" if small else "#e0fbff")
    p.setPen(QPen(arrow, (3.6 if small else 3.0) * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(QPointF(32 * s, 40 * s), QPointF(32 * s, 27.5 * s))
    p.drawLine(QPointF(26.5 * s, 32.5 * s), QPointF(32 * s, 27 * s))
    p.drawLine(QPointF(37.5 * s, 32.5 * s), QPointF(32 * s, 27 * s))

    if state and state in STATE_INFO:
        p.setPen(QPen(QColor(BG), 3 * s))
        p.setBrush(QColor(STATE_INFO[state][1]))
        p.drawEllipse(QRectF(40 * s, 40 * s, 22 * s, 22 * s))
    p.end()
    return pm


# ---------------------------------------------------------------- capas

def placeholder_cover(name: str, w: int, h: int, dpr: float = 1.0) -> QPixmap:
    """Capa gerada para jogos sem imagem: holograma com grade e iniciais em neon."""
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    hue = 190 + sum(ord(c) * (i + 1) for i, c in enumerate(name)) % 90   # entre ciano e violeta
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
    p.setClipPath(path)
    grad = QLinearGradient(0, 0, w * 0.3, h)
    grad.setColorAt(0, QColor.fromHsv(hue, 170, 70))
    grad.setColorAt(1, QColor("#050916"))
    p.fillRect(QRectF(0, 0, w, h), grad)
    line = QColor.fromHsv(hue, 160, 255)
    line.setAlpha(22)
    p.setPen(QPen(line, 1))
    step = max(8, int(w / 9))
    for x in range(0, int(w) + 1, step):
        p.drawLine(QPointF(x, 0), QPointF(x, h))
    for y in range(0, int(h) + 1, step):
        p.drawLine(QPointF(0, y), QPointF(w, y))
    halo = QRadialGradient(QPointF(w / 2, h * 0.38), w * 0.6)
    glow = QColor.fromHsv(hue, 200, 255)
    glow.setAlpha(60)
    halo.setColorAt(0, glow)
    halo.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(0, 0, w, h), halo)

    words = [wd for wd in name.replace(":", " ").split() if wd[:1].isalnum()]
    initials = "".join(wd[0] for wd in words[:2]).upper() or "?"
    f = p.font()
    f.setPointSizeF(max(6.0, h / 7.5))
    f.setBold(True)
    p.setFont(f)
    text_rect = QRectF(0, 0, w, h * 0.72)
    shadow = QColor.fromHsv(hue, 200, 255)
    shadow.setAlpha(90)
    p.setPen(shadow)
    for dx, dy in ((-1.5, 0), (1.5, 0), (0, -1.5), (0, 1.5)):
        p.drawText(text_rect.translated(dx, dy), Qt.AlignCenter, initials)
    p.setPen(QColor("#f0fdff"))
    p.drawText(text_rect, Qt.AlignCenter, initials)
    if h >= 120:
        f.setPointSizeF(h / 26)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(220, 235, 255, 180))
        p.drawText(QRectF(8, h * 0.6, w - 16, h * 0.36), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, name)
    p.end()
    return pm


def rounded_cover(source: QPixmap, w: int, h: int, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    scaled = source.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), 8, 8)
    p.setClipPath(path)
    p.drawPixmap(QPointF((w - scaled.width() / dpr) / 2, (h - scaled.height() / dpr) / 2), scaled)
    # leve escurecimento embaixo para integrar a capa ao cartão
    shade = QLinearGradient(0, h * 0.65, 0, h)
    shade.setColorAt(0, QColor(6, 10, 24, 0))
    shade.setColorAt(1, QColor(6, 10, 24, 120))
    p.fillRect(QRectF(0, 0, w, h), shade)
    p.end()
    return pm

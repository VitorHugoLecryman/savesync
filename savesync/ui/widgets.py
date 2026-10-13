"""Grade de capas (FlowLayout), cartão neon de cada jogo, switch e selo de status."""
from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation,
                            Signal)
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget, QLayout

from .theme import BORDER, CYAN, MUTED, STATE_INFO, STORE_NAMES, TEXT, VIOLET, placeholder_cover, rounded_cover

COVER_W, COVER_H = 140, 210
GLOW = 12                       # margem transparente onde o brilho é desenhado
CARD_W = COVER_W + 20 + 2 * GLOW
CARD_H = COVER_H + 98 + 2 * GLOW
ATTENTION = ("upload", "download", "conflict", "toobig", "error")


class FlowLayout(QLayout):
    """Distribui os cartões em linhas que quebram conforme a largura da janela."""

    def __init__(self, parent=None, spacing=14, max_gap=28):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self._max_gap = max_gap

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, dry):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        visible = [i for i in self._items if not i.isEmpty()]
        if not visible:
            return m.top() + m.bottom()
        item_w = visible[0].sizeHint().width()
        per_row = max(1, (area.width() + self._spacing) // (item_w + self._spacing))
        # espaço que sobra é dividido entre os cartões para a grade ficar alinhada
        gap = self._spacing if per_row == 1 else max(self._spacing, (area.width() - per_row * item_w) // (per_row - 1))
        gap = min(gap, self._max_gap)
        x, y, line_h, col = area.x(), area.y(), 0, 0
        for item in visible:
            hint = item.sizeHint()
            if col == per_row:
                x, y, col = area.x(), y + line_h + self._spacing, 0
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line_h = max(line_h, hint.height())
            col += 1
        return y + line_h - rect.y() + m.bottom()


def _alpha(color, a):
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(a))))
    return c


def paint_neon_frame(p, r, h, glow_a, glow_b, intensity, radius=12):
    """Cartão de vidro escuro com halo e contorno neon (h = 0..1 do mouse em cima)."""
    # halo neon: contornos cada vez maiores e mais transparentes
    if intensity > 0.01:
        for i in range(GLOW, 0, -2):
            fade = (1 - i / (GLOW + 1)) ** 2
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, _alpha(glow_a, 70 * intensity * fade))
            g.setColorAt(1, _alpha(glow_b, 70 * intensity * fade))
            p.setPen(QPen(g, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-i, -i, i, i), radius + i, radius + i)

    # corpo de vidro escuro
    body = QLinearGradient(r.topLeft(), r.bottomLeft())
    body.setColorAt(0, QColor(18, 30, 64, 236))
    body.setColorAt(1, QColor(8, 14, 34, 236))
    p.setPen(Qt.NoPen)
    p.setBrush(body)
    p.drawRoundedRect(r, radius, radius)

    # contorno: gradiente neon quando ativo/selecionado, discreto quando não
    if intensity > 0.01:
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, _alpha(glow_a, 120 + 135 * intensity))
        g.setColorAt(1, _alpha(glow_b, 120 + 135 * intensity))
        pen = QPen(g, 1.4)
    else:
        pen = QPen(QColor(BORDER), 1)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    # reflexo no topo para dar volume
    shine = QPainterPath()
    shine.addRoundedRect(r.adjusted(1.5, 1.5, -1.5, -r.height() * 0.55), radius - 1, radius - 1)
    sg = QLinearGradient(r.topLeft(), QPointF(r.left(), r.top() + r.height() * 0.45))
    sg.setColorAt(0, QColor(255, 255, 255, int(16 + 14 * h)))
    sg.setColorAt(1, QColor(255, 255, 255, 0))
    p.fillPath(shine, sg)


class NeonSwitch(QCheckBox):
    """Switch desenhado à mão: trilho em gradiente com brilho neon quando ligado."""

    TRACK_W, TRACK_H = 26, 14

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_pos)
        self.toggled.connect(self._animate)

    def _set_pos(self, value):
        self._pos = float(value)
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):
        """Mudança vinda do código (não do clique): posiciona sem animar."""
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        text_w = fm.horizontalAdvance(self.text()) + 8 if self.text() else 0
        return QSize(self.TRACK_W + 6 + text_w, max(self.TRACK_H + 6, fm.height() + 4))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._pos
        y = (self.height() - self.TRACK_H) / 2
        track = QRectF(3, y, self.TRACK_W, self.TRACK_H)
        r = self.TRACK_H / 2
        if t > 0.01:   # brilho
            for i, a in ((4, 18), (2.5, 34), (1.2, 60)):
                p.setPen(QPen(_alpha(CYAN, a * t), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(track.adjusted(-i, -i, i, i), r + i, r + i)
        off = QColor("#16224a")
        p.setPen(QPen(_alpha("#2c4380", 255 * (1 - t) + 40), 1))
        p.setBrush(off)
        p.drawRoundedRect(track, r, r)
        if t > 0.01:
            g = QLinearGradient(track.left(), 0, track.right(), 0)
            g.setColorAt(0, _alpha(CYAN, 255 * t))
            g.setColorAt(1, _alpha(VIOLET, 255 * t))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(track, r, r)
        knob_d = self.TRACK_H - 4
        kx = track.left() + 2 + (self.TRACK_W - knob_d - 4) * t
        knob = QRectF(kx, y + 2, knob_d, knob_d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff") if t > 0.5 else QColor("#7d8bb5"))
        p.drawEllipse(knob)
        if self.text():
            p.setPen(QColor(TEXT) if self.isChecked() else QColor(MUTED))
            p.setFont(self.font())
            p.drawText(QRectF(track.right() + 5, 0, self.width(), self.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())


class StatusBadge(QWidget):
    """Selo redondo com brilho na cor do estado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.symbol, self.color = "", QColor(MUTED)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_state(self, symbol, color):
        self.symbol, self.color = symbol, QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(15, 15)
        halo = QRadialGradient(c, 15)
        halo.setColorAt(0.45, _alpha(self.color, 140))
        halo.setColorAt(1, _alpha(self.color, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, 15, 15)
        body = QRadialGradient(QPointF(12, 11), 12)
        body.setColorAt(0, self.color.lighter(135))
        body.setColorAt(1, self.color.darker(115))
        p.setBrush(body)
        p.setPen(QPen(QColor(6, 10, 24, 230), 2))
        p.drawEllipse(c, 10.5, 10.5)
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(10)
        p.setFont(f)
        p.setPen(QColor("#04101f") if self.color.lightness() > 150 else QColor("white"))
        p.drawText(QRectF(4.5, 4.5, 21, 21), Qt.AlignCenter, self.symbol)


class GameCard(QWidget):
    toggled = Signal(str, bool)
    opened = Signal(str)

    def __init__(self, rec, parent=None):
        super().__init__(parent)
        self.gid = rec["id"]
        self.name = rec["name"]
        self.state = "unknown"
        self.enabled = bool(rec["enabled"])
        self._hover = 0.0
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

        self._anim = QVariantAnimation(self, duration=180, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_hover)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(GLOW + 10, GLOW + 10, GLOW + 10, GLOW + 8)
        lay.setSpacing(4)

        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        lay.addWidget(self.cover)

        self.badge = StatusBadge(self.cover)
        self.badge.move(COVER_W - 32, 2)

        self.title = QLabel()
        self.title.setFixedWidth(COVER_W)
        lay.addWidget(self.title)

        self.sub = QLabel()
        self.sub.setStyleSheet(f"color:{MUTED}; font-size:8.5pt;")
        lay.addWidget(self.sub)

        self.toggle = NeonSwitch("Backup automático")
        self.toggle.setStyleSheet("font-size:8.5pt;")
        self.toggle.toggled.connect(self._on_toggle)
        lay.addWidget(self.toggle)

        self.update_record(rec)
        self.set_cover(None)

    # ------------------------------------------------------------ conteúdo

    def _on_toggle(self, on):
        self.enabled = on
        self.update()
        self.toggled.emit(self.gid, on)

    def set_cover(self, path):
        dpr = self.devicePixelRatioF()
        if path:
            pm = QPixmap(path)
            if not pm.isNull():
                self.cover.setPixmap(rounded_cover(pm, COVER_W, COVER_H, dpr))
                return
        self.cover.setPixmap(placeholder_cover(self.name, COVER_W, COVER_H, dpr))

    def update_record(self, rec):
        self.name = rec["name"]
        self.enabled = bool(rec["enabled"])
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(rec["name"], Qt.ElideRight, COVER_W))
        self.setToolTip(rec["name"])
        store = STORE_NAMES.get(rec["store"], rec["store"])
        if not rec.get("installed", True):
            store += " · não instalado"
        self.sub.setText(store)
        self.toggle.blockSignals(True)
        self.toggle.setChecked(self.enabled)
        self.toggle.blockSignals(False)
        self.update()

    def set_state(self, state, enabled):
        self.state = state
        self.enabled = enabled
        symbol, color, text = STATE_INFO.get(state, STATE_INFO["unknown"])
        self.badge.set_state(symbol, color)
        self.badge.setToolTip(text)
        self.badge.setVisible(state != "unknown" and (enabled or state in ("local", "synced", "download")))
        muted = state == "nosave" and not enabled
        self.title.setStyleSheet(f"font-weight:600; color:{MUTED if muted else '#f0f6ff'};")
        self.update()

    # ------------------------------------------------------------ brilho

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _fade(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, event):
        self._fade(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._fade(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(GLOW, GLOW, -GLOW, -GLOW)
        radius = 12
        h = self._hover
        attention = self.enabled and self.state in ATTENTION
        state_color = QColor(STATE_INFO.get(self.state, STATE_INFO["unknown"])[1])

        if attention:
            glow_a, glow_b = state_color, state_color
            intensity = 0.55 + 0.45 * h
        elif self.enabled:
            glow_a, glow_b = QColor(CYAN), QColor(VIOLET)
            intensity = 0.42 + 0.58 * h
        else:
            glow_a, glow_b = QColor(CYAN), QColor(VIOLET)
            intensity = 0.0 + 0.85 * h

        paint_neon_frame(p, r, h, glow_a, glow_b, intensity, radius)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self.toggle.geometry().contains(event.position().toPoint()):
            self.opened.emit(self.gid)
        super().mouseReleaseEvent(event)

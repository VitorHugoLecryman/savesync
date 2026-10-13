"""Efeitos visuais: fundo com rede de dados, linha de fluxo e título em gradiente.

As animações só rodam com a janela visível (param na bandeja/minimizado) e redesenham
apenas pequenos retângulos, para gastar o mínimo de CPU.
"""
import math
import random

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import CYAN, VIOLET


class SciFiBackground(QWidget):
    """Fundo azul profundo com uma rede discreta; 'pacotes' de dados correm pelas ligações."""

    NODES = 42
    PARTICLES = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        rnd = random.Random(42)
        self.nodes = [(rnd.uniform(0.02, 0.98), rnd.uniform(0.04, 0.98)) for _ in range(self.NODES)]
        edges = set()
        for i, (x, y) in enumerate(self.nodes):
            near = sorted(range(self.NODES), key=lambda j: (self.nodes[j][0] - x) ** 2 + (self.nodes[j][1] - y) ** 2)
            for j in near[1:3]:
                edges.add((min(i, j), max(i, j)))
        self.edges = sorted(edges)
        self.particles = [[rnd.randrange(len(self.edges)), rnd.random(), rnd.uniform(0.004, 0.010)]
                          for _ in range(self.PARTICLES)]
        self.busy = False
        self._static = None
        self.timer = QTimer(self, interval=50, timeout=self._tick)

    # ------------------------------------------------------------ controle

    def set_running(self, running):
        if running and not self.timer.isActive():
            self.timer.start()
        elif not running:
            self.timer.stop()

    def set_busy(self, busy):
        self.busy = busy

    def resizeEvent(self, event):
        self._static = None
        super().resizeEvent(event)

    # ------------------------------------------------------------ desenho

    def _pt(self, idx):
        x, y = self.nodes[idx]
        return QPointF(x * self.width(), y * self.height())

    def _render_static(self):
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        base = QLinearGradient(0, 0, w * 0.35, h)
        base.setColorAt(0, QColor("#0a1430"))
        base.setColorAt(0.55, QColor("#060b1d"))
        base.setColorAt(1, QColor("#04070f"))
        p.fillRect(0, 0, w, h, base)
        for cx, cy, radius, color, alpha in ((0.12, 0.05, 0.55, CYAN, 34), (0.92, 0.95, 0.6, VIOLET, 40),
                                             (0.75, 0.2, 0.35, "#3b82f6", 18)):
            g = QRadialGradient(QPointF(cx * w, cy * h), radius * max(w, h))
            c = QColor(color)
            c.setAlpha(alpha)
            g.setColorAt(0, c)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, w, h, g)
        # grade de pontos bem discreta
        dot = QColor(120, 170, 255, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(dot)
        for x in range(0, w, 28):
            for y in range(0, h, 28):
                p.drawEllipse(QPointF(x, y), 0.8, 0.8)
        # rede
        for a, b in self.edges:
            pa, pb = self._pt(a), self._pt(b)
            g = QLinearGradient(pa, pb)
            g.setColorAt(0, QColor(34, 211, 238, 26))
            g.setColorAt(1, QColor(139, 92, 246, 26))
            p.setPen(QPen(g, 1))
            p.drawLine(pa, pb)
        for i in range(self.NODES):
            pt = self._pt(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(34, 211, 238, 18))
            p.drawEllipse(pt, 4, 4)
            p.setBrush(QColor(165, 243, 252, 70))
            p.drawEllipse(pt, 1.4, 1.4)
        p.end()
        self._static = pm

    def _particle_pos(self, part):
        a, b = self.edges[part[0]]
        pa, pb = self._pt(a), self._pt(b)
        t = part[1]
        return QPointF(pa.x() + (pb.x() - pa.x()) * t, pa.y() + (pb.y() - pa.y()) * t), pa, pb

    def paintEvent(self, event):
        if self._static is None or self._static.size() != self.size() * self.devicePixelRatioF():
            self._render_static()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static)
        p.setRenderHint(QPainter.Antialiasing)
        boost = 1.6 if self.busy else 1.0
        for part in self.particles:
            pos, pa, pb = self._particle_pos(part)
            length = math.hypot(pb.x() - pa.x(), pb.y() - pa.y()) or 1
            ux, uy = (pb.x() - pa.x()) / length, (pb.y() - pa.y()) / length
            tail = QPointF(pos.x() - ux * 22, pos.y() - uy * 22)
            g = QLinearGradient(tail, pos)
            g.setColorAt(0, QColor(34, 211, 238, 0))
            g.setColorAt(1, QColor(103, 232, 249, int(150 * boost) if boost > 1 else 140))
            p.setPen(QPen(g, 1.6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(tail, pos)
            halo = QRadialGradient(pos, 7)
            halo.setColorAt(0, QColor(103, 232, 249, int(110 * boost) if boost > 1 else 100))
            halo.setColorAt(1, QColor(34, 211, 238, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(pos, 7, 7)

    def _dirty(self, part):
        pos, pa, pb = self._particle_pos(part)
        return QRect(int(pos.x()) - 30, int(pos.y()) - 30, 60, 60)

    def _tick(self):
        speed = 3.0 if self.busy else 1.0
        for part in self.particles:
            before = self._dirty(part)
            part[1] += part[2] * speed
            if part[1] >= 1.0:
                # chega ao nó e segue por outra ligação que sai dele
                a, b = self.edges[part[0]]
                options = [i for i, e in enumerate(self.edges) if b in e and i != part[0]]
                if options:
                    nxt = random.choice(options)
                    if self.edges[nxt][1] == b:   # orienta a ligação para sair de 'b'
                        self.edges[nxt] = (self.edges[nxt][1], self.edges[nxt][0])
                    part[0] = nxt
                else:
                    part[0] = random.randrange(len(self.edges))
                part[1] = 0.0
                self.update(before)
            self.update(before.united(self._dirty(part)))


class FlowLine(QWidget):
    """Linha em gradiente abaixo da barra do topo; um feixe de luz corre por ela durante a sincronização."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        self.offset = 0.0
        self.busy = False
        self.timer = QTimer(self, interval=30, timeout=self._tick)

    def set_busy(self, busy):
        self.busy = busy
        if busy and self.isVisible():
            self.timer.start()
        elif not busy:
            self.timer.stop()
            self.update()

    def _tick(self):
        self.offset = (self.offset + 0.012) % 1.4
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w = self.width()
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, QColor(34, 211, 238, 140))
        g.setColorAt(0.5, QColor(99, 102, 241, 110))
        g.setColorAt(1, QColor(139, 92, 246, 140))
        p.fillRect(self.rect(), g)
        if self.busy:
            center = (self.offset - 0.2) * w
            beam = QLinearGradient(center - 140, 0, center + 140, 0)
            beam.setColorAt(0, QColor(255, 255, 255, 0))
            beam.setColorAt(0.5, QColor(224, 251, 255, 255))
            beam.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), beam)


class GradientLabel(QWidget):
    """Texto com preenchimento em gradiente ciano → violeta (título do app)."""

    def __init__(self, text, point_size=16, parent=None):
        super().__init__(parent)
        self.text = text
        self.font_ = QFont("Segoe UI", point_size, QFont.DemiBold)
        self.font_.setLetterSpacing(QFont.PercentageSpacing, 103)

    def sizeHint(self):
        fm = QFontMetrics(self.font_)
        return QSize(fm.horizontalAdvance(self.text) + 8, fm.height() + 4)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        fm = QFontMetrics(self.font_)
        y = (self.height() + fm.ascent() - fm.descent()) / 2
        path.addText(2, y, self.font_, self.text)
        rect = path.boundingRect()
        g = QLinearGradient(rect.left(), 0, rect.right(), 0)
        g.setColorAt(0, QColor("#67e8f9"))
        g.setColorAt(1, QColor("#a78bfa"))
        glow = QColor(CYAN)
        glow.setAlpha(45)
        p.setPen(QPen(glow, 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.fillPath(path, g)

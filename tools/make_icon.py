"""Gera o ícone (assets/savesync.ico) e as imagens do instalador a partir do visual do app."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QRadialGradient)

app = QGuiApplication([])
from savesync.ui.theme import CYAN, VIOLET, _icon_pixmap  # noqa: E402

ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")
os.makedirs(ASSETS, exist_ok=True)


def save(img, name):
    path = os.path.join(ASSETS, name)
    ok = img.save(path)
    print(("ok   " if ok else "ERRO ") + os.path.abspath(path))


def wizard_side(scale):
    """Faixa lateral do assistente: fundo azul profundo, rede de dados e o logo neon."""
    w, h = 164 * scale, 314 * scale
    img = QImage(w, h, QImage.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    bg = QLinearGradient(0, 0, w * 0.4, h)
    bg.setColorAt(0, QColor("#0d1a3d"))
    bg.setColorAt(1, QColor("#04070f"))
    p.fillRect(0, 0, w, h, bg)
    for cx, cy, color, alpha in ((0.1, 0.1, CYAN, 70), (0.95, 0.9, VIOLET, 80)):
        g = QRadialGradient(QPointF(cx * w, cy * h), 0.8 * w)
        c = QColor(color)
        c.setAlpha(alpha)
        g.setColorAt(0, c)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, g)
    nodes = [(0.15, 0.62), (0.42, 0.7), (0.78, 0.6), (0.3, 0.85), (0.65, 0.88), (0.9, 0.78), (0.1, 0.95)]
    p.setPen(QColor(34, 211, 238, 60))
    for a, b in ((0, 1), (1, 2), (1, 3), (3, 4), (4, 5), (2, 5), (3, 6)):
        p.drawLine(QPointF(nodes[a][0] * w, nodes[a][1] * h), QPointF(nodes[b][0] * w, nodes[b][1] * h))
    p.setPen(Qt.NoPen)
    for x, y in nodes:
        p.setBrush(QColor(165, 243, 252, 150))
        p.drawEllipse(QPointF(x * w, y * h), 2 * scale, 2 * scale)
    logo = _icon_pixmap(96 * scale).toImage()
    p.drawImage(int((w - logo.width()) / 2), int(48 * scale), logo)
    f = QFont("Segoe UI", 15)
    f.setPixelSize(int(22 * scale))
    f.setBold(True)
    p.setFont(f)
    text = QLinearGradient(0, 0, w, 0)
    text.setColorAt(0, QColor("#67e8f9"))
    text.setColorAt(1, QColor("#a78bfa"))
    p.setPen(QColor("#a5f3fc"))
    p.drawText(QRectF(0, 152 * scale, w, 30 * scale), Qt.AlignCenter, "SaveSync")
    f.setPixelSize(int(11 * scale))
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor(200, 215, 245, 190))
    p.drawText(QRectF(10 * scale, 182 * scale, w - 20 * scale, 40 * scale), Qt.AlignHCenter | Qt.TextWordWrap,
               "Backup de saves de jogos no Google Drive")
    p.end()
    return img


def wizard_small(scale):
    size = 58 * scale
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    logo = _icon_pixmap(int(52 * scale)).toImage()
    p.drawImage(int((size - logo.width()) / 2), int((size - logo.height()) / 2), logo)
    p.end()
    return img


_icon_pixmap(256).toImage().save(os.path.join(ASSETS, "savesync.ico"), "ICO")
print("ok   " + os.path.abspath(os.path.join(ASSETS, "savesync.ico")))
for scale in (1, 2):
    save(wizard_side(scale), f"wizard_side_{scale}x.bmp")
    save(wizard_small(scale), f"wizard_small_{scale}x.bmp")

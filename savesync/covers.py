"""Capas dos jogos: baixadas uma vez, reduzidas para 200x300 em JPEG (~15 KB cada)."""
import hashlib
import logging
import time

import requests
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from .config import COVERS_DIR

log = logging.getLogger(__name__)

W, H = 200, 300
RETRY_AFTER = 7 * 86400  # tenta de novo capas que falharam depois de uma semana

STEAM_PORTRAIT = [
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{id}/library_600x900.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/library_600x900.jpg",
]
STEAM_LANDSCAPE = [
    "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{id}/header.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/header.jpg",
]

_session = requests.Session()
_session.headers["User-Agent"] = "SaveSync/1.0"


def cover_key(steam_id, name):
    return f"steam_{steam_id}" if steam_id else "n_" + hashlib.sha1(name.lower().encode()).hexdigest()[:16]


def cover_path(key):
    return COVERS_DIR / f"{key}.jpg"


def _get(url, **kw):
    try:
        r = _session.get(url, timeout=15, **kw)
        if r.status_code == 200 and r.content and r.headers.get("Content-Type", "").startswith("image"):
            return r.content
    except requests.RequestException:
        pass
    return None


def _portrait(img: QImage) -> QImage:
    s = img.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return s.copy((s.width() - W) // 2, (s.height() - H) // 2, W, H)


def _landscape_to_portrait(img: QImage) -> QImage:
    """Capa horizontal centralizada sobre um fundo desfocado da própria imagem."""
    canvas = QImage(W, H, QImage.Format_RGB32)
    canvas.fill(QColor("#060a18"))
    # desfoque barato: reduz muito e amplia de novo
    blur = img.scaled(12, 18, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    blur = blur.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    scaled = img.scaledToWidth(W, Qt.SmoothTransformation)
    p = QPainter(canvas)
    p.drawImage((W - blur.width()) // 2, (H - blur.height()) // 2, blur)
    p.fillRect(0, 0, W, H, QColor(6, 10, 24, 150))
    p.drawImage(0, (H - scaled.height()) // 2, scaled)
    p.end()
    return canvas


def _save(img: QImage, key):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "JPG", 82)
    cover_path(key).write_bytes(bytes(ba))


def _steam_assets(steam_id):
    """Jogos novos têm capas em endereços com hash; a API da loja informa o caminho certo."""
    query = ('{"ids":[{"appid":%d}],"context":{"language":"english","country_code":"US"},'
             '"data_request":{"include_assets":true}}' % int(steam_id))
    try:
        r = _session.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1",
                         params={"input_json": query}, timeout=15)
        assets = r.json()["response"]["store_items"][0]["assets"]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return {}
    fmt = "https://shared.akamai.steamstatic.com/store_item_assets/" + assets.get("asset_url_format", "")
    return {k: fmt.replace("${FILENAME}", v) for k, v in assets.items()
            if isinstance(v, str) and v.endswith(".jpg")}


def _steamgriddb(name, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = _session.get(f"https://www.steamgriddb.com/api/v2/search/autocomplete/{requests.utils.quote(name)}",
                         headers=headers, timeout=15)
        games = r.json().get("data") or []
        if not games:
            return None
        r = _session.get(f"https://www.steamgriddb.com/api/v2/grids/game/{games[0]['id']}",
                         params={"dimensions": "600x900"}, headers=headers, timeout=15)
        grids = r.json().get("data") or []
        return _get(grids[0]["url"]) if grids else None
    except (requests.RequestException, ValueError, KeyError):
        return None


def fetch(key, steam_id, name, steamgriddb_key="", local_image=""):
    """Baixa e salva a capa. Retorna True se existe capa no fim. Roda em thread de fundo."""
    path = cover_path(key)
    if path.exists():
        return True
    miss = path.with_suffix(".miss")
    if miss.exists() and time.time() - miss.stat().st_mtime < RETRY_AFTER:
        return False
    img = QImage()
    if steam_id:
        for url in STEAM_PORTRAIT:
            data = _get(url.format(id=steam_id))
            if data and img.loadFromData(data):
                _save(_portrait(img), key)
                return True
        assets = _steam_assets(steam_id)
        for field, convert in (("library_capsule", _portrait), ("header", _landscape_to_portrait)):
            data = _get(assets[field]) if field in assets else None
            if data and img.loadFromData(data):
                _save(convert(img), key)
                return True
    if steamgriddb_key:
        data = _steamgriddb(name, steamgriddb_key)
        if data and img.loadFromData(data):
            _save(_portrait(img), key)
            return True
    if local_image and img.load(local_image):
        # ícone do próprio jogo (ex.: ICON0.PNG do PS3, horizontal)
        _save(_landscape_to_portrait(img) if img.width() > img.height() else _portrait(img), key)
        return True
    if steam_id:
        for url in STEAM_LANDSCAPE:
            data = _get(url.format(id=steam_id))
            if data and img.loadFromData(data):
                _save(_landscape_to_portrait(img), key)
                return True
    miss.touch()
    return False

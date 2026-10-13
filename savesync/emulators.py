"""Emuladores: RPCS3 (PlayStation 3).

O RPCS3 guarda cada save em  <dev_hdd0>\\home\\<usuário>\\savedata\\<TITLEID><sufixo>\\
(ex.: BLUS30443-AUTOSAVE). O código do jogo são os 9 primeiros caracteres da pasta, e o
PARAM.SFO de cada pasta traz o nome do jogo. O RPCS3 é portátil (não instala), então a
pasta dele é procurada nos discos, Área de Trabalho, Downloads e Documentos.
"""
import ctypes
import logging
import os
import re
import struct
import uuid
from dataclasses import dataclass, field

from .config import _known_folder

log = logging.getLogger(__name__)

TITLE_ID = re.compile(r"^[A-Z]{4}\d{5}")
# placeholder usado nos caminhos dos saves: o zip fica portável mesmo se o RPCS3 estiver em outra pasta
HDD0_TOKEN = "<rpcs3Hdd0>"


@dataclass
class PS3Game:
    title_id: str
    name: str
    hdd0: str
    save_dirs: list = field(default_factory=list)
    icon: str = ""


# ---------------------------------------------------------------- PARAM.SFO

def read_sfo(path) -> dict:
    """Lê um PARAM.SFO (formato de metadados do PS3/PSP)."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 * 1024)
    except OSError:
        return {}
    if len(data) < 20 or data[:4] != b"\0PSF":
        return {}
    key_start, data_start, count = struct.unpack_from("<III", data, 8)
    out = {}
    for i in range(min(count, 256)):
        base = 20 + i * 16
        if base + 16 > len(data):
            break
        key_off, fmt, length, _max_len, data_off = struct.unpack_from("<HHIII", data, base)
        key_end = data.find(b"\0", key_start + key_off)
        key = data[key_start + key_off:key_end].decode("ascii", "ignore")
        raw = data[data_start + data_off:data_start + data_off + length]
        if fmt == 0x0404 and len(raw) >= 4:          # inteiro
            out[key] = struct.unpack_from("<I", raw)[0]
        else:                                          # texto UTF-8
            out[key] = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    return out


def _clean(title):
    return " ".join((title or "").replace("\n", " ").split())


# ---------------------------------------------------------------- localizar o RPCS3

def _user_dirs():
    dirs = [os.path.expanduser("~")]
    for guid in ("B4BFCC3A-DB2C-424C-B029-7FE99A87C641",    # Área de Trabalho
                 "374DE290-123F-4565-9164-39C4925E467B",    # Downloads
                 "FDD39AD0-238F-46AF-ADB4-6C85480369C7"):   # Documentos
        p = _known_folder(guid)
        if p:
            dirs.append(p)
    return dirs


def _fixed_drives():
    drives = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        letter = f"{chr(65 + i)}:\\"
        if mask & (1 << i) and ctypes.windll.kernel32.GetDriveTypeW(letter) == 3:
            drives.append(letter)
    return drives


def find_rpcs3(extra_roots=()):
    """Pastas que contêm rpcs3.exe. Procura até 4 níveis por pastas com 'rpcs3' no nome,
    e também dentro das pastas extras configuradas pelo usuário."""
    found = {}

    def check(path):
        if os.path.isfile(os.path.join(path, "rpcs3.exe")):
            found.setdefault(os.path.normcase(path), os.path.normpath(path))
            return True
        return False

    def walk(path, depth):
        try:
            with os.scandir(path) as it:
                entries = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            return
        for e in entries:
            low = e.name.lower()
            if low.startswith(("$", ".")) or low in ("windows", "appdata", "program files", "programdata",
                                                    "program files (x86)", "node_modules", "dev_hdd0"):
                continue
            if "rpcs3" in low and check(e.path):
                continue
            if depth > 1:
                walk(e.path, depth - 1)

    for root in list(extra_roots):
        if os.path.isdir(root) and not check(root):
            walk(root, 2)
    for root in _user_dirs() + _fixed_drives():
        walk(root, 4)
    return list(found.values())


def hdd0_dir(rpcs3_dir):
    """Pasta dev_hdd0 (pode ter sido mudada em config/vfs.yml)."""
    for cfg in (os.path.join(rpcs3_dir, "config", "vfs.yml"), os.path.join(rpcs3_dir, "vfs.yml")):
        try:
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r'\s*"?/dev_hdd0/"?\s*:\s*(.+?)\s*$', line)
                    if m:
                        value = m.group(1).strip("'\"").replace("$(EmulatorDir)", rpcs3_dir.rstrip("\\/") + "/")
                        value = os.path.normpath(value)
                        if os.path.isdir(value):
                            return value
        except OSError:
            continue
    return os.path.join(rpcs3_dir, "dev_hdd0")


def _games_yml(rpcs3_dir):
    """config/games.yml: TITLEID -> caminho do jogo (pasta ou .iso)."""
    games = {}
    for cfg in (os.path.join(rpcs3_dir, "config", "games.yml"), os.path.join(rpcs3_dir, "games.yml")):
        try:
            with open(cfg, encoding="utf-8") as f:
                for line in f:
                    m = re.match(r'\s*"?([A-Z]{4}\d{5})"?\s*:\s*(.+?)\s*$', line)
                    if m:
                        games[m.group(1)] = os.path.normpath(m.group(2).strip("'\""))
        except OSError:
            continue
        if games:
            break
    return games


# ---------------------------------------------------------------- jogos e saves

def detect_rpcs3_games(extra_roots=()):
    games: dict[str, PS3Game] = {}
    for rpcs3_dir in find_rpcs3(extra_roots):
        hdd0 = hdd0_dir(rpcs3_dir)
        names, icons = {}, {}

        # jogos de disco/pasta listados pelo emulador
        for tid, path in _games_yml(rpcs3_dir).items():
            for sub in ("PS3_GAME", ""):
                sfo = read_sfo(os.path.join(path, sub, "PARAM.SFO"))
                if sfo.get("TITLE"):
                    names[tid] = _clean(sfo["TITLE"])
                    icon = os.path.join(path, sub, "ICON0.PNG")
                    if os.path.isfile(icon):
                        icons[tid] = icon
                    break
            else:
                if path.lower().endswith(".iso"):
                    # nome do arquivo sem marcações tipo "(USA)" ou "[site]"
                    stem = os.path.splitext(os.path.basename(path))[0]
                    names.setdefault(tid, _clean(re.sub(r"\[[^\]]*\]|\([^)]*\)", "", stem)) or tid)

        # jogos instalados no HD virtual (PSN)
        try:
            with os.scandir(os.path.join(hdd0, "game")) as it:
                for e in it:
                    sfo = read_sfo(os.path.join(e.path, "PARAM.SFO")) if e.is_dir() else {}
                    if sfo.get("CATEGORY") == "HG" and sfo.get("TITLE"):
                        tid = sfo.get("TITLE_ID") or e.name[:9]
                        names.setdefault(tid, _clean(sfo["TITLE"]))
                        icon = os.path.join(e.path, "ICON0.PNG")
                        if os.path.isfile(icon):
                            icons.setdefault(tid, icon)
        except OSError:
            pass

        # saves
        saves: dict[str, list] = {}
        save_names, save_icons = {}, {}
        try:
            with os.scandir(os.path.join(hdd0, "home")) as users:
                for user in users:
                    savedata = os.path.join(user.path, "savedata")
                    if not os.path.isdir(savedata):
                        continue
                    for e in os.scandir(savedata):
                        if not e.is_dir() or not TITLE_ID.match(e.name):
                            continue
                        tid = e.name[:9]
                        saves.setdefault(tid, []).append(e.path)
                        sfo = read_sfo(os.path.join(e.path, "PARAM.SFO"))
                        if sfo.get("TITLE"):
                            save_names.setdefault(tid, _clean(sfo["TITLE"]))
                        icon = os.path.join(e.path, "ICON0.PNG")
                        if os.path.isfile(icon):
                            save_icons.setdefault(tid, icon)
        except OSError:
            pass

        for tid in set(names) | set(saves):
            if tid in games:
                continue
            name = names.get(tid) or save_names.get(tid) or tid
            if name == tid and save_names.get(tid):
                name = save_names[tid]
            games[tid] = PS3Game(tid, name, hdd0, sorted(saves.get(tid, [])),
                                 icons.get(tid) or save_icons.get(tid, ""))
    log.info("RPCS3: %d jogos", len(games))
    return list(games.values())


def save_pattern(title_id):
    """Padrão (com placeholder) que pega todas as pastas de save do jogo, de qualquer usuário do RPCS3."""
    return f"{HDD0_TOKEN}/home/*/savedata/{title_id}*"

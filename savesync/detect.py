"""Detecta jogos instalados: Steam, Epic, GOG, Ubisoft e pastas soltas nos discos."""
import ctypes
import json
import logging
import os
import re
import winreg
from dataclasses import dataclass
from pathlib import Path

from .manifest import norm

log = logging.getLogger(__name__)


@dataclass
class InstalledGame:
    name: str
    store: str
    store_id: str
    install_dir: str


# ---------------------------------------------------------------- utilidades

def _reg_value(root, path, name):
    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _reg_subkeys(root, path):
    try:
        with winreg.OpenKey(root, path) as key:
            i = 0
            while True:
                try:
                    yield winreg.EnumKey(key, i)
                except OSError:
                    return
                i += 1
    except OSError:
        return


def parse_vdf(text: str) -> dict:
    """Parser mínimo do formato KeyValues da Steam (.vdf / .acf). Chaves em minúsculas."""
    root, stack, key = {}, [], None
    stack.append(root)
    for quoted, brace in re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', text):
        if brace == "{":
            child = {}
            stack[-1][(key or "").lower()] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            value = quoted.replace("\\\\", "\\")
            if key is None:
                key = value
            else:
                stack[-1][key.lower()] = value
                key = None
    return root


def fixed_drives():
    drives = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if mask & (1 << i):
            letter = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(letter) == 3:  # DRIVE_FIXED
                drives.append(letter)
    return drives


# ---------------------------------------------------------------- Steam

_STEAM_SKIP_IDS = {228980, 1070560, 1391110, 1628350, 1493710, 2180100, 1826330, 250820, 1007}
_STEAM_SKIP_NAMES = re.compile(r"redistributable|proton|steam linux runtime|steamworks|steamvr|dedicated server|sdk$", re.I)


def steam_root():
    path = (_reg_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath")
            or _reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"))
    return os.path.normpath(path) if path and os.path.isdir(path) else None


def detect_steam():
    root = steam_root()
    if not root:
        return []
    libraries = {os.path.normcase(root): root}
    vdf = Path(root, "steamapps", "libraryfolders.vdf")
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
        for value in data.get("libraryfolders", {}).values():
            path = value.get("path") if isinstance(value, dict) else value
            if isinstance(path, str) and os.path.isdir(path):
                libraries[os.path.normcase(path)] = os.path.normpath(path)
    except OSError:
        pass
    games = []
    for lib in libraries.values():
        apps = Path(lib, "steamapps")
        for acf in apps.glob("appmanifest_*.acf"):
            try:
                state = parse_vdf(acf.read_text(encoding="utf-8", errors="replace")).get("appstate", {})
                appid, name, folder = int(state["appid"]), state.get("name", ""), state.get("installdir", "")
            except (OSError, KeyError, ValueError):
                continue
            if appid in _STEAM_SKIP_IDS or _STEAM_SKIP_NAMES.search(name):
                continue
            install = apps / "common" / folder
            games.append(InstalledGame(name or folder, "steam", str(appid), str(install)))
    return games


# ---------------------------------------------------------------- Epic

def detect_epic():
    folder = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")
    games = []
    for item in folder.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if data.get("bIsIncompleteInstall"):
            continue
        main = data.get("MainGameAppName")
        if main and main != data.get("AppName"):
            continue  # DLC
        cats = data.get("AppCategories") or []
        if cats and "games" not in cats:
            continue
        install = data.get("InstallLocation", "")
        if install and os.path.isdir(install):
            games.append(InstalledGame(data.get("DisplayName") or data.get("AppName"), "epic",
                                       data.get("AppName", ""), os.path.normpath(install)))
    return games


# ---------------------------------------------------------------- GOG

def detect_gog():
    games = []
    for base in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            key = f"{base}\\{sub}"
            path = _reg_value(winreg.HKEY_LOCAL_MACHINE, key, "path")
            name = _reg_value(winreg.HKEY_LOCAL_MACHINE, key, "gameName")
            if _reg_value(winreg.HKEY_LOCAL_MACHINE, key, "dependsOn"):
                continue
            if path and name and os.path.isdir(path):
                gog_id = _reg_value(winreg.HKEY_LOCAL_MACHINE, key, "gameID") or sub
                games.append(InstalledGame(name, "gog", str(gog_id), os.path.normpath(path)))
        if games:
            break
    return games


# ---------------------------------------------------------------- Ubisoft

def detect_ubisoft():
    games = []
    base = r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
    for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        path = _reg_value(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{sub}", "InstallDir")
        if path and os.path.isdir(path):
            path = os.path.normpath(path)
            games.append(InstalledGame(os.path.basename(path), "uplay", sub, path))
    return games


def detect_launchers():
    games = []
    for detector in (detect_steam, detect_epic, detect_gog, detect_ubisoft):
        try:
            found = detector()
            log.info("%s: %d jogos", detector.__name__, len(found))
            games += found
        except Exception:
            log.exception("Falha em %s", detector.__name__)
    return games


# ---------------------------------------------------------------- pastas soltas nos discos

_SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "programdata", "users", "recovery",
    "perflogs", "windowsapps", "msocache", "config.msi", "intel", "amd", "nvidia", "drivers",
    "msys64", "$windows.~ws", "$winreagent", "$sysreset", "steamapps", "appdata", "onedrivetemp",
    "windows kits", "microsoft", "microsoft office", "common files", "windowspowershell",
    "internet explorer", "windows defender", "reference assemblies", "dotnet", "node_modules",
}
_SKIP_DIRS |= {"google", "mozilla", "mozilla firefox", "microsoft edge", "opera", "brave software",
               "discord", "spotify", "adobe", "oracle", "java", "git", "nodejs", "docker", "nvidia corporation",
               "obs-studio", "7-zip", "notepad++", "videolan", "zoom", "python312", "python311", "python310"}
# nomes de pasta que também são nomes de jogo no banco, mas quase sempre são programas
_GENERIC_NAMES = {"games", "game", "jogos", "common", "data", "bin", "steam", "launcher", "tools",
                  "emulators", "programfiles", "programfilesx86", "windows", "temp", "backup", "saves",
                  "chrome", "firefox", "edge", "opera", "discord", "spotify", "telegram", "whatsapp",
                  "zoom", "skype", "teams", "office", "photoshop", "blender", "unity", "unreal", "godot",
                  "audacity", "gimp", "krita", "obs", "vlc", "winrar", "update", "updater", "setup"}


def _subdirs(path):
    try:
        with os.scandir(path) as it:
            return [e for e in it if e.is_dir(follow_symlinks=False) and e.name.lower() not in _SKIP_DIRS
                    and not e.name.startswith(".")]
    except OSError:
        return []


def _has_exe(path, depth=3, budget=None):
    budget = budget if budget is not None else [3000]
    try:
        with os.scandir(path) as it:
            dirs = []
            for e in it:
                budget[0] -= 1
                if budget[0] <= 0:
                    return False
                if e.is_file() and e.name.lower().endswith(".exe"):
                    return True
                if e.is_dir(follow_symlinks=False):
                    dirs.append(e.path)
    except OSError:
        return False
    return depth > 0 and any(_has_exe(d, depth - 1, budget) for d in dirs)


def scan_folders(manifest, extra_roots, known_dirs: set):
    """Procura pastas de jogos (até 3 níveis) em todos os discos fixos e nas pastas extras.

    Uma pasta conta como jogo quando o nome bate com o 'installDir' de algum jogo do
    manifest e ela contém um .exe.
    """
    results, seen = [], set(known_dirs)

    def consider(entry_path, entry_name):
        n = norm(entry_name)
        if len(n) < 4 or n in _GENERIC_NAMES:
            return False
        mname = manifest.by_installdir.get(n)
        if not mname:
            return False
        key = os.path.normcase(entry_path)
        if key in seen:
            return True
        if not _has_exe(entry_path):
            return False
        seen.add(key)
        results.append(InstalledGame(mname, "folder", "", os.path.normpath(entry_path)))
        return True

    roots = fixed_drives() + [r for r in extra_roots if os.path.isdir(r)]
    for root in roots:
        for d1 in _subdirs(root):
            if consider(d1.path, d1.name):
                continue
            for d2 in _subdirs(d1.path):
                if consider(d2.path, d2.name):
                    continue
                for d3 in _subdirs(d2.path):
                    consider(d3.path, d3.name)
    log.info("Varredura de pastas: %d jogos", len(results))
    return results

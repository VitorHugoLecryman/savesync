"""Caminhos do app, pastas conhecidas do Windows e configurações."""
import ctypes
import functools
import getpass
import json
import os
import platform
import threading
import uuid
from ctypes import wintypes
from pathlib import Path

APP_NAME = "SaveSync"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / APP_NAME
COVERS_DIR = APP_DIR / "covers"
LOG_PATH = APP_DIR / "savesync.log"
BACKUPS_DIR = APP_DIR / "backups_locais"
TEMP_DIR = APP_DIR / "temp"
MACHINE = platform.node() or "PC"


def open_log():
    """Abre o log no editor de texto padrão (Bloco de Notas)."""
    ensure_dirs()
    LOG_PATH.touch(exist_ok=True)
    os.startfile(str(LOG_PATH))


def ensure_dirs():
    for d in (APP_DIR, COVERS_DIR, BACKUPS_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data):
    """Grava JSON de forma atômica (evita arquivo corrompido se o PC desligar no meio)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- pastas do Windows

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        u = uuid.UUID(text)
        super().__init__(u.fields[0], u.fields[1], u.fields[2],
                         (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))


def _known_folder(guid: str):
    """Usa a API do Windows: acha a pasta Documentos mesmo se ela estiver no OneDrive."""
    ptr = ctypes.c_wchar_p()
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(_GUID(guid)), 0, None, ctypes.byref(ptr))
    except (AttributeError, OSError):
        return None
    if hr != 0:
        return None
    value = ptr.value
    ctypes.windll.ole32.CoTaskMemFree(ptr)
    return value


@functools.cache
def known_folders() -> dict:
    """Mapa placeholder -> caminho real nesta máquina (mesmos nomes do manifest do Ludusavi)."""
    home = _known_folder("5E6C858F-0E22-4760-9AFE-EA3317B67173") or str(Path.home())
    env = os.environ
    folders = {
        "<home>": home,
        "<winAppData>": _known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D") or env.get("APPDATA"),
        "<winLocalAppData>": _known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091") or env.get("LOCALAPPDATA"),
        "<winLocalAppDataLow>": os.path.join(home, "AppData", "LocalLow"),
        "<winDocuments>": _known_folder("FDD39AD0-238F-46AF-ADB4-6C85480369C7") or os.path.join(home, "Documents"),
        "<winSavedGames>": _known_folder("4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4") or os.path.join(home, "Saved Games"),
        "<winProgramData>": _known_folder("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97") or env.get("PROGRAMDATA"),
        "<winPublic>": _known_folder("DFDF76A2-C82A-4D63-906A-5644AC457385") or env.get("PUBLIC"),
        "<winDir>": _known_folder("F38BF404-1D43-42F2-9305-67DE0B28FC23") or env.get("WINDIR"),
    }
    return {k: os.path.normpath(v) for k, v in folders.items() if v}


def os_user_name():
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME", "")


# ---------------------------------------------------------------- configurações

DEFAULTS = {
    "autostart": True,
    "include_config": False,       # incluir arquivos de configuração além dos saves
    "debounce_seconds": 20,        # espera o jogo terminar de gravar antes de enviar
    "max_save_mb": 1024,           # trava de segurança contra padrões que pegam arquivos demais
    "local_backups_keep": 5,       # cópias locais guardadas antes de substituir um save pelo da nuvem
    "drive_folder": "SaveSync",
    "steamgriddb_key": "",
    "scan_folders": [],            # pastas extras onde procurar jogos avulsos
    "paused": False,
    "tray_hint_shown": False,
}


class Settings:
    def __init__(self):
        self.path = APP_DIR / "settings.json"
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        self.data.update(read_json(self.path, {}))

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        with self._lock:
            self.data[key] = value
            write_json(self.path, self.data)

    def update(self, values: dict):
        with self._lock:
            self.data.update(values)
            write_json(self.path, self.data)

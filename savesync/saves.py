"""Localiza os arquivos de save, calcula a 'impressão digital' e monta/extrai os .zip.

Dentro do zip os caminhos são "portáveis": C:\\Users\\fulano\\AppData\\Roaming\\X vira
AppData_Roaming/X. Assim o save restaura certo em outro PC, com outro usuário ou outra
pasta de Documentos.
"""
import glob
import hashlib
import json
import os
import re
import threading
import time
import zipfile
import zlib
from dataclasses import dataclass

from .config import APP_DIR, MACHINE, known_folders, os_user_name, read_json, write_json

# placeholder -> nome da pasta dentro do zip
TOKEN_DIRS = {
    "<base>": "PastaDoJogo",
    "<rpcs3Hdd0>": "RPCS3_dev_hdd0",
    "<root>": "Steam",
    "<winLocalAppDataLow>": "AppData_LocalLow",
    "<winLocalAppData>": "AppData_Local",
    "<winAppData>": "AppData_Roaming",
    "<winDocuments>": "Documentos",
    "<winSavedGames>": "SavedGames",
    "<winPublic>": "Publico",
    "<winProgramData>": "ProgramData",
    "<winDir>": "Windows",
    "<home>": "Usuario",
}
DIR_TOKENS = {v.lower(): k for k, v in TOKEN_DIRS.items()}
INDEX_NAME = "savesync.json"
_GLOB_CHARS = set("*?[")


@dataclass
class SaveFile:
    path: str        # caminho real
    portable: str    # caminho dentro do zip
    size: int
    mtime: float


def roots_for(record, steam_root=None) -> dict:
    roots = dict(known_folders())
    if record.get("install_dir") and os.path.isdir(record["install_dir"]):
        roots["<base>"] = os.path.normpath(record["install_dir"])
    if record.get("emu_root") and os.path.isdir(record["emu_root"]):
        roots["<rpcs3Hdd0>"] = os.path.normpath(record["emu_root"])
    if steam_root:
        roots["<root>"] = steam_root
    return roots


def expand(pattern: str, roots: dict):
    """Troca os placeholders do manifest pelos caminhos reais. None se faltar algum."""
    text = pattern.replace("<storeUserId>", "*").replace("<osUserName>", os_user_name())
    for token in re.findall(r"<[A-Za-z0-9]+>", text):
        if token not in roots:
            return None
        text = text.replace(token, roots[token])
    return os.path.normpath(text)


def _escape_brackets(path):
    return re.sub(r"[\[\]]", lambda m: f"[{m.group(0)}]", path)


def literal_prefix(path: str) -> str:
    """Parte do caminho antes do primeiro curinga."""
    parts = re.split(r"[\\/]", path)
    out = []
    for part in parts:
        if _GLOB_CHARS & set(part):
            break
        out.append(part)
    if len(out) == 1 and out[0].endswith(":"):
        return out[0] + "\\"
    return "\\".join(out)


def to_portable(path: str, roots: dict) -> str:
    low = os.path.normcase(path)
    best = None
    for token, root in roots.items():
        if token not in TOKEN_DIRS:
            continue
        r = os.path.normcase(root).rstrip("\\") + "\\"
        if low.startswith(r) and (best is None or len(r) > len(best[1])):
            best = (token, r)
    if best:
        rel = path[len(best[1]):]
        return TOKEN_DIRS[best[0]] + "/" + rel.replace("\\", "/")
    drive, rest = os.path.splitdrive(path)
    return f"Disco_{drive.rstrip(':').upper() or 'X'}" + rest.replace("\\", "/")


def from_portable(portable: str, roots: dict):
    head, _, rest = portable.partition("/")
    if head.lower().startswith("disco_"):
        return os.path.normpath(f"{head[6:]}:\\{rest}")
    token = DIR_TOKENS.get(head.lower())
    if not token or token not in roots:
        return None
    return os.path.normpath(os.path.join(roots[token], rest))


def save_patterns(record, manifest, include_config):
    pats = []
    if record.get("manifest_name"):
        pats += manifest.patterns(record["manifest_name"], record.get("store"), include_config)
    pats += record.get("custom_paths") or []
    return pats


def find_files(record, manifest, include_config=False, steam_root=None):
    roots = roots_for(record, steam_root)
    found = {}
    for pattern in save_patterns(record, manifest, include_config):
        real = expand(pattern, roots)
        if not real:
            continue
        prefix = literal_prefix(real)
        if not os.path.exists(prefix):
            continue
        matches = glob.glob(_escape_brackets(real), recursive=True, include_hidden=True) if prefix != real else [real]
        for m in matches:
            if os.path.isdir(m):
                for dirpath, _, names in os.walk(m):
                    for n in names:
                        _add(found, os.path.join(dirpath, n), roots)
            elif os.path.isfile(m):
                _add(found, m, roots)
    return sorted(found.values(), key=lambda f: f.portable.lower())


def _add(found, path, roots):
    key = os.path.normcase(os.path.abspath(path))
    if key in found:
        return
    try:
        st = os.stat(path)
    except OSError:
        return
    found[key] = SaveFile(os.path.abspath(path), to_portable(os.path.abspath(path), roots), st.st_size, st.st_mtime)


def watch_dirs(record, manifest, include_config=False, steam_root=None):
    """Pastas que o observador precisa vigiar para este jogo."""
    roots = roots_for(record, steam_root)
    too_broad = {os.path.normcase(v) for v in known_folders().values()}
    dirs = set()
    for pattern in save_patterns(record, manifest, include_config):
        real = expand(pattern, roots)
        if not real:
            continue
        prefix = literal_prefix(real)
        if os.path.isfile(prefix):
            prefix = os.path.dirname(prefix)
        while prefix and not os.path.isdir(prefix):
            parent = os.path.dirname(prefix)
            if parent == prefix:
                break
            prefix = parent
        # nunca vigia raízes amplas demais (ex.: a pasta do usuário inteira)
        if prefix and os.path.normcase(prefix) not in too_broad and os.path.splitdrive(prefix)[1] not in ("", "\\"):
            dirs.add(os.path.normpath(prefix))
    return dirs


# ---------------------------------------------------------------- impressão digital

class HashCache:
    """Guarda o SHA-256 de cada arquivo junto com tamanho/data para não reler o que não mudou."""

    def __init__(self):
        self.path = APP_DIR / "hashes.json"
        self.data = read_json(self.path, {})
        self.lock = threading.Lock()
        self.dirty = False

    def file_hash(self, f: SaveFile):
        key = os.path.normcase(f.path)
        cached = self.data.get(key)
        if cached and cached[0] == f.size and cached[1] == f.mtime:
            return cached[2]
        h = hashlib.sha256()
        with open(f.path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        with self.lock:
            self.data[key] = [f.size, f.mtime, digest]
            self.dirty = True
        return digest

    def save(self):
        with self.lock:
            if self.dirty:
                write_json(self.path, self.data)
                self.dirty = False


def combine(entries) -> str:
    """entries: [(portable, sha)] -> hash único do save inteiro (não depende de datas nem do PC)."""
    h = hashlib.sha256()
    for portable, sha in sorted(entries, key=lambda e: e[0].lower()):
        h.update(f"{portable.lower()}\0{sha}\n".encode())
    return h.hexdigest()


def save_hash(files, cache: HashCache):
    return combine((f.portable, cache.file_hash(f)) for f in files) if files else None


# ---------------------------------------------------------------- zip

def _worth_compressing(path):
    """Testa o começo do arquivo: saves já comprimidos (ex.: .lsv do BG3, imagens) são guardados sem
    recompressão, o que deixa a preparação ~10x mais rápida sem aumentar o tamanho."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(256 << 10)
    except OSError:
        return True
    if len(head) < 4096:
        return True
    return len(zlib.compress(head, 1)) < len(head) * 0.9


def build_zip(files, dest, game_name):
    """Cria o zip lendo cada arquivo uma única vez; o hash vem dos mesmos bytes enviados."""
    entries = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            h = hashlib.sha256()
            # zip não aceita datas antes de 1980 (alguns saves copiados de mídia antiga têm data zerada)
            info = zipfile.ZipInfo(f.portable, time.localtime(max(f.mtime, 315705600))[:6])
            info.compress_type = zipfile.ZIP_DEFLATED if _worth_compressing(f.path) else zipfile.ZIP_STORED
            with open(f.path, "rb") as src, zf.open(info, "w") as out:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    h.update(chunk)
                    out.write(chunk)
            entries.append({"path": f.portable, "sha": h.hexdigest(), "mtime": f.mtime})
        digest = combine((e["path"], e["sha"]) for e in entries)
        index = {"game": game_name, "hash": digest, "machine": MACHINE,
                 "saved_at": time.time(), "files": entries}
        zf.writestr(INDEX_NAME, json.dumps(index, ensure_ascii=False, indent=1))
    return digest


def read_index(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read(INDEX_NAME))


def extract_zip(zip_path, roots, current_files):
    """Restaura o save. Apaga arquivos locais que não existem no save da nuvem
    (o chamador já fez backup local antes)."""
    with zipfile.ZipFile(zip_path) as zf:
        index = json.loads(zf.read(INDEX_NAME))
        targets = []
        for e in index["files"]:
            dest = from_portable(e["path"], roots)
            if dest is None:
                folder = e["path"].split("/")[0]
                raise RuntimeError(f"Não sei onde fica '{folder}' neste PC. Defina a pasta do jogo nos detalhes.")
            targets.append((e, dest))
        keep = {os.path.normcase(d) for _, d in targets}
        for f in current_files:
            if os.path.normcase(f.path) not in keep:
                try:
                    os.remove(f.path)
                except OSError:
                    pass
        for e, dest in targets:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".savesync-tmp"
            with zf.open(e["path"]) as src, open(tmp, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
            os.replace(tmp, dest)
            if e.get("mtime"):
                os.utime(dest, (e["mtime"], e["mtime"]))
    return index

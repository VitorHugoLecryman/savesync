"""Banco de dados de locais de save (manifest do Ludusavi, feito a partir do PCGamingWiki).

O YAML original tem ~17 MB e demora ~10 s para ler, então ele é convertido uma vez
para um JSON compacto só com o que interessa no Windows.
"""
import json
import logging
import re
import time
import unicodedata

import requests
import yaml

from .config import APP_DIR, read_json, write_json

log = logging.getLogger(__name__)

MANIFEST_URL = "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml"
CACHE_PATH = APP_DIR / "manifest.json"
META_PATH = APP_DIR / "manifest_meta.json"
MAX_AGE_DAYS = 7

TAG_SAVE = 1
TAG_CONFIG = 2
KNOWN_STORES = {"steam", "epic", "gog", "uplay", "microsoft", "origin", "ea"}
_NON_WINDOWS = ("<xdgData>", "<xdgConfig>", "<home>/Library/", "<home>/.")


def norm(text: str) -> str:
    """Normaliza nomes para comparação: 'The Witcher® 3: Wild Hunt' -> 'thewitcher3wildhunt'."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _compact(raw: dict) -> dict:
    games, aliases = {}, {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if "alias" in entry:
            aliases[name] = entry["alias"]
            continue
        files = []
        for path, info in (entry.get("files") or {}).items():
            info = info or {}
            if any(marker in path for marker in _NON_WINDOWS):
                continue
            whens = info.get("when") or []
            applies, stores = not whens, set()
            unrestricted = not whens
            for w in whens:
                if w.get("os") in (None, "windows"):
                    applies = True
                    if w.get("store"):
                        stores.add(w["store"])
                    else:
                        unrestricted = True
            if not applies:
                continue
            tags = info.get("tags") or ["save"]
            bits = (TAG_SAVE if "save" in tags else 0) | (TAG_CONFIG if "config" in tags else 0)
            files.append([path, bits or TAG_SAVE, None if unrestricted else sorted(stores)])
        if not files:
            continue
        game = {"f": files}
        ids = entry.get("id") or {}
        steam_ids = [(entry.get("steam") or {}).get("id")] + list(ids.get("steamExtra") or [])
        gog_ids = [(entry.get("gog") or {}).get("id")] + list(ids.get("gogExtra") or [])
        game["s"] = [i for i in steam_ids if i]
        game["g"] = [i for i in gog_ids if i]
        game["i"] = list((entry.get("installDir") or {}).keys())
        game["c"] = [k for k, v in (entry.get("cloud") or {}).items() if v]
        games[name] = game
    return {"version": 1, "games": games, "aliases": aliases}


class Manifest:
    def __init__(self, data=None):
        self.games: dict = {}
        self.by_steam: dict = {}
        self.by_gog: dict = {}
        self.by_norm: dict = {}
        self.by_installdir: dict = {}
        if data:
            self._index(data)

    def _index(self, data):
        # cada jogo fica guardado como texto JSON e só é decodificado quando usado (economiza ~35 MB)
        self.games = {}
        for name, g in data.get("games", {}).items():
            if isinstance(g, str):
                self.games[name] = g
                g = json.loads(g)
            else:
                self.games[name] = json.dumps(g, ensure_ascii=False, separators=(",", ":"))
            self.by_norm.setdefault(norm(name), name)
            for sid in g.get("s", []):
                self.by_steam.setdefault(int(sid), name)
            for gid in g.get("g", []):
                self.by_gog.setdefault(int(gid), name)
            for d in g.get("i", []):
                self.by_installdir.setdefault(norm(d), name)
        for alias, target in data.get("aliases", {}).items():
            if target in self.games:
                self.by_norm.setdefault(norm(alias), target)

    @property
    def loaded(self):
        return bool(self.games)

    @classmethod
    def load(cls):
        t = time.time()
        data = read_json(CACHE_PATH, None)
        m = cls(data)
        if m.loaded:
            log.info("Manifest carregado: %d jogos em %.1fs", len(m.games), time.time() - t)
        return m

    @staticmethod
    def needs_update():
        meta = read_json(META_PATH, {})
        return not CACHE_PATH.exists() or time.time() - meta.get("checked", 0) > MAX_AGE_DAYS * 86400

    @classmethod
    def download(cls, force=False):
        """Baixa o manifest se mudou (usa ETag). Retorna um Manifest novo ou None se nada mudou."""
        meta = read_json(META_PATH, {})
        headers = {}
        if not force and CACHE_PATH.exists() and meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        resp = requests.get(MANIFEST_URL, headers=headers, timeout=120)
        if resp.status_code == 304:
            meta["checked"] = time.time()
            write_json(META_PATH, meta)
            return None
        resp.raise_for_status()
        t = time.time()
        raw = yaml.load(resp.content, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
        compact = _compact(raw)
        del raw
        manifest = cls(compact)
        data = {"version": 2, "games": manifest.games, "aliases": compact["aliases"]}
        del compact
        tmp = CACHE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(CACHE_PATH)
        write_json(META_PATH, {"etag": resp.headers.get("ETag"), "checked": time.time()})
        log.info("Manifest atualizado: %d jogos com save conhecido (%.1fs)", len(manifest.games), time.time() - t)
        return manifest

    # ------------------------------------------------------------ consultas

    def find(self, name):
        if name in self.games:
            return name
        return self.by_norm.get(norm(name))

    def match_installed(self, store, store_id, name, install_dir=""):
        try:
            if store == "steam" and store_id:
                hit = self.by_steam.get(int(store_id))
                if hit:
                    return hit
            if store == "gog" and store_id:
                hit = self.by_gog.get(int(store_id))
                if hit:
                    return hit
        except ValueError:
            pass
        hit = self.find(name)
        if hit:
            return hit
        if install_dir:
            folder = re.split(r"[\\/]", install_dir.rstrip("\\/"))[-1]
            return self.by_installdir.get(norm(folder))
        return None

    def _entry(self, mname):
        raw = self.games.get(mname) if mname else None
        return json.loads(raw) if raw else {}

    def patterns(self, mname, store, include_config=False, saves_only=False):
        game = self._entry(mname)
        if not game:
            return []
        out = []
        for path, bits, stores in game["f"]:
            wanted = bits & TAG_SAVE or (include_config and not saves_only and bits & TAG_CONFIG)
            if not wanted:
                continue
            if stores and store in KNOWN_STORES and store not in stores:
                continue
            out.append(path)
        return out

    def steam_id(self, mname):
        ids = self._entry(mname).get("s") or []
        return ids[0] if ids else None

    def cloud(self, mname):
        return self._entry(mname).get("c") or []

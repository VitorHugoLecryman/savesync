"""Lista de jogos conhecidos e o estado de sincronização de cada um (library.json)."""
import threading

from .config import APP_DIR, read_json, write_json


def new_record(gid, name, store, store_id="", install_dir="", manifest_name=None):
    return {
        "id": gid,
        "name": name,
        "store": store,               # steam | epic | gog | uplay | folder | found | manual
        "store_id": str(store_id or ""),
        "install_dir": install_dir or "",
        "installed": True,
        "manifest_name": manifest_name,
        "manifest_locked": False,     # True quando o usuário escolheu o jogo do banco manualmente
        "custom_paths": [],           # pastas/arquivos de save adicionados pelo usuário
        "enabled": False,             # backup automático ligado
        "hidden": False,
        "sync": {},                   # base_hash, remote_id, last_sync
    }


class Library:
    def __init__(self):
        self.path = APP_DIR / "library.json"
        self.lock = threading.RLock()
        self.games: dict[str, dict] = read_json(self.path, {}).get("games", {})
        for gid, rec in self.games.items():
            base = new_record(gid, rec.get("name", gid), rec.get("store", "manual"))
            base.update(rec)
            self.games[gid] = base

    def save(self):
        with self.lock:
            write_json(self.path, {"version": 1, "games": self.games})

    def get(self, gid):
        return self.games.get(gid)

    def all(self):
        with self.lock:
            return list(self.games.values())

    def add(self, rec):
        with self.lock:
            self.games[rec["id"]] = rec

    def update(self, gid, save=True, **fields):
        with self.lock:
            rec = self.games.get(gid)
            if rec is None:
                return None
            rec.update(fields)
            if save:
                self.save()
            return rec

    def update_sync(self, gid, **fields):
        with self.lock:
            rec = self.games.get(gid)
            if rec is not None:
                rec.setdefault("sync", {}).update(fields)
                self.save()

    def remove(self, gid):
        with self.lock:
            self.games.pop(gid, None)
            self.save()

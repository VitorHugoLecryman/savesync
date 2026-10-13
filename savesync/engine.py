"""Motor do SaveSync: varredura, comparação local x nuvem, envio, download e observador.

Toda operação pesada roda numa única thread de fundo (fila), então nunca há dois envios
ao Drive ao mesmo tempo e a interface não trava.

Como a comparação funciona (por jogo):
  local  = hash dos arquivos de save neste PC
  nuvem  = hash gravado junto do .zip no Drive
  base   = hash da última sincronização feita neste PC
  local == nuvem            -> sincronizado
  nuvem == base             -> só o local mudou     -> enviar
  local == base             -> só a nuvem mudou     -> baixar
  os dois mudaram           -> conflito (o usuário escolhe)
"""
import glob
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from itertools import islice

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from . import covers, detect, emulators, saves
from .config import BACKUPS_DIR, TEMP_DIR, known_folders
from .drive import NETWORK_ERRORS, AuthRequired, DriveClient, RemoteSave, describe_error, game_key_hash
from .library import new_record
from .manifest import Manifest, norm

log = logging.getLogger(__name__)

SYNCED, UPLOAD, DOWNLOAD, CONFLICT = "synced", "upload", "download", "conflict"
NOSAVE, LOCAL, OFFLINE, TOOBIG, BUSY, ERROR, UNKNOWN = "nosave", "local", "offline", "toobig", "busy", "error", "unknown"
PENDING_STATES = (UPLOAD, DOWNLOAD, CONFLICT)
SCANNED_STORES = {"steam", "epic", "gog", "uplay", "folder", "rpcs3"}


@dataclass
class GameStatus:
    state: str = UNKNOWN
    files: list = field(default_factory=list)
    local_hash: str | None = None
    local_size: int = 0
    local_mtime: float = 0.0
    remote: RemoteSave | None = None
    message: str = ""


def game_key(rec) -> str:
    """Identidade do jogo na nuvem (igual em todos os PCs)."""
    if rec.get("store") == "rpcs3":
        return "rpcs3" + rec["store_id"].lower()   # código do jogo PS3, ex.: rpcs3blus30443
    return norm(rec.get("manifest_name") or rec["name"]) or rec["id"]


class _Handler(FileSystemEventHandler):
    def __init__(self, engine):
        self.engine = engine

    def on_any_event(self, event):
        if event.event_type not in ("created", "modified", "deleted", "moved", "closed"):
            return
        if event.is_directory and event.event_type == "modified":
            return
        self.engine.on_fs_event(event.src_path)
        if getattr(event, "dest_path", ""):
            self.engine.on_fs_event(event.dest_path)


class Engine:
    def __init__(self, settings, library, events):
        self.settings = settings
        self.library = library
        self.events = events
        self.manifest = Manifest()
        self.drive = DriveClient(settings.get("drive_folder"))
        self.hashes = saves.HashCache()
        self.steam_root = detect.steam_root()
        self.status: dict[str, GameStatus] = {}
        self.remote: dict[str, RemoteSave] = {}
        self.remote_ok = False
        self.drive_error = "connecting" if self.drive.has_token() else "notconnected"
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="sync")
        self.cover_pool = ThreadPoolExecutor(4, thread_name_prefix="cover")
        self._cover_requested = set()
        self._timers: dict[str, threading.Timer] = {}
        self._timer_lock = threading.Lock()
        self._suppress_until: dict[str, float] = {}
        self._watch_map: dict[str, set] = {}
        self._handler = _Handler(self)
        self.observer = None
        self._clean_temp()

    def _clean_temp(self):
        """Apaga .zip que sobraram de envios/downloads interrompidos (podem ter vários GB)."""
        for leftover in TEMP_DIR.glob("*"):
            _remove_quietly(leftover)

    # ------------------------------------------------------------ fila de trabalho

    def submit(self, label, fn, *args, **kwargs):
        def run():
            self.events.busy.emit(label)
            try:
                return fn(*args, **kwargs)
            except AuthRequired:
                self._set_drive_error("auth")
                self.events.notify.emit("Google Drive", "A conexão com o Google Drive expirou. Abra o SaveSync e conecte de novo.")
            except Exception as e:
                log.exception("Erro em: %s", label)
                self.events.error.emit(describe_error(e) or e.__class__.__name__)
            finally:
                try:
                    self.hashes.save()
                except OSError:
                    pass
                self.events.busy.emit("")
        return self.pool.submit(run)

    def shutdown(self):
        with self._timer_lock:
            for t in self._timers.values():
                t.cancel()
        if self.observer:
            self.observer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.cover_pool.shutdown(wait=False, cancel_futures=True)
        self.hashes.save()

    # ------------------------------------------------------------ rotina completa

    def routine(self, source="manual"):
        """Usada ao abrir o programa: banco de saves, jogos, Drive, verificação e observador."""
        self.ensure_manifest()
        self.scan(deep=not self.library.games)
        tries = 6 if source == "startup" else 1
        for attempt in range(tries):
            if self.refresh_remote() or self.drive_error != "offline":
                break
            if attempt < tries - 1:
                self.events.busy.emit("Sem internet, tentando de novo em 20 s…")
                time.sleep(20)
        self.check(source)
        self.rebuild_watches()

    def refresh_and_check(self, source="manual"):
        self.refresh_remote()
        self.check(source)

    # ------------------------------------------------------------ banco de saves

    def ensure_manifest(self, force=False):
        if not self.manifest.loaded:
            self.manifest = Manifest.load()
        if force or not self.manifest.loaded or Manifest.needs_update():
            self.events.busy.emit("Atualizando banco de dados de saves (pode levar 1 minuto)…")
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--update-manifest"]
            else:
                cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "..", "main.py"), "--update-manifest"]
            if force:
                cmd.append("--force")
            try:
                code = subprocess.run(cmd, creationflags=subprocess.CREATE_NO_WINDOW, timeout=900).returncode
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning("Falha ao rodar atualização do banco: %s", e)
                code = 1
            if code == 0:
                self.manifest = Manifest.load()
                self._rematch()
            elif code != 3 and not self.manifest.loaded:
                raise RuntimeError("Não consegui baixar o banco de dados de saves. Verifique a internet.")

    def _rematch(self):
        with self.library.lock:
            for rec in self.library.all():
                if not rec.get("manifest_locked"):
                    hit = self.manifest.match_installed(rec["store"], rec["store_id"], rec["name"], rec["install_dir"])
                    rec["manifest_name"] = hit or rec.get("manifest_name")
            self.library.save()

    # ------------------------------------------------------------ jogos

    def scan(self, deep=False):
        self.events.busy.emit("Procurando jogos instalados…")
        self.steam_root = detect.steam_root()
        found = detect.detect_launchers()
        lib = self.library
        known = {os.path.normcase(g.install_dir) for g in found}
        known |= {os.path.normcase(r["install_dir"]) for r in lib.all() if r["store"] == "manual" and r["install_dir"]}
        self.events.busy.emit("Procurando jogos nos discos…")
        found += detect.scan_folders(self.manifest, self.settings.get("scan_folders") or [], known)

        new, seen = 0, set()
        with lib.lock:
            for ig in found:
                mname = self.manifest.match_installed(ig.store, ig.store_id, ig.name, ig.install_dir)
                gid = f"{ig.store}:{ig.store_id}" if ig.store_id else f"{ig.store}:{norm(ig.name)}"
                if gid in seen:
                    continue
                seen.add(gid)
                rec = lib.get(gid)
                if rec is None:
                    rec = new_record(gid, ig.name, ig.store, ig.store_id, ig.install_dir, mname)
                    self._absorb_found(rec)
                    lib.add(rec)
                    new += 1
                else:
                    rec["install_dir"] = ig.install_dir
                    rec["installed"] = True
                    if not rec.get("manifest_locked"):
                        rec["manifest_name"] = mname
            self.events.busy.emit("Procurando jogos do RPCS3 (PS3)…")
            for game in emulators.detect_rpcs3_games(self.settings.get("scan_folders") or []):
                gid = "rpcs3:" + game.title_id
                seen.add(gid)
                pattern = emulators.save_pattern(game.title_id)
                rec = lib.get(gid)
                if rec is None:
                    rec = new_record(gid, game.name, "rpcs3", game.title_id)
                    rec["manifest_locked"] = True     # não é jogo de PC: não procura no banco do Ludusavi
                    lib.add(rec)
                    new += 1
                rec.update(name=game.name, emu_root=game.hdd0, cover_file=game.icon, installed=True)
                if pattern not in rec["custom_paths"]:
                    rec["custom_paths"] = [pattern] + rec["custom_paths"]
            for rec in lib.all():
                if rec["store"] in SCANNED_STORES and rec["id"] not in seen:
                    if not rec["enabled"] and not rec["sync"] and not rec["custom_paths"]:
                        lib.games.pop(rec["id"], None)   # desinstalado e nunca usado: some da lista
                        self.status.pop(rec["id"], None)
                    else:
                        rec["installed"] = False
            if deep:
                self.events.busy.emit("Procurando saves de outros jogos (avulsos, emuladores)…")
                have = {r.get("manifest_name") for r in lib.all()}
                for mname in self.presence_scan(have):
                    gid = "found:" + norm(mname)
                    if lib.get(gid) is None:
                        rec = new_record(gid, mname, "found", manifest_name=mname)
                        rec["installed"] = False
                        lib.add(rec)
                        new += 1
            lib.save()
        log.info("Varredura concluída: %d jogos novos", new)
        self.events.library_changed.emit()
        return new

    def _absorb_found(self, rec):
        """Se o jogo já estava na lista só por ter save encontrado, herda as configurações."""
        if not rec.get("manifest_name"):
            return
        old = self.library.get("found:" + norm(rec["manifest_name"]))
        if old:
            rec.update(enabled=old["enabled"], sync=old["sync"], custom_paths=old["custom_paths"])
            self.library.games.pop(old["id"], None)
            self.status.pop(old["id"], None)

    def presence_scan(self, have):
        """Procura saves de qualquer jogo do banco que estejam em AppData/Documentos etc."""
        roots = dict(known_folders())
        broad = {os.path.normcase(v) for v in roots.values()}
        exists, found = {}, []
        for mname in self.manifest.games:
            if mname in have:
                continue
            for pattern in self.manifest.patterns(mname, None, saves_only=True):
                if "<base>" in pattern or "<root>" in pattern or "<game>" in pattern:
                    continue
                real = saves.expand(pattern, roots)
                if not real:
                    continue
                prefix = saves.literal_prefix(real)
                if os.path.normcase(prefix) in broad:
                    continue
                if prefix not in exists:
                    exists[prefix] = os.path.exists(prefix)
                if exists[prefix] and _any_file(real, prefix):
                    found.append(mname)
                    break
        log.info("Saves de outros jogos encontrados: %d", len(found))
        return found

    def add_manual(self, name, install_dir="", save_dir="", mname=None):
        mname = mname or self.manifest.find(name)
        rec = new_record("manual:" + uuid.uuid4().hex[:8], name, "manual", "", install_dir, mname)
        rec["manifest_locked"] = bool(mname)
        rec["custom_paths"] = [save_dir] if save_dir else []
        rec["enabled"] = True
        with self.library.lock:
            self._absorb_found(rec)
            self.library.add(rec)
            self.library.save()
        self.events.library_changed.emit()
        self.submit("Verificando save…", self.auto_sync, rec["id"])
        self.submit("Atualizando observador…", self.rebuild_watches)
        return rec

    def set_enabled(self, gid, enabled):
        self.library.update(gid, enabled=enabled)
        if enabled:
            self.submit("Verificando save…", self.auto_sync, gid)
        else:
            self.submit("Verificando save…", self.compute_status, gid)
        self.submit("Atualizando observador…", self.rebuild_watches)

    # ------------------------------------------------------------ capas

    def steam_id_for(self, rec):
        if rec["store"] == "steam" and rec["store_id"]:
            return rec["store_id"]
        return self.manifest.steam_id(rec.get("manifest_name")) if rec.get("manifest_name") else None

    def cover_for(self, rec):
        sid = self.steam_id_for(rec)
        if rec["store"] == "rpcs3":
            key = "rpcs3_" + rec["store_id"]
        else:
            key = covers.cover_key(sid, rec.get("manifest_name") or rec["name"])
        path = covers.cover_path(key)
        if path.exists():
            return str(path)
        if key not in self._cover_requested:
            self._cover_requested.add(key)
            self.cover_pool.submit(self._fetch_cover, rec["id"], key, sid, rec.get("manifest_name") or rec["name"],
                                   rec.get("cover_file", ""))
        return None

    def _fetch_cover(self, gid, key, sid, name, local_image=""):
        try:
            if covers.fetch(key, sid, name, self.settings.get("steamgriddb_key"), local_image):
                self.events.cover_ready.emit(gid)
        except Exception:
            log.exception("Falha ao baixar capa de %s", name)

    # ------------------------------------------------------------ Google Drive

    def drive_state(self):
        if self.drive.connected:
            return "connected"
        if self.drive_error:
            return self.drive_error
        if not self.drive.has_credentials_file():
            return "nocreds"
        return "notconnected" if not self.drive.has_token() else "offline"

    def _set_drive_error(self, code):
        if code:
            self.remote_ok = False
        self.drive_error = code
        self.events.drive_changed.emit()

    def connect_drive(self, interactive=False):
        if not interactive and not self.drive.has_token():
            self._set_drive_error("notconnected" if self.drive.has_credentials_file() else "nocreds")
            return False
        try:
            self.drive.folder_name = self.settings.get("drive_folder")
            self.drive.connect(interactive)
            self._set_drive_error("")
            return True
        except AuthRequired:
            self._set_drive_error("auth")
        except FileNotFoundError:
            self._set_drive_error("nocreds")
        except NETWORK_ERRORS as e:
            log.warning("Sem conexão com o Drive: %s", e)
            self._set_drive_error("offline")
        return False

    def connect_and_check(self):
        if self.connect_drive(interactive=True):
            self.refresh_and_check("manual")
            self.rebuild_watches()

    def disconnect_drive(self):
        self.drive.disconnect()
        self.remote.clear()
        self.remote_ok = False
        self._set_drive_error("notconnected")
        self.check("manual")

    def refresh_remote(self):
        if not self.drive.connected and not self.connect_drive():
            self.remote_ok = False
            return False
        try:
            self.remote = self.drive.list_saves()
            self.remote_ok = True
            self._set_drive_error("")
            return True
        except AuthRequired:
            self._set_drive_error("auth")
        except NETWORK_ERRORS as e:
            log.warning("Falha ao listar saves no Drive: %s", e)
            self._set_drive_error("offline")
        return False

    def _fetch_remote(self, rec, kh):
        rid = rec["sync"].get("remote_id")
        r = self.drive.get_save(rid) if rid else None
        if r is None or r.key != kh:
            r = self.drive.find_save(kh)
        if r:
            self.remote[kh] = r
        else:
            self.remote.pop(kh, None)

    # ------------------------------------------------------------ status

    def compute_status(self, gid, fresh=False):
        rec = self.library.get(gid)
        if rec is None:
            return None
        st = GameStatus()
        kh = game_key_hash(game_key(rec))
        if fresh and self.remote_ok:
            try:
                self._fetch_remote(rec, kh)
            except NETWORK_ERRORS:
                self._set_drive_error("offline")
        st.remote = self.remote.get(kh) if self.remote_ok else None
        st.files = saves.find_files(rec, self.manifest, self.settings.get("include_config"), self.steam_root)
        st.local_size = sum(f.size for f in st.files)
        st.local_mtime = max((f.mtime for f in st.files), default=0.0)
        base = rec["sync"].get("base_hash")

        if st.files and (rec["enabled"] or st.remote):
            try:
                st.local_hash = saves.save_hash(st.files, self.hashes)
            except OSError as e:
                st.state, st.message = ERROR, f"Não consegui ler um arquivo do save: {e.strerror or e}"
                return self._publish(gid, st)

        if not self.remote_ok:
            if not st.files:
                st.state = NOSAVE
            elif rec["enabled"] and self.drive_error == "offline":
                st.state = OFFLINE
            else:
                st.state = LOCAL
        elif not st.files and not st.remote:
            st.state = NOSAVE
        elif not st.files:
            st.state = DOWNLOAD
        elif not rec["enabled"] and not st.remote:
            st.state = LOCAL
        elif not st.remote:
            st.state = UPLOAD
        elif st.local_hash == st.remote.hash:
            st.state = SYNCED
            if base != st.local_hash or rec["sync"].get("remote_id") != st.remote.id:
                self.library.update_sync(gid, base_hash=st.local_hash, remote_id=st.remote.id)
        elif st.remote.hash == base:
            st.state = UPLOAD
        elif st.local_hash == base:
            st.state = DOWNLOAD
        else:
            st.state = CONFLICT

        if st.state == UPLOAD and st.local_size > self.settings.get("max_save_mb") * 1024 * 1024:
            st.state = TOOBIG
            st.message = f"O save tem {st.local_size / 1048576:.0f} MB, acima do limite configurado."
        return self._publish(gid, st)

    def _publish(self, gid, st):
        self.status[gid] = st
        self.events.status_changed.emit(gid)
        return st

    def _mark(self, gid, state):
        st = self.status.get(gid) or GameStatus()
        st.state = state
        self._publish(gid, st)

    def check(self, source="manual"):
        """Recalcula o status de todos os jogos e avisa quais precisam de confirmação."""
        self.events.busy.emit("Verificando saves…")
        pending, keys = [], set()
        for rec in self.library.all():
            if rec.get("hidden"):
                continue
            kh = game_key_hash(game_key(rec))
            if self.remote_ok and not rec["enabled"] and kh in self.remote:
                # backup ligado em outro PC: liga aqui também
                self.library.update(rec["id"], save=False, enabled=True)
            st = self.compute_status(rec["id"])
            if rec["enabled"] and st.state in PENDING_STATES and kh not in keys:
                keys.add(kh)
                pending.append(rec["id"])
        self.library.save()
        self.events.pending.emit(pending, source)
        return pending

    # ------------------------------------------------------------ envio / download

    def upload(self, gid, force=False):
        rec = self.library.get(gid)
        st = self.compute_status(gid, fresh=True)
        if not self.remote_ok:
            raise RuntimeError("Sem conexão com o Google Drive.")
        if not st.files:
            raise RuntimeError(f"{rec['name']}: nenhum arquivo de save encontrado.")
        if st.state == SYNCED:
            return
        if st.state == CONFLICT and not force:
            raise RuntimeError(f"{rec['name']}: conflito, escolha qual save manter.")
        if st.state == TOOBIG and not force:
            raise RuntimeError(f"{rec['name']}: {st.message}")
        kh = game_key_hash(game_key(rec))
        self._mark(gid, BUSY)
        zip_path = TEMP_DIR / f"up_{kh}.zip"
        name = rec["name"]
        try:
            started = time.time()
            log.info("Envio de %s: %d arquivos, %.1f MB (estado %s)", name, len(st.files), st.local_size / 1048576, st.state)
            self.events.busy.emit(f"Compactando {name} ({st.local_size / 1048576:.0f} MB)…")
            digest = saves.build_zip(st.files, zip_path, name)
            log.info("Zip de %s pronto: %.1f MB em %.0fs", name, zip_path.stat().st_size / 1048576, time.time() - started)
            self.events.busy.emit(f"Enviando {name}…")
            remote = self.drive.upload(kh, name, zip_path, digest, st.remote.id if st.remote else None,
                                       progress=_Speed(self.events, f"Enviando {name}", zip_path.stat().st_size))
        except BaseException:
            self.compute_status(gid)
            raise
        finally:
            _remove_quietly(zip_path)
        self.remote[kh] = remote
        self.library.update_sync(gid, base_hash=digest, remote_id=remote.id, last_sync=time.time(), last_action="upload")
        elapsed = max(time.time() - started, 0.1)
        log.info("Enviado: %s (%d arquivos, %.1f MB) em %.0fs", rec["name"], len(st.files),
                 remote.size / 1048576, elapsed)
        self.compute_status(gid)

    def download(self, gid):
        rec = self.library.get(gid)
        st = self.compute_status(gid, fresh=True)
        if not self.remote_ok:
            raise RuntimeError("Sem conexão com o Google Drive.")
        if not st.remote:
            raise RuntimeError(f"{rec['name']}: não há save deste jogo na nuvem.")
        kh = game_key_hash(game_key(rec))
        self._mark(gid, BUSY)
        zip_path = TEMP_DIR / f"down_{kh}.zip"
        name = rec["name"]
        try:
            self.drive.download(st.remote.id, zip_path,
                                progress=_Speed(self.events, f"Baixando {name}", st.remote.size))
            self.events.busy.emit(f"Restaurando {name}…")
            if st.files:
                self._local_backup(rec, st.files)
            self._suppress_until[gid] = time.time() + 60
            saves.extract_zip(zip_path, saves.roots_for(rec, self.steam_root), st.files)
        except BaseException:
            self.compute_status(gid)
            raise
        finally:
            _remove_quietly(zip_path)
        self.library.update_sync(gid, base_hash=st.remote.hash, remote_id=st.remote.id,
                                 last_sync=time.time(), last_action="download")
        log.info("Baixado: %s", rec["name"])
        self.compute_status(gid)

    def _local_backup(self, rec, files):
        """Cópia do save local antes de ser substituído pelo da nuvem."""
        safe = re.sub(r'[\\/:*?"<>|]', "", rec["name"]).strip() or rec["id"].replace(":", "_")
        folder = BACKUPS_DIR / safe
        folder.mkdir(parents=True, exist_ok=True)
        saves.build_zip(files, folder / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.zip", rec["name"])
        keep = max(1, int(self.settings.get("local_backups_keep")))
        for old in sorted(folder.glob("*.zip"))[:-keep]:
            old.unlink(missing_ok=True)

    def apply(self, actions):
        """actions: [(gid, 'upload'|'download')] vindos da janela de confirmação."""
        done, errors = 0, []
        for gid, action in actions:
            rec = self.library.get(gid)
            if not rec:
                continue
            self.events.busy.emit(f"{'Enviando' if action == 'upload' else 'Baixando'} {rec['name']}…")
            try:
                if action == "upload":
                    self.upload(gid, force=True)
                else:
                    self.download(gid)
                done += 1
            except AuthRequired:
                raise
            except Exception as e:
                log.exception("Falha em %s %s", action, rec["name"])
                errors.append(f"{rec['name']}: {describe_error(e)}")
        if errors:
            self.events.error.emit("Alguns saves falharam:\n" + "\n".join(errors))
        elif done:
            self.events.notify.emit("SaveSync", f"{done} save(s) sincronizado(s) com sucesso.")

    # ------------------------------------------------------------ observador de pastas

    def rebuild_watches(self):
        include_config = self.settings.get("include_config")
        mapping = {}
        for rec in self.library.all():
            if rec["enabled"] and not rec.get("hidden"):
                for d in saves.watch_dirs(rec, self.manifest, include_config, self.steam_root):
                    mapping.setdefault(os.path.normcase(d), set()).add(rec["id"])
        self._watch_map = mapping
        tops = []
        for d in sorted(mapping, key=len):
            if not any(d.startswith(t + "\\") for t in tops):
                tops.append(d)
        if self.observer:
            self.observer.stop()
            self.observer.join(3)
        self.observer = Observer()
        for top in tops:
            try:
                self.observer.schedule(self._handler, top, recursive=True)
            except OSError as e:
                log.warning("Não consegui vigiar %s: %s", top, e)
        self.observer.daemon = True
        self.observer.start()
        log.info("Vigiando %d pastas de %d jogos", len(tops), len({g for s in mapping.values() for g in s}))

    def on_fs_event(self, path):
        low = os.path.normcase(path)
        if low.endswith((".savesync-tmp", ".part")):
            return
        for d, gids in self._watch_map.items():
            if low == d or low.startswith(d + "\\"):
                for gid in gids:
                    self._schedule(gid)

    def _schedule(self, gid, delay=None):
        if self.settings.get("paused") or time.time() < self._suppress_until.get(gid, 0):
            return
        with self._timer_lock:
            old = self._timers.get(gid)
            if old:
                old.cancel()
            t = threading.Timer(delay or self.settings.get("debounce_seconds"), self._fire, args=(gid,))
            t.daemon = True
            self._timers[gid] = t
            t.start()

    def _fire(self, gid):
        rec = self.library.get(gid)
        if rec:
            self.submit(f"Enviando save de {rec['name']}…", self.auto_sync, gid)

    def auto_sync(self, gid):
        """Chamado quando um save muda: envia sozinho se for seguro, senão avisa."""
        rec = self.library.get(gid)
        if not rec or not rec["enabled"]:
            return
        if not self.remote_ok and not self.refresh_remote():
            self.compute_status(gid)
            return
        st = self.compute_status(gid, fresh=True)
        if st.state == UPLOAD:
            try:
                self.upload(gid)
                self.events.notify.emit("Save enviado", f"{rec['name']}: backup atualizado no Google Drive ✓")
            except PermissionError:
                log.info("Save de %s em uso, tentando de novo em 60 s", rec["name"])
                self._schedule(gid, delay=60)
        elif st.state in (CONFLICT, DOWNLOAD):
            self.events.notify.emit("Atenção", f"{rec['name']}: a nuvem tem um save diferente. Abra o SaveSync para decidir.")


class _Speed:
    """Mostra porcentagem, velocidade e tempo restante; registra a velocidade real no log."""

    def __init__(self, events, label, total_bytes):
        self.events, self.label, self.total = events, label, max(total_bytes, 1)
        self.start = time.time()

    def __call__(self, fraction):
        elapsed = max(time.time() - self.start, 0.1)
        speed = fraction * self.total / elapsed / 1048576
        remaining = (1 - fraction) * self.total / 1048576 / speed if speed > 0 else 0
        eta = f"faltam {remaining / 60:.0f} min" if remaining >= 90 else f"faltam {remaining:.0f} s"
        self.events.busy.emit(f"{self.label}… {fraction:.0%} · {speed:.1f} MB/s · {eta}")
        log.info("%s: %.0f%% a %.1f MB/s", self.label, fraction * 100, speed)


def _remove_quietly(path):
    """Apagar o temporário nunca pode esconder o erro (ou o sucesso) do envio."""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.warning("Não consegui apagar o temporário %s: %s", path, e)


def _any_file(real, prefix):
    if real == prefix:
        if os.path.isfile(real):
            return True
        for _, _, files in os.walk(real):
            if files:
                return True
        return False
    for match in islice(glob.iglob(saves._escape_brackets(real), recursive=True, include_hidden=True), 20):
        if os.path.isfile(match) or (os.path.isdir(match) and _any_file(match, match)):
            return True
    return False

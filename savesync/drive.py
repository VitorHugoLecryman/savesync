"""Integração com o Google Drive.

Usa o escopo 'drive.file': o app só enxerga os arquivos que ele mesmo criou, nunca o
resto do seu Drive. Cada jogo vira um único .zip na pasta SaveSync; ao atualizar, o
mesmo arquivo é substituído e o Drive guarda as versões anteriores por ~30 dias.
"""
import hashlib
import logging
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload, build_http

from .config import APP_DIR, MACHINE

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_PATH = APP_DIR / "credentials.json"     # credencial configurada pelo próprio usuário
# credencial embutida no instalador (build_exe.ps1); dispensa a configuração no Google Cloud
BUNDLED_CREDENTIALS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "credentials.json"


def make_http():
    """Conexão HTTP como a biblioteca do Google espera.

    O Drive responde 308 ("continue enviando") a cada parte de um envio grande. O httplib2 puro
    entende 308 como redirecionamento e falha com "Redirected but the response is missing a
    Location header"; o build_http() do Google desliga isso.
    """
    http = build_http()
    http.timeout = 120
    return http


def credentials_path():
    """A do usuário tem prioridade; senão usa a embutida no programa."""
    if CREDENTIALS_PATH.exists():
        return CREDENTIALS_PATH
    if BUNDLED_CREDENTIALS.exists():
        return BUNDLED_CREDENTIALS
    return None
TOKEN_PATH = APP_DIR / "token.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = "id,name,size,modifiedTime,appProperties"
# partes de 64 MB: em saves grandes, menos idas e voltas ao Google (cada parte espera uma confirmação)
CHUNK = 64 << 20

# Erros de rede que significam "sem internet agora", não "deu ruim de verdade"
NETWORK_ERRORS = (httplib2.HttpLib2Error, TransportError, OSError, TimeoutError)


def describe_error(e):
    """Traduz os erros mais comuns da API do Drive para algo que dê para entender."""
    text = str(e)
    if "storageQuotaExceeded" in text or "quotaExceeded" in text:
        return "O Google Drive está cheio. Libere espaço no Drive (ou desligue o backup de jogos com saves grandes)."
    if "accessNotConfigured" in text or "has not been used in project" in text:
        return "A Google Drive API não está ativada no projeto do Google Cloud."
    if "rateLimitExceeded" in text or "userRateLimitExceeded" in text:
        return "O Google pediu para esperar um pouco (muitos envios seguidos). Tente de novo em alguns minutos."
    return text


class AuthRequired(Exception):
    """O login no Google expirou ou foi revogado."""


@dataclass
class RemoteSave:
    id: str
    key: str
    hash: str
    saved_at: float
    machine: str
    size: int
    name: str


def game_key_hash(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()


def _to_remote(f) -> RemoteSave:
    p = f.get("appProperties") or {}
    try:
        saved_at = float(p.get("saved_at", 0))
    except ValueError:
        saved_at = 0.0
    return RemoteSave(f["id"], p.get("gk", ""), p.get("hash", ""), saved_at,
                      p.get("machine", "?"), int(f.get("size") or 0), f.get("name", ""))


class DriveClient:
    def __init__(self, folder_name="SaveSync"):
        self.folder_name = folder_name
        self.service = None
        self.root_id = None
        self.email = None

    # ------------------------------------------------------------ conexão

    @staticmethod
    def has_credentials_file():
        return credentials_path() is not None

    @staticmethod
    def has_token():
        return TOKEN_PATH.exists()

    @property
    def connected(self):
        return self.service is not None

    def connect(self, interactive=False):
        """Conecta usando o token salvo. Com interactive=True abre o navegador para login."""
        creds = None
        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except ValueError:
                creds = None
        if creds and not creds.valid and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                log.warning("Token do Google expirou/revogado")
                creds = None
        if not creds or not creds.valid:
            if not interactive:
                self.service = None
                raise AuthRequired()
            creds_file = credentials_path()
            if creds_file is None:
                raise FileNotFoundError("credentials.json não encontrado")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
            creds = flow.run_local_server(
                port=0, prompt="consent", open_browser=True,
                authorization_prompt_message="",
                success_message="Pronto! O SaveSync foi conectado ao seu Google Drive. Pode fechar esta aba.")
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        http = google_auth_httplib2.AuthorizedHttp(creds, http=make_http())
        self.service = build("drive", "v3", http=http, cache_discovery=False)
        about = self.service.about().get(fields="user(emailAddress)").execute()
        self.email = about.get("user", {}).get("emailAddress")
        self.root_id = self._ensure_root()
        log.info("Google Drive conectado: %s", self.email)
        return True

    def disconnect(self):
        self.service = None
        self.root_id = None
        self.email = None
        try:
            TOKEN_PATH.unlink()
        except FileNotFoundError:
            pass

    def _call(self, request):
        try:
            return request.execute(num_retries=2)
        except RefreshError as e:
            self.service = None
            raise AuthRequired() from e

    def _ensure_root(self):
        q = (f"mimeType='{FOLDER_MIME}' and name='{self.folder_name}' and trashed=false "
             f"and 'root' in parents")
        found = self._call(self.service.files().list(q=q, fields="files(id)", pageSize=10)).get("files", [])
        if found:
            return found[0]["id"]
        meta = {"name": self.folder_name, "mimeType": FOLDER_MIME,
                "description": "Backups de saves de jogos feitos pelo SaveSync"}
        return self._call(self.service.files().create(body=meta, fields="id"))["id"]

    # ------------------------------------------------------------ arquivos

    def list_saves(self) -> dict:
        """Todos os saves na nuvem: {hash_da_chave_do_jogo: RemoteSave}."""
        out, token = {}, None
        while True:
            resp = self._call(self.service.files().list(
                q=f"'{self.root_id}' in parents and trashed=false",
                fields=f"nextPageToken,files({FIELDS})", pageSize=1000, pageToken=token))
            for f in resp.get("files", []):
                r = _to_remote(f)
                if r.key:
                    prev = out.get(r.key)
                    if prev is None or r.saved_at > prev.saved_at:
                        out[r.key] = r
            token = resp.get("nextPageToken")
            if not token:
                return out

    def get_save(self, file_id):
        try:
            f = self._call(self.service.files().get(fileId=file_id, fields=FIELDS + ",trashed"))
        except HttpError as e:
            if e.resp.status == 404:
                return None
            raise
        return None if f.get("trashed") else _to_remote(f)

    def find_save(self, key_hash):
        resp = self._call(self.service.files().list(
            q=(f"'{self.root_id}' in parents and trashed=false and "
               f"appProperties has {{ key='gk' and value='{key_hash}' }}"),
            fields=f"files({FIELDS})", pageSize=10))
        saves = [_to_remote(f) for f in resp.get("files", [])]
        return max(saves, key=lambda r: r.saved_at) if saves else None

    def upload(self, key_hash, display_name, zip_path, digest, existing_id=None, progress=None) -> RemoteSave:
        safe = "".join(c for c in display_name if c not in '\\/:*?"<>|').strip() or "save"
        props = {"gk": key_hash, "hash": digest, "machine": MACHINE[:60],
                 "saved_at": f"{time.time():.3f}", "app": "savesync"}
        meta = {"name": f"{safe}.zip", "appProperties": props,
                "description": f"Save de {display_name} (SaveSync, enviado de {MACHINE})"}
        # o arquivo é aberto com 'with' para sempre ser fechado (senão o Windows não deixa apagar o .zip)
        with open(zip_path, "rb") as fh:
            if existing_id:
                try:
                    return self._send(fh, lambda media: self.service.files().update(
                        fileId=existing_id, body=meta, media_body=media, fields=FIELDS), progress)
                except HttpError as e:
                    if e.resp.status != 404:
                        raise
            meta["parents"] = [self.root_id]
            return self._send(fh, lambda media: self.service.files().create(
                body=meta, media_body=media, fields=FIELDS), progress)

    def _send(self, fh, make_request, progress):
        """Envio em partes de 16 MB (retomável), avisando o progresso."""
        fh.seek(0)
        media = MediaIoBaseUpload(fh, mimetype="application/zip", chunksize=CHUNK, resumable=True)
        request = make_request(media)
        response = None
        try:
            while response is None:
                status, response = request.next_chunk(num_retries=3)
                if status and progress:
                    progress(status.progress())
        except RefreshError as e:
            self.service = None
            raise AuthRequired() from e
        return _to_remote(response)

    def download(self, file_id, dest, progress=None):
        request = self.service.files().get_media(fileId=file_id)
        tmp = str(dest) + ".part"
        with open(tmp, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=CHUNK)
            done = False
            while not done:
                status, done = downloader.next_chunk(num_retries=3)
                if status and progress:
                    progress(status.progress())
        os.replace(tmp, dest)

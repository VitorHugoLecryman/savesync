# SaveSync

Backup automático de saves de jogos no Google Drive, para jogos que não têm nuvem própria.

- **Acha os jogos sozinho**: Steam, Epic, GOG, Ubisoft, pastas de jogos em todos os discos e saves
  de jogos avulsos/emuladores em AppData/Documentos.
- **Sabe onde cada jogo salva** usando o banco de dados aberto do
  [Ludusavi](https://github.com/mtkennerly/ludusavi-manifest) (feito a partir do PCGamingWiki, mais de 20 mil jogos).
- **Grade com capas** pequenas (~15 KB cada, em cache local).
- **Backup automático**: com a chave ligada, o save sobe para o Drive alguns segundos depois que o jogo grava.
- **Ao ligar o PC**: abre na bandeja, compara os saves locais com os do Drive e pede confirmação
  para o que estiver desatualizado (enviar, baixar ou resolver um conflito).
- **Emulador RPCS3 (PS3)**: acha o RPCS3 sozinho (é portátil, então procura nos discos, Área de Trabalho,
  Downloads e Documentos) e lista os jogos com nome e ícone. Os saves de `dev_hdd0\home\*\savedata` são
  agrupados pelo código do jogo (ex.: `BLUS30443`) e restauram certo mesmo com o RPCS3 em outra pasta.
- **Restaura em outro PC**: os caminhos são guardados de forma portável (usuário, pasta Documentos
  no OneDrive etc. podem ser diferentes).

## Instalar

Dê dois cliques em **`Instalador\SaveSync-Setup-<versão>.exe`** e siga o assistente. Não precisa ser administrador.
O instalador cria atalhos, pode ligar a abertura com o Windows e aparece em *Configurações → Aplicativos*
para desinstalar. Para atualizar, basta rodar um instalador mais novo por cima (seus jogos e a conexão
com o Drive são mantidos).

Para gerar o instalador de novo depois de mudar o código: `powershell -ExecutionPolicy Bypass -File build_installer.ps1`
(a versão vem de `savesync/__init__.py`).

Para rodar direto do código: `.venv\Scripts\python.exe main.py`

## Conectar o Google Drive (uma vez)

**Credencial embutida:** se houver um `client_secret_*.json` (tipo *App para computador*) na pasta do projeto,
o `build_exe.ps1` embute ele no programa. Quem instalar só clica em **Conectar Google Drive** e entra com a
própria conta; os saves de cada pessoa ficam no Drive dela. Enquanto o app estiver *em teste* no Google Cloud,
cada conta precisa estar em **Público-alvo → Usuários de teste** (e o login expira a cada 7 dias).
Não distribua publicamente um instalador com a credencial embutida.

Sem credencial embutida:

Clique em **Conectar Google Drive** no programa; a janela explica o passo a passo. Resumo:

1. [Google Cloud Console](https://console.cloud.google.com/) → criar projeto → ativar **Google Drive API**.
2. **Google Auth Platform** → configurar (público *Externo*) → em *Público-alvo* clicar em **Publicar app**
   (em modo de teste o login expira a cada 7 dias).
3. **Clientes → Criar cliente → App para computador** → baixar o JSON.
4. No SaveSync: **Selecionar credentials.json** → **Conectar** → autorizar no navegador.

O app usa o escopo `drive.file`: só enxerga os arquivos que ele mesmo criou (pasta **SaveSync** no Drive).

## Como a sincronização decide

Para cada jogo são comparados três "hashes" (impressões digitais do conteúdo dos arquivos):

| Situação | O que acontece |
|---|---|
| local = nuvem | sincronizado ✓ |
| só o local mudou desde a última sincronização | envia (automático quando o save muda; com confirmação ao ligar o PC) |
| só a nuvem mudou (jogou em outro PC) | pede para baixar |
| os dois mudaram | conflito: você escolhe qual manter |

Proteções contra perda de save:
- Antes de substituir um save local pelo da nuvem, uma cópia vai para `backups_locais` (mantém as 5 últimas).
- No Drive cada jogo é um único `.zip` que é *atualizado*; o Google Drive guarda as versões anteriores
  por ~30 dias (botão direito no arquivo → Gerenciar versões).
- Conflitos nunca são resolvidos sozinhos.
- Limite de tamanho por jogo (padrão 1 GB) contra padrões que pegariam arquivos demais.

## Onde ficam os dados

`%LOCALAPPDATA%\SaveSync`: configurações, lista de jogos, capas, token do Google, log (`savesync.log`)
e backups locais.

## Estrutura do código

| Arquivo | Função |
|---|---|
| `main.py` | ponto de entrada (`--startup` = modo inicialização do Windows) |
| `savesync/detect.py` | detecção de jogos (launchers + varredura de discos) |
| `savesync/emulators.py` | emulador RPCS3 (PS3): jogos, `PARAM.SFO` e pastas de save |
| `savesync/manifest.py` | banco de dados de locais de save (Ludusavi) |
| `savesync/saves.py` | localizar arquivos, hash, zip com caminhos portáveis |
| `savesync/drive.py` | Google Drive API |
| `savesync/engine.py` | comparação, envio/download, observador de pastas |
| `savesync/covers.py` | capas (Steam / SteamGridDB) |
| `savesync/ui/` | interface (PySide6) |
| `index.html`, `privacidade.html` | página inicial e política de privacidade (GitHub Pages) exigidas pela tela de consentimento OAuth do Google — **não mover nem renomear**, os endereços estão cadastrados no Google Cloud |

Programa irmão: **[Vitrine](https://github.com/VitorHugoLecryman/Vitrine)** coloca jogos de fora da Steam na
biblioteca da Steam com artes (usa uma cópia da detecção de jogos daqui).

## Limitações

- Saves guardados no **registro do Windows** (poucos jogos) não são copiados, só arquivos.
- Jogos do **Xbox/Game Pass** usam saves protegidos e não são suportados.
- RPCS3: só os saves são copiados; troféus (`dev_hdd0\home\*\trophy`) não. Se o RPCS3 estiver numa pasta
  sem "rpcs3" no nome, use **Procurar jogos → Procurar jogos em uma pasta…** e escolha a pasta dele.
- Jogos que não estão no banco de dados precisam que você indique a pasta do save (botão **+ Pasta de save…**).

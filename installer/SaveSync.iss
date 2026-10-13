; Instalador do SaveSync (Inno Setup 6). Gerado por build_installer.ps1.
#define AppName "SaveSync"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6C2E8B4A-3F1D-4E7A-9B52-5A7E5C0D0001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=SaveSync
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\SaveSync
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
; instala só para o usuário atual: não pede senha de administrador
PrivilegesRequired=lowest
OutputDir=..\Instalador
OutputBaseFilename=SaveSync-Setup-{#AppVersion}
SetupIconFile=..\assets\savesync.ico
UninstallDisplayIcon={app}\SaveSync.exe
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=..\assets\wizard_side_1x.bmp,..\assets\wizard_side_2x.bmp
WizardSmallImageFile=..\assets\wizard_small_1x.bmp,..\assets\wizard_small_2x.bmp
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=force
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"
Name: "autostart"; Description: "Abrir o SaveSync quando o Windows iniciar (recomendado)"; GroupDescription: "Inicialização:"

[Files]
Source: "..\dist\SaveSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; remove arquivos da versão anterior antes de copiar a nova
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\SaveSync.exe"; Comment: "Backup de saves de jogos no Google Drive"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SaveSync.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SaveSync"; \
    ValueData: """{app}\SaveSync.exe"" --startup"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\SaveSync.exe"; Description: "Abrir o SaveSync agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im SaveSync.exe"; Flags: runhidden; RunOnceId: "FecharSaveSync"

[Code]
// Fecha o SaveSync (que pode estar na bandeja) antes de substituir os arquivos.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im SaveSync.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if ResultCode = 0 then
    Sleep(1500);
  Result := '';
end;

// Ao desinstalar, pergunta se apaga também configurações, capas e backups locais.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    // a opção "abrir com o Windows" também pode ter sido ligada pelo próprio app
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SaveSync');
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Apagar também as configurações, a lista de jogos e os backups locais do SaveSync?' + #13#10 + #13#10 +
              '(Os saves que estão no Google Drive não são apagados.)',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\SaveSync'), True, True, True);
end;

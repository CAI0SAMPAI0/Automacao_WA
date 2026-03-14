; ═══════════════════════════════════════════════════════════════
;  Study Practices — Instalador Inno Setup
;  • Instala por usuário (não precisa de admin)
;  • NÃO apaga dados existentes (perfil, banco, agendamentos)
;  • Nome fixo do exe: Study_Practices.exe
;  • Visual moderno com wizard customizado
; ═══════════════════════════════════════════════════════════════

#define MyAppName      "Study Practices"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "Taty's English"
#define MyAppExeName   "Study_Practices.exe"
#define MyAppURL       "https://github.com/CAI0SAMPAI0/playwright"

[Setup]
; ── identidade ──────────────────────────────────────────────────
AppId                    = {{8F3A2B1C-4D5E-6F7A-8B9C-0D1E2F3A4B5C}
AppName                  = {#MyAppName}
AppVersion               = {#MyAppVersion}
AppPublisher             = {#MyAppPublisher}
AppPublisherURL          = {#MyAppURL}
AppSupportURL            = {#MyAppURL}
AppUpdatesURL            = {#MyAppURL}
VersionInfoVersion       = {#MyAppVersion}

; ── instalação por usuário (sem UAC) ────────────────────────────
PrivilegesRequired        = lowest
PrivilegesRequiredOverridesAllowed = commandline

; ── destino padrão ───────────────────────────────────────────────
; {userdocs} = C:\Users\<Nome>\Documents
DefaultDirName            = {userdocs}\Study_Practices
DefaultGroupName          = {#MyAppName}
DisableProgramGroupPage   = yes

; ── comportamento de atualização ────────────────────────────────
; Não desinstala a versão anterior automaticamente, apenas sobrescreve o exe
DontMergeUninstallDeleteFiles = yes

; ── visual ───────────────────────────────────────────────────────
WizardStyle              = modern
WizardSizePercent        = 110

; Cores do wizard (fundo do painel esquerdo)
WizardImageFile          = compiler:WizModernImage.bmp
WizardSmallImageFile     = compiler:WizModernSmallImage.bmp

; ── saída ────────────────────────────────────────────────────────
OutputDir                = dist
OutputBaseFilename       = Study_Practices_Setup
Compression              = lzma2/ultra64
SolidCompression         = yes

; ── ícone ────────────────────────────────────────────────────────
; Descomente e ajuste o caminho se tiver o .ico disponível:
; SetupIconFile          = resources\Taty_s-English-Logo.ico
; UninstallDisplayIcon   = {app}\Study_Practices.exe

; ── outros ───────────────────────────────────────────────────────
AllowNoIcons             = yes
ChangesEnvironment       = no
CloseApplications        = yes

[Languages]
Name: "portuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na &Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
; ── executável principal ─────────────────────────────────────────
; Copia o .exe com nome FIXO para que o agendador sempre encontre
Source: "dist\Study_Practices.exe"; DestDir: "{app}"; DestName: "Study_Practices.exe"; Flags: ignoreversion

; ── recursos opcionais ───────────────────────────────────────────
; Se seu build for onedir (pasta _internal), inclua também:
; Source: "dist\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; \
  Description: "Iniciar {#MyAppName} agora"; \
  Flags: nowait postinstall skipifsilent

; ═══════════════════════════════════════════════════════════════
;  PRESERVAÇÃO DE DADOS DO USUÁRIO
;  Estas pastas NÃO são tocadas na instalação nem na desinstalação
; ═══════════════════════════════════════════════════════════════
[UninstallDelete]
; Remove APENAS o executável e atalhos, NÃO os dados do usuário
Type: files;      Name: "{app}\Study_Practices.exe"
Type: dirifempty; Name: "{app}"

; As pastas abaixo são propositalmente OMITIDAS do UninstallDelete:
;   {app}\perfil_bot_whatsapp\   ← sessão WhatsApp (QR Code)
;   {app}\user_data\             ← banco SQLite de agendamentos
;   {app}\logs\                  ← histórico de execuções
;   {app}\scheduled_tasks\       ← arquivos .bat/.vbs/.json

[Code]
{ ──────────────────────────────────────────────────────────────
  Código Pascal para:
  1. Detectar instalação existente e exibir mensagem amigável
  2. Garantir que o exe antigo não esteja em execução
────────────────────────────────────────────────────────────── }

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  sInstDir: String;
begin
  if CurStep = ssInstall then
  begin
    sInstDir := WizardDirValue();
    { Garante que as pastas de dados existam antes de instalar }
    ForceDirectories(sInstDir + '\user_data');
    ForceDirectories(sInstDir + '\logs');
    ForceDirectories(sInstDir + '\perfil_bot_whatsapp');
    ForceDirectories(sInstDir + '\scheduled_tasks');
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if IsUpgrade() then
  begin
    MsgBox(
      'Uma instalação anterior do Study Practices foi detectada.' + #13#10 +
      'Seus dados (agendamentos, sessão WhatsApp) serão preservados.' + #13#10#13#10 +
      'O instalador irá atualizar apenas o executável.',
      mbInformation,
      MB_OK
    );
  end;
end;

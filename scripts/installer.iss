; =============================================================================
; Inno Setup Script - CMaker Photo Commander
; Instalador Standalone Oficial para Windows 10/11
; =============================================================================

#define MyAppName "CMaker Photo Commander"
#define MyAppVersion "2.8.0"
#define MyAppPublisher "Espaço CMaker"
#define MyAppURL "https://github.com/cmaker/photo-commander"
#define MyAppExeName "CMakerPhotoCommander.exe"

[Setup]
AppId={{E680E74C-4D2A-4C2E-B9D1-72A0D8198944}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\CMakerPhotoCommander
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=Instalador_CMakerPhotoCommander_v2.8.0
SetupIconFile=..\assets\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=2.8.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductVersion=2.8.0.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Executável principal
Source: "..\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Atalho batch e ícones
Source: "..\iniciar_app.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; Vídeos de animação
Source: "..\anim\*"; DestDir: "{app}\anim"; Flags: ignoreversion recursesubdirs createallsubdirs

; Configuração padrão inicial (não sobrescreve se o usuário já tiver seu config.json configurado)
Source: "..\config.example.json"; DestDir: "{app}"; DestName: "config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\app_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent


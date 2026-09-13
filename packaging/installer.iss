; =====================================================================
; FaceScan installer (Inno Setup 6.x)
; Build with: ISCC.exe packaging/installer.iss
; Requires dist\FaceScan (PyInstaller output) to be built first.
; =====================================================================

#define AppName "FaceScan"
#define AppVersion "1.0.0"
#define AppPublisher "FaceScan"
#define AppExeName "FaceScan.exe"

[Setup]
AppId={{E8C9F2A1-7D3B-4E6A-9B1C-5F2D8A4C1E3F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=FaceScan-Setup-{#AppVersion}
SetupIconFile=assets\facescan.ico
WizardImageFile=assets\wizard_sidebar.bmp
WizardSmallImageFile=assets\wizard_banner.bmp
LicenseFile=LICENSE.txt
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
LanguageDetectionMethod=uilanguage

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full";    Description: "Completa / Full (incluye modelos faciales, 100% offline)"
Name: "compact"; Description: "Compacta / Compact (sin modelos; descarga en el primer uso)"
Name: "custom";  Description: "Personalizada / Custom"; Flags: iscustom

[Components]
Name: "main";   Description: "Aplicacion FaceScan"; Types: full compact custom; Flags: fixed
Name: "models"; Description: "Modelos faciales (buffalo_l, ~300 MB)"; Types: full custom

[Tasks]
Name: "desktopicon";  Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmanuals"; Description: "Crear accesos a los manuales / Add manual shortcuts"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\FaceScan\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "models"; Components: main
Source: "..\dist\FaceScan\_internal\models\*"; DestDir: "{app}\_internal\models"; Flags: recursesubdirs createallsubdirs; Components: models
Source: "manuales\programa_manual_es.md"; DestDir: "{app}\manuales"; Components: main
Source: "manuales\programa_manual_en.md"; DestDir: "{app}\manuales"; Components: main
Source: "LICENSE.txt"; DestDir: "{app}"; Components: main
Source: "assets\facescan.ico"; DestDir: "{app}"; Components: main

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\facescan.ico"
Name: "{autoprograms}\{#AppName} · Manual de usuario (ES)"; Filename: "{win}\notepad.exe"; Parameters: """{app}\manuales\programa_manual_es.md"""; Tasks: startmanuals
Name: "{autoprograms}\{#AppName} · User Manual (EN)"; Filename: "{win}\notepad.exe"; Parameters: """{app}\manuales\programa_manual_en.md"""; Tasks: startmanuals
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\facescan.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; User data (DB, photos, keys, logs) lives in %LOCALAPPDATA%\FaceScan
; and is preserved when the application is uninstalled.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal\models"
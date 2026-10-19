; clients/windows/packaging/installer.iss
; Inno Setup 6: інсталятор CNC-Robot Studio для Windows.
; Збірка (з каталогу clients/windows, після PyInstaller):
;   iscc /DAppVersion=1.0.0 packaging\installer.iss
; Результат: packaging\Output\CNC-Robot-Studio-Setup-<версія>.exe
; Встановлення для поточного користувача, права адміністратора не потрібні.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "CNC-Robot Studio"
#define AppExe "CNC-Robot Studio.exe"

[Setup]
AppId={{6B0E9F52-3C7A-4F1E-9D2B-8A51C4E0B7D3}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=CNC-Robot
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=CNC-Robot-Studio-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

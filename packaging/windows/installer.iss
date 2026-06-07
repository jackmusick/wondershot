; Inno Setup script — wraps the PyInstaller one-dir bundle.
;
; Build (after `pyinstaller packaging/windows/wondershot.spec`):
;   iscc packaging\windows\installer.iss /DAppVersion=0.1.0
; Silent install: WondershotSetup.exe /VERYSILENT /NORESTART
; The wondershot:// scheme registration below is what makes the
; OneDrive browser-redirect sign-in land on Windows.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define DistDir "..\..\dist\Wondershot"

[Setup]
AppId={{62AD3129-0C5E-4DC5-8082-9B2E376F27A1}
AppName=Wondershot
AppVersion={#AppVersion}
AppPublisher=Jack Musick
DefaultDirName={autopf}\Wondershot
DefaultGroupName=Wondershot
DisableProgramGroupPage=yes
OutputBaseFilename=WondershotSetup-{#AppVersion}
OutputDir=..\..\dist
SetupIconFile=wondershot.ico
UninstallDisplayIcon={app}\Wondershot.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes

[Tasks]
Name: "autostart"; Description: "Start Wondershot when Windows starts"; \
  GroupDescription: "Startup:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
  GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Wondershot"; Filename: "{app}\Wondershot.exe"
Name: "{autodesktop}\Wondershot"; Filename: "{app}\Wondershot.exe"; \
  Tasks: desktopicon

[Registry]
; wondershot:// URL scheme (OneDrive auth-code redirect handler)
Root: HKA; Subkey: "Software\Classes\wondershot"; \
  ValueType: string; ValueData: "URL:Wondershot"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\wondershot"; \
  ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\wondershot\shell\open\command"; \
  ValueType: string; ValueData: """{app}\Wondershot.exe"" ""%1"""
; Autostart (per-user Run key; tray app)
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "Wondershot"; \
  ValueData: """{app}\Wondershot.exe"""; Flags: uninsdeletevalue; \
  Tasks: autostart

[Run]
Filename: "{app}\Wondershot.exe"; Description: "Launch Wondershot"; \
  Flags: nowait postinstall skipifsilent

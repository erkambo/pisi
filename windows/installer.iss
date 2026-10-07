; Inno Setup script for PISI - compiled by windows\build.ps1 when Inno Setup 6
; is installed (https://jrsoftware.org/isdl.php). Per-user install, no admin.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C6A3F2E-5B1D-4E7A-9F3C-2D4B6A8E1C57}
AppName=PISI
AppVerName=PISI {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=Erkam Boyacioglu
AppComments=A desktop cat that keeps you company while you focus
DefaultDirName={localappdata}\Programs\PISI
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PISI-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\PISI.exe
UninstallDisplayName=PISI
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "..\dist\PISI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; a clean _internal each upgrade, so no stale modules linger
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
; same name the app itself would use (PISI.lnk), so it never makes a duplicate
Name: "{autoprograms}\PISI"; Filename: "{app}\PISI.exe"
Name: "{autodesktop}\PISI"; Filename: "{app}\PISI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PISI.exe"; Parameters: "--install"; Flags: runhidden waituntilterminated
Filename: "{app}\PISI.exe"; Description: "Start PISI now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; stop the running cat and remove its start-at-sign-in entry (keeps your data)
Filename: "{app}\PISI.exe"; Parameters: "--uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "PISIUninstall"

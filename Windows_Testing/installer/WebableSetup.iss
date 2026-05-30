; Inno Setup 6 script — Webable Windows installer (per-user, no admin by default).
; Build after PyInstaller: iscc installer\WebableSetup.iss

#define MyAppName "Webable"
#define MyAppPublisher "Webable"
#define MyAppURL "https://github.com/zeromeia0/webable"
#define MyAppExeName "Webable.exe"

; Read version from repo VERSION file at compile time via /DAppVersion= on command line,
; or default here:
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{A7B8C9D0-E1F2-3456-7890-ABCDEF123456}}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist\installer
OutputBaseFilename=Webable-Setup-{#AppVersion}
SetupIconFile=..\assets\webable.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=no
LicenseFile=
InfoBeforeFile=..\installer\welcome.txt
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Personal Finance (local)
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir output (dist\Webable\)
Source: "..\dist\Webable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; User data in %LOCALAPPDATA%\Webable is intentionally NOT removed (financial data safety).
Type: filesandordirs; Name: "{app}\logs"

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

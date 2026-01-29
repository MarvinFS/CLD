; CLD Installer Script for Inno Setup
; https://github.com/MarvinFS/ClaudeCli-Dictate

#define MyAppName "CLD"
#define MyAppVersion "0.5.1"
#define MyAppPublisher "MarvinFS"
#define MyAppURL "https://github.com/MarvinFS/Public/tree/main/ClaudeCli-Dictate"
#define MyAppExeName "CLD.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
AppId={{8F3B4A2D-7C1E-4D5F-9A8B-2C3D4E5F6A7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output settings
OutputDir=dist
OutputBaseFilename=CLD-{#MyAppVersion}-Setup
SetupIconFile=cld_icon.ico
; Compression
Compression=lzma2/ultra64
SolidCompression=yes
; Privileges - install for current user by default, allow elevation
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; UI
WizardStyle=modern
; Uninstaller
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start CLD when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main application
Source: "dist\CLD\CLD.exe"; DestDir: "{app}"; Flags: ignoreversion
; Internal folder with all dependencies
Source: "dist\CLD\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; Icon files for shortcuts
Source: "cld_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\cld_icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\cld_icon.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

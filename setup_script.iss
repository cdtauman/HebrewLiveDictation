; Inno Setup Script for Hebrew Live Dictation
; Standard User-Level (No UAC) Setup Wizard

#ifndef AppVersion
  #define AppVersion "1.0.0-beta"
#endif

[Setup]
AppName=Hebrew Live Dictation
AppVersion={#AppVersion}
AppPublisher=cdtauman
DefaultDirName={localappdata}\Programs\HebrewLiveDictation
DefaultGroupName=Hebrew Live Dictation
DisableProgramGroupPage=yes
OutputBaseFilename=HebrewLiveDictation_Setup_{#AppVersion}
OutputDir=dist
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
SetupIconFile=assets\app_icon.ico
UninstallDisplayIcon={app}\HebrewLiveDictation.exe
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hebrew"; MessagesFile: "compiler:Languages\Hebrew.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\HebrewLiveDictation\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Hebrew Live Dictation"; Filename: "{app}\HebrewLiveDictation.exe"
Name: "{userdesktop}\Hebrew Live Dictation"; Filename: "{app}\HebrewLiveDictation.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HebrewLiveDictation.exe"; Description: "{cm:LaunchProgram,Hebrew Live Dictation}"; Flags: nowait postinstall skipifsilent

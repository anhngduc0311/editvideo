#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
[Setup]
AppId={{34735A24-46EA-46D9-9D92-55FB51EF1DA3}
AppName=EditVideo Studio
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\EditVideoStudio
DefaultGroupName=EditVideo Studio
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=EditVideoStudio-Setup
Compression=zip/1
SolidCompression=no
WizardStyle=modern
DisableProgramGroupPage=yes
DisableWelcomePage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
UninstallDisplayIcon={app}\EditVideoStudio.exe
SetupLogging=yes
CloseApplications=yes

[Files]
Source: "..\dist\EditVideoStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\EditVideo Studio"; Filename: "{app}\EditVideoStudio.exe"
Name: "{group}\EditVideo Studio"; Filename: "{app}\EditVideoStudio.exe"

[Run]
Filename: "{app}\EditVideoStudio.exe"; Flags: nowait skipifsilent

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  { Inno keeps the Ready page when every earlier page is disabled. Queue the
    Install click after it is created, so a normal double-click installs. }
  if (CurPageID = wpReady) and not WizardSilent then
    PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0);
end;

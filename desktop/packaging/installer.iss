; Windows installer of the admin client (Inno Setup 6) — docs/desktop-windows.md.
; Built by packaging\build.ps1:  ISCC /DAppVersion=0.1.0 packaging\installer.iss
;
; - per-user install (no administrator rights): %LOCALAPPDATA%\Programs\School Managing Admin
; - Start menu shortcut, optional desktop shortcut, standard uninstall
; - first install only: the server page writes %APPDATA%\SchoolManagingDesktop\desktop.json
;   (never overwritten; the uninstall keeps it, and keeps the diagnostic log)
; - no service, no file association, no secret: the client signs in against the API

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=x.y.z installer.iss
#endif
#define AppName "School Managing Admin"
#define AppExe "SchoolManagingAdmin.exe"
#define DemoApi "https://isbree-api.onrender.com/api/v1/"

[Setup]
AppId={{DF914333-AB0C-4976-B780-8D8754DAFCDB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=School Managing
AppComments=Client d'administration de la plateforme School Managing (démonstration ISBREE)
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Installation du client d'administration School Managing
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist\installer
OutputBaseFilename=SchoolManagingAdmin-Setup-{#AppVersion}-x64
SetupIconFile=build\app-icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\SchoolManagingAdmin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ServerPage: TInputQueryWizardPage;

function ConfigFile(): String;
begin
  Result := ExpandConstant('{userappdata}\SchoolManagingDesktop\desktop.json');
end;

procedure InitializeWizard();
begin
  ServerPage := CreateInputQueryPage(wpSelectTasks,
    'Serveur', 'À quel serveur le client se connecte-t-il ?',
    'Adresse de l''API de la plateforme. Par défaut : le serveur public de démonstration ISBREE ' +
    '(hébergement gratuit : la première connexion peut prendre environ une minute). ' +
    'Vous pourrez la changer plus tard dans ' + ConfigFile() + '.');
  ServerPage.Add('Adresse de l''API :', False);
  ServerPage.Values[0] := '{#DemoApi}';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { An existing configuration is the user's: never asked again, never overwritten. }
  Result := (PageID = ServerPage.ID) and FileExists(ConfigFile());
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Url: String;
begin
  Result := True;
  if CurPageID = ServerPage.ID then
  begin
    Url := Trim(ServerPage.Values[0]);
    if (Pos('https://', Lowercase(Url)) <> 1) and (Pos('http://', Lowercase(Url)) <> 1) then
    begin
      MsgBox('L''adresse doit commencer par https:// (ou http:// pour un serveur local).', mbError, MB_OK);
      Result := False;
    end
    else if (Pos('"', Url) > 0) or (Pos('\', Url) > 0) or (Pos(' ', Url) > 0) then
    begin
      MsgBox('Cette adresse contient un caractère non autorisé.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Url: String;
begin
  if (CurStep = ssPostInstall) and not FileExists(ConfigFile()) then
  begin
    Url := Trim(ServerPage.Values[0]);
    if Copy(Url, Length(Url), 1) <> '/' then
      Url := Url + '/';
    ForceDirectories(ExtractFileDir(ConfigFile()));
    { timeout 75 s: the free demonstration host takes about a minute to wake up. }
    SaveStringToFile(ConfigFile(), '{"api_url": "' + Url + '", "timeout": 75}', False);
  end;
end;

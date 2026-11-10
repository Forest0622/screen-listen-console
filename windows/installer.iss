#define MyAppName "屏幕监听控制"
#define MyAppVersion "1.3.5"
#define MyAppExeName "ScreenListenConsole.exe"

[Setup]
AppId={{8C1F0B52-2A1E-4C7B-9A55-6C0F2D3E7A10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Forest0622
AppPublisherURL=https://github.com/Forest0622/screen-listen-console
DefaultDirName={autopf}\ScreenListenConsole
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=ScreenListenConsoleSetup-{#MyAppVersion}
SetupIconFile=assets\AppIcon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartIfNeededByRun=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // 安装前先杀掉正在运行的旧版本，避免文件被占用
  Exec('taskkill', '/f /im ScreenListenConsole.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

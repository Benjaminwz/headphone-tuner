; 耳機調音台 Windows 安裝程式（Inno Setup 6）
; 不要直接編譯這個檔案：執行 python installer\build.py v1.2.3，它會先下載 uv.exe、做好精靈圖片再呼叫 ISCC。
; 裝的時候不用系統管理員權限，預設裝在 %LOCALAPPDATA%\Programs\耳機調音台。
; 調音台專用的 Python 由 bootstrap.cmd 用 uv 下載到安裝資料夾裡，不會動到電腦裡其他的 Python。

#ifndef AppVersion
  #define AppVersion "dev"
#endif
#define AppName "耳機調音台"
#define Root ".."
#define PyW "{app}\.venv\Scripts\pythonw.exe"

[Setup]
#ifdef TESTBUILD
AppId={{A1D5E0B2-7E57-4C6B-8E1F-000000000000}
#else
AppId={{3F0C8B6E-5D2A-4E71-9A43-B7C2E1D4F695}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Benjaminwz
AppPublisherURL=https://github.com/Benjaminwz/headphone-tuner
AppSupportURL=https://github.com/Benjaminwz/headphone-tuner/issues
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; RedirectionGuard 會一路傳給安裝時跑的程式，害 uv 建不了 Python 的資料夾連結（錯誤 448）。
; 這個安裝程式不用管理員權限，本來就沒有它要防的提權風險，所以關掉。
RedirectionGuard=no
OutputDir=dist
OutputBaseFilename=HeadphoneTuner-Setup-{#AppVersion}
SetupIconFile={#Root}\tuner.ico
UninstallDisplayIcon={app}\tuner.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=build\wizard.bmp,build\wizard_2x.bmp
WizardSmallImageFile=build\wizard_small.bmp,build\wizard_small_2x.bmp
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "cht"; MessagesFile: "ChineseTraditional.isl"

[Messages]
WelcomeLabel2=這會在你的電腦上安裝 [name/ver]：繁體中文介面的耳機等化器。%n%n安裝時會自動下載調音台專用的 Python 和套件（約 60 MB），請保持網路連線。%n%n調音台靠免費的 Equalizer APO 處理聲音；還沒裝的話，最後一步會幫你打開下載頁面。
FinishedLabel=耳機調音台裝好了！%n%n第一次打開會請你選耳機，輸入型號就好。之後從開始功能表或桌面的「{#AppName}」打開。

[Tasks]
Name: "desktopicon"; Description: "在桌面建立「{#AppName}」捷徑"; GroupDescription: "捷徑："

[Files]
Source: "{#Root}\耳機調音台.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\tuner.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\說明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "bootstrap.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "uv\uv.exe"; DestDir: "{app}\bin"; Flags: ignoreversion

#ifndef TESTBUILD
[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{#PyW}"; Parameters: """{app}\耳機調音台.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\tuner.ico"; Comment: "繁體中文介面的耳機等化器"; AppUserModelID: "HeadphoneTuner.Panel"
Name: "{userdesktop}\{#AppName}"; Filename: "{#PyW}"; Parameters: """{app}\耳機調音台.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\tuner.ico"; Comment: "繁體中文介面的耳機等化器"; AppUserModelID: "HeadphoneTuner.Panel"; Tasks: desktopicon
#endif

[Run]
Filename: "{#PyW}"; Parameters: """{app}\耳機調音台.pyw"""; WorkingDir: "{app}"; Description: "打開耳機調音台"; Flags: postinstall nowait skipifsilent; Check: PythonReady
Filename: "https://sourceforge.net/projects/equalizerapo/"; Description: "打開 Equalizer APO 下載頁面（還沒安裝；裝的時候勾選你的耳機用的輸出裝置，裝完重新開機）"; Flags: postinstall shellexec skipifsilent; Check: NeedAPO

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\install-log.txt"

[Code]
var
  PythonOK: Boolean;

{ 關掉這個資料夾裡正在跑的調音台（只找 python，不會動到別的程式），更新或解除安裝時檔案才不會被占用 }
procedure StopTuner;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like ''python*'' -and $_.CommandLine -and $_.CommandLine.Contains(''' +
    ExpandConstant('{app}') + ''') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopTuner;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := '正在下載並設定調音台專用的 Python（第一次要等 1～3 分鐘）…';
    WizardForm.ProgressGauge.Style := npbstMarquee;
    PythonOK := Exec(ExpandConstant('{cmd}'), '/c ""' + ExpandConstant('{app}\bootstrap.cmd') + '""',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
    WizardForm.ProgressGauge.Style := npbstNormal;
    if not PythonOK then
      MsgBox('準備 Python 失敗了（代碼 ' + IntToStr(ResultCode) + '）。' + #13#10 +
        '請確認電腦有連上網路，再執行一次安裝程式。' + #13#10#13#10 +
        '詳細紀錄在：' + ExpandConstant('{app}\install-log.txt'), mbError, MB_OK);
  end;
end;

function PythonReady: Boolean;
begin
  Result := PythonOK;
end;

function NeedAPO: Boolean;
begin
  Result := not FileExists(ExpandConstant('{commonpf64}\EqualizerAPO\EqualizerAPO.dll'));
end;

{ 把 Equalizer APO 的設定恢復原狀（拿掉調音台的區塊），不然解除安裝後調音還會繼續生效 }
procedure RestoreAPO;
var
  ResultCode: Integer;
begin
  if FileExists(ExpandConstant('{app}\.venv\Scripts\python.exe')) then
    Exec(ExpandConstant('{app}\.venv\Scripts\python.exe'), '"' + ExpandConstant('{app}\耳機調音台.pyw') + '" --uninstall',
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ 路徑超過 260 字的檔案（裝在很深的資料夾時，Python 裡會有）一般方法刪不掉，用 PowerShell 的長路徑寫法補刪 }
procedure RemoveLongPaths;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -Command "foreach ($d in ''python'', ''.venv'') { $p = ''\\?\' + ExpandConstant('{app}') +
    '\'' + $d; if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue } }"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    StopTuner;
    RestoreAPO;
  end;
  if CurUninstallStep = usPostUninstall then
    RemoveLongPaths;
  if (CurUninstallStep = usPostUninstall) and DirExists(ExpandConstant('{app}')) then
    if MsgBox('要一起刪除你存的預設和耳機資料嗎？' + #13#10#13#10 +
      '之後想重新安裝繼續用的話，請按「否」。', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;

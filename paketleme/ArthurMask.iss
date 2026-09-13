; Arthur Mask kurulum paketi (Inno Setup 6)
; ISCC.exe /DSurum=1.0.0 /DKaynak=E:\arthur-mask-derleme\ArthurMask /OE:\arthur-mask-derleme paketleme\ArthurMask.iss

#ifndef Surum
  #define Surum "1.0.0"
#endif
#ifndef Kaynak
  #define Kaynak "E:\arthur-mask-derleme\ArthurMask"
#endif

[Setup]
AppId={{8F3C2B7E-4D1A-4E7B-9C55-A7D1E0B3F412}
AppName=Arthur Mask
AppVersion={#Surum}
AppVerName=Arthur Mask {#Surum}
AppPublisher=ArthurLegal
AppPublisherURL=https://github.com/beerbottle90/ArthurLegal
AppSupportURL=https://github.com/beerbottle90/ArthurLegal
AppUpdatesURL=https://github.com/beerbottle90/ArthurLegal/releases/tag/arthur-mask
DefaultDirName={localappdata}\Programs\Arthur Mask
DisableDirPage=yes
DefaultGroupName=Arthur Mask
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=ArthurMask-Kurulum
SetupIconFile={#Kaynak}\ArthurMask.ico
UninstallDisplayIcon={app}\ArthurMask.ico
UninstallDisplayName=Arthur Mask
LicenseFile={#Kaynak}\belgeler\LICENSE.txt
Compression=lzma2/normal
SolidCompression=yes
LZMANumBlockThreads=8
WizardStyle=modern
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "masaustu"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Kısayollar:"

[InstallDelete]
; Güncellemede eski sürümün kütüphaneleri ve derlenmiş modülü tamamen değiştirilir.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"

[Files]
Source: "{#Kaynak}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Arthur Mask"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-c ""import sys; from arthur_mask.baslat import main; sys.exit(main())"""; WorkingDir: "{app}"; IconFilename: "{app}\ArthurMask.ico"; Comment: "Belgeleri Claude'a göndermeden önce bu bilgisayarda maskeler"
Name: "{userdesktop}\Arthur Mask"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-c ""import sys; from arthur_mask.baslat import main; sys.exit(main())"""; WorkingDir: "{app}"; IconFilename: "{app}\ArthurMask.ico"; Tasks: masaustu
Name: "{userprograms}\Arthur Mask Kullanım Notları"; Filename: "{app}\belgeler\BENIOKU.md"

[Run]
Filename: "{app}\runtime\python.exe"; Parameters: "-c ""import sys; from arthur_mask.claude_ayari import main; sys.exit(main(['kaydet']))"""; WorkingDir: "{app}"; StatusMsg: "Claude Desktop bağlantısı kaydediliyor..."; Flags: runhidden waituntilterminated
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-c ""import sys; from arthur_mask.baslat import main; sys.exit(main())"""; WorkingDir: "{app}"; Description: "Arthur Mask'i şimdi aç"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: "-c ""import sys; from arthur_mask.claude_ayari import main; sys.exit(main(['sil']))"""; WorkingDir: "{app}"; RunOnceId: "ClaudeKaydiSil"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"

[Messages]
tr.FinishedLabel=Arthur Mask kuruldu.%n%nÖnemli: Claude Desktop açıksa tamamen kapatıp (sistem tepsisindeki simgeden de) yeniden açın; Arthur Mask bağlantısı ancak yeniden başlatınca görünür.%n%nBelgeleriniz ve kasalarınız Belgeler\Arthur Mask klasöründe tutulur.

[Code]
// Kurulum ya da güncellemeden önce bu klasörden çalışan Arthur Mask süreçleri (Claude Desktop'un
// başlattığı köprü dahil) kapatılır; aksi hâlde kilitli dosyalar değiştirilemez.
procedure SurecleriKapat();
var
  Sonuc: Integer;
  Komut: String;
begin
  Komut := '-NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like ''' +
    ExpandConstant('{app}') + '\runtime\*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"';
  Exec('powershell.exe', Komut, '', SW_HIDE, ewWaitUntilTerminated, Sonuc);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  SurecleriKapat();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    SurecleriKapat();
end;

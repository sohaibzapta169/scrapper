[Setup]
AppId={{7D305771-4AC2-4F36-8D53-0204C7982BD4}
AppName=Financial Listings Monitoring Tool
AppVersion=1.0.0
AppPublisher=Financial Listings Monitoring Tool
DefaultDirName={autopf}\Financial Listings Monitoring Tool
DefaultGroupName=Financial Listings Monitoring Tool
UninstallDisplayIcon={app}\FinancialListingsMonitor.exe
OutputDir=output
OutputBaseFilename=FinancialListingsMonitor-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\FinancialListingsMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Financial Listings Monitoring Tool"; Filename: "{app}\FinancialListingsMonitor.exe"
Name: "{group}\Uninstall Financial Listings Monitoring Tool"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Financial Listings Monitoring Tool"; Filename: "{app}\FinancialListingsMonitor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FinancialListingsMonitor.exe"; Description: "{cm:LaunchProgram,Financial Listings Monitoring Tool}"; Flags: nowait postinstall skipifsilent

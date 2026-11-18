param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'GLaDOSCheckin'),
    [string]$ProfileSource = '',
    [string]$Proxy = '',
    [string[]]$RunTimes = @('12:07', '18:07')
)
$ErrorActionPreference = 'Stop'
$taskName = 'Codex-GLaDOS-Checkin'
$description = 'GLaDOSCheckin managed local browser task. Dedicated profile only.'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) {
    throw 'A different task already uses this name; refusing to overwrite it.'
}
if ((Get-TimeZone).Id -ne 'China Standard Time') {
    throw 'These schedule times require the China Standard Time system timezone.'
}
$appRoot = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$profile = [IO.Path]::GetFullPath((Join-Path $appRoot 'BrowserProfile'))
if (-not $profile.StartsWith($appRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Unexpected profile destination.'
}
New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
if ($ProfileSource) {
    $sourceProfile = [IO.Path]::GetFullPath($ProfileSource)
    if (-not (Test-Path -LiteralPath (Join-Path $sourceProfile '.glados-checkin-profile'))) {
        throw 'The source is not a dedicated GLaDOS browser profile.'
    }
    if (Test-Path -LiteralPath $profile) {
        throw 'The destination profile already exists; refusing to replace it.'
    }
    # Both absolute paths are resolved above; destination is confined to appRoot.
    Move-Item -LiteralPath $sourceProfile -Destination $profile
}
$sourceRoot = $PSScriptRoot
foreach ($name in @('browser_checkin.py', 'checkin.py', 'local_checkin.py', 'run_local.py', 'requirements.txt', 'README.md')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $name) -Destination (Join-Path $appRoot $name) -Force
}
$pythonCommand = (Get-Command python.exe).Source
$venv = Join-Path $appRoot '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts/python.exe'))) {
    & $pythonCommand -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}
& (Join-Path $venv 'Scripts/python.exe') -m pip install -r (Join-Path $appRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies.' }
@{
    base_url = 'https://glados.network'
    channel = 'msedge'
    profile = $profile
    proxy = $Proxy
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appRoot 'settings.json') -Encoding UTF8
$action = New-ScheduledTaskAction -Execute (Join-Path $venv 'Scripts/pythonw.exe') -Argument ('"' + (Join-Path $appRoot 'run_local.py') + '"') -WorkingDirectory $appRoot
$triggers = @($RunTimes | ForEach-Object {
    $at = [datetime]::ParseExact($_, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
    New-ScheduledTaskTrigger -Daily -At $at
})
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description $description -Force | Out-Null
Write-Output ('Installed task: ' + $taskName)
Write-Output ('Daily times (Asia/Shanghai): ' + ($RunTimes -join ', '))
Write-Output ('Application directory: ' + $appRoot)

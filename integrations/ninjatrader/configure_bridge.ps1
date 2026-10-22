param(
    [string]$ApiBase = "https://p01--journalme-api--z928s7lw8hps.code.run/api/v1",
    [string]$AccountName
)

$ErrorActionPreference = "Stop"

$secureToken = Read-Host "Paste the JournalMe bridge key" -AsSecureString
$token = [System.Net.NetworkCredential]::new("", $secureToken).Password
if (-not $token) {
    throw "Bridge key is required."
}

$dir = Join-Path $env:USERPROFILE "Documents\JournalMe"
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$path = Join-Path $dir "bridge.conf"

$lines = @(
    "api_base=$($ApiBase.TrimEnd('/'))"
    "bridge_token=$token"
)
if ($AccountName) {
    $lines += "account_name=$AccountName"
}
[System.IO.File]::WriteAllLines($path, $lines, [System.Text.UTF8Encoding]::new($false))

Write-Host "JournalMe bridge configuration written to: $path"
Write-Host "Do not commit or share this file."

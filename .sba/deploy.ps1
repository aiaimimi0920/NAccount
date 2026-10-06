[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
if ($PSScriptRoot.StartsWith('\\') -or (Get-Location).Path.StartsWith('\\')) {
    throw 'Use the existing mapped drive or an equivalent local path, not a UNC working directory.'
}
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$script = Join-Path $PSScriptRoot 'cloudflare.py'
# Preserve the caller's working directory so relative CLI paths keep their meaning.
if (Get-Command rtk -ErrorAction SilentlyContinue) {
    & rtk proxy python $script @Arguments
}
else {
    & python $script @Arguments
}
exit $LASTEXITCODE

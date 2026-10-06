[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'
if ($PSScriptRoot.StartsWith('\\')) {
    throw 'Use the existing mapped drive or an equivalent local path, not a UNC working directory.'
}
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location -LiteralPath $PSScriptRoot
try {
    $script = Join-Path $PSScriptRoot 'scripts/stack.py'
    if (Get-Command rtk -ErrorAction SilentlyContinue) {
        & rtk proxy python $script @Arguments
    }
    else {
        & python $script @Arguments
    }
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $code

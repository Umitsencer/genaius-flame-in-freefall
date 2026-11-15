<#
.SYNOPSIS
Launch the local GENAIUS NASA PSI prototype server (FastAPI + Uvicorn, loopback only) on Windows PowerShell.
Install dependencies first: python -m pip install -r requirements.txt
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$AllowDegradedRawData
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SrcPath = Join-Path $RepoRoot "src"
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonCmd = Get-Command python -ErrorAction Stop
    $PythonExe = $PythonCmd.Source
}

$RequiredRawFiles = @(
    "data/raw/psi/experimental_tables/PSI-25/PSI-25_Experimental table_BASS-II.csv",
    "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv",
    "data/raw/nasa_docs/20150023456_flex.pdf",
    "data/raw/nasa_docs/20210011385_bass_ii.pdf",
    "data/raw/psi/matrices_and_readmes/PSI-25/PSI-25_Science Documents_BASS-II_ReadMe.docx"
)

$OptionalRawFiles = @(
    "data/raw/psi/matrices_and_readmes/PSI-39/PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx",
    "data/raw/psi/experimental_tables/PSI-39/PSI-39_Experimental table_CFI.csv",
    "data/raw/psi/experimental_tables/PSI-99/PSI-99_Experimental table_SAFFIRE-2.csv",
    "data/raw/psi/matrices_and_readmes/PSI-99/PSI-99_Science Documents_SAFFIRE-II Readme.docx"
)

$MissingRaw = @()
foreach ($RelPath in $RequiredRawFiles) {
    $FullPath = Join-Path $RepoRoot $RelPath
    if (-not (Test-Path $FullPath)) {
        $MissingRaw += $RelPath
    }
}

$MissingOptional = @()
foreach ($RelPath in $OptionalRawFiles) {
    $FullPath = Join-Path $RepoRoot $RelPath
    if (-not (Test-Path $FullPath)) {
        $MissingOptional += $RelPath
    }
}

if ($MissingRaw.Count -gt 0) {
    Write-Warning ("Missing required local NASA core raw files ({0}): {1}" -f $MissingRaw.Count, ($MissingRaw -join ", "))
    if (-not $AllowDegradedRawData) {
        throw "Required local data/raw files are missing. See README.md or pass -AllowDegradedRawData to inspect catalog/UI without full tables."
    }
}

if ($MissingOptional.Count -gt 0) {
    Write-Warning ("Optional PSI-39 CFI / PSI-99 SAFFIRE files not found ({0}); those modules will degrade with 503 if queried." -f $MissingOptional.Count)
}

$DotEnvPath = Join-Path $RepoRoot ".env"
if (Test-Path $DotEnvPath) {
    Write-Host ".env detected locally (contents are not printed; OpenRouter activates only when OPENROUTER_API_KEY is set and GENAIUS_LLM_ENABLED is not false)."
} else {
    Write-Host "No .env file found; server will run cleanly in deterministic non-LLM mode."
}

$env:PYTHONPATH = $SrcPath
Write-Host ("Starting GENAIUS prototype server on http://127.0.0.1:{0}/ using {1}" -f $Port, $PythonExe)
& $PythonExe -m genaius.prototype.server --repo-root $RepoRoot --port $Port

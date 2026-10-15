$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectRuntime = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runtimeCandidates = @($projectRuntime)
if (Get-Command py -ErrorAction SilentlyContinue) {
    $ErrorActionPreference = 'Continue'
    $registeredRuntime = & py -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0) { $runtimeCandidates += $registeredRuntime }
    $ErrorActionPreference = 'Stop'
}
$bundledRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$runtimeCandidates += $bundledRuntime
foreach ($runtimeCandidate in $runtimeCandidates) {
    if (Test-Path -LiteralPath $runtimeCandidate -PathType Leaf) {
        if ($runtimeCandidate -eq $bundledRuntime -or ($runtimeCandidate -eq $projectRuntime -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'build\tcl\tk8.6\tk.tcl')))) {
            # Tcl cannot reliably access the bundled scripts in this runtime location.
            # Stage its unmodified, licensed Tcl/Tk files inside the workspace instead.
            $localTcl = Join-Path $PSScriptRoot 'build\tcl'
            if (-not (Test-Path -LiteralPath (Join-Path $localTcl 'tk8.6\tk.tcl'))) {
                New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'build') | Out-Null
                Copy-Item -LiteralPath (Join-Path (Split-Path $bundledRuntime) 'tcl') -Destination $localTcl -Recurse -Force
            }
            $env:TCL_LIBRARY = (Join-Path $localTcl 'tcl8.6').Replace('\', '/')
            $env:TK_LIBRARY = (Join-Path $localTcl 'tk8.6').Replace('\', '/')
        }
        & $runtimeCandidate (Join-Path $PSScriptRoot 'app.py')
        exit $LASTEXITCODE
    }
}
Write-Host 'Python was not found. Install Python 3.10 or newer with Tcl/Tk and the Python launcher, then try again.'
exit 1

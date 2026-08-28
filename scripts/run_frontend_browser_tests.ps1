param(
    [string]$Grep = ""
)

$ErrorActionPreference = "Stop"
$frontendPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\frontend")).Path
$nextCliPath = Join-Path $frontendPath "node_modules\next\dist\bin\next"
$playwrightPath = Join-Path $frontendPath "node_modules\.bin\playwright.cmd"
$nodePath = (Get-Command node -ErrorAction Stop).Source
$previousDataMode = $env:NEXT_PUBLIC_AMEX_DATA_MODE
$env:NEXT_PUBLIC_AMEX_DATA_MODE = if ($env:AMEX_E2E_LIVE -eq "1") { "live" } else { "fixture" }

Push-Location $frontendPath
try {
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend production build failed."
    }
} finally {
    Pop-Location
}

try {
    $existing = Invoke-WebRequest -Uri "http://127.0.0.1:3100" -UseBasicParsing -TimeoutSec 1 -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        throw "Port 3100 is already serving HTTP; refusing to test against an unidentified process."
    }
} catch [System.Net.WebException] {
    # Expected when the verification server has not started yet.
}

$server = Start-Process -FilePath $nodePath -ArgumentList @($nextCliPath, "start", "--hostname", "127.0.0.1", "--port", "3100") -WorkingDirectory $frontendPath -WindowStyle Hidden -PassThru
$exitCode = 1

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if ($server.HasExited) {
            throw "Next verification server exited before becoming ready."
        }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:3100" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch [System.Net.WebException] {
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $ready) {
        throw "Next verification server did not become ready within 20 seconds."
    }

    $arguments = @("test", "--reporter=line")
    if ($Grep.Length -gt 0) {
        $arguments += @("--grep", $Grep)
    }
    & $playwrightPath @arguments
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -ne $server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        $null = $server.WaitForExit(5000)
    }
    if ($null -eq $previousDataMode) {
        Remove-Item Env:NEXT_PUBLIC_AMEX_DATA_MODE -ErrorAction SilentlyContinue
    } else {
        $env:NEXT_PUBLIC_AMEX_DATA_MODE = $previousDataMode
    }
}

exit $exitCode

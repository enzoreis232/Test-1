param(
    [string]$Python = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "O executável Windows precisa ser compilado e validado no Windows."
}
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not $SkipTests) {
        # Evita que os testes automatizados abram janelas interativas.
        $oldPlatform = $env:QT_QPA_PLATFORM
        $env:QT_QPA_PLATFORM = "offscreen"
        try {
            & $Python -m pytest
            if ($LASTEXITCODE -ne 0) { throw "Os testes falharam." }
        } finally {
            $env:QT_QPA_PLATFORM = $oldPlatform
        }
    }

    & $Python -m PyInstaller --noconfirm --clean BacBoAnalyticsPro.spec
    if ($LASTEXITCODE -ne 0) { throw "A compilação PyInstaller falhou." }
    $dist = Join-Path $projectRoot "dist/BacBoAnalyticsPro"
    $exe = Join-Path $dist "BacBoAnalyticsPro.exe"
    if (-not (Test-Path $exe)) { throw "Executável não foi produzido." }
    # Onedir: o executável depende de _internal. Nunca distribuir somente o .exe.
    if (-not (Test-Path (Join-Path $dist "_internal/PySide6"))) {
        throw "As bibliotecas Qt não estão na distribuição."
    }
    if (-not (Get-ChildItem $dist -Filter qwindows.dll -Recurse)) {
        throw "O plugin Qt de plataforma Windows está ausente."
    }

    $smokeDir = Join-Path ([IO.Path]::GetTempPath()) ("bacbo-smoke-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $smokeDir | Out-Null
    try {
        $process = Start-Process -FilePath $exe -ArgumentList @(
            "--smoke-test", "--data-dir", ('"' + $smokeDir + '"'),
            "--screenshot", ('"' + (Join-Path $smokeDir "validacao-windows.png") + '"')
        ) -PassThru
        if (-not $process.WaitForExit(45000)) {
            Stop-Process -Id $process.Id -Force
            throw "O aplicativo congelou ou não concluiu o teste de inicialização."
        }
        if ($process.ExitCode -ne 0) {
            throw "O teste do executável terminou com código $($process.ExitCode)."
        }
        # O ponto de entrada cria este comprovante somente após demonstrar
        # UI, persistência e processamento de rodadas no executável congelado.
        $report = Join-Path $smokeDir "smoke-test.json"
        if (-not (Test-Path $report)) { throw "O teste não gerou relatório de validação." }
        $result = Get-Content $report -Raw | ConvertFrom-Json
        if (-not $result.ok) { throw "O relatório indica falha do aplicativo." }
        Copy-Item $report (Join-Path $dist "validacao-windows.json")
        $screenshot = Join-Path $smokeDir "validacao-windows.png"
        if (-not (Test-Path $screenshot)) { throw "A imagem de validação da interface está ausente." }
        Copy-Item $screenshot (Join-Path $dist "validacao-windows.png")
    } finally {
        Remove-Item $smokeDir -Force -Recurse -ErrorAction SilentlyContinue
    }

    Copy-Item "LEIA-ME.txt" (Join-Path $dist "LEIA-ME.txt") -Force
    $zip = Join-Path $projectRoot "dist/BacBoAnalyticsPro-Windows.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
    Write-Host "Artefato validado: $zip"
} finally {
    Pop-Location
}

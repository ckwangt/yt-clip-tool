# Restarts the local Flask dev server: stops whatever is listening on port 5000,
# makes sure ffmpeg is on PATH, then starts app.py (debug/reload mode) in the background.

$port = 5000

$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $ffmpegPkgRoot = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    $ffmpegBin = Get-ChildItem -Path $ffmpegPkgRoot -Filter "ffmpeg.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ffmpegBin) {
        $env:PATH = "$($ffmpegBin.DirectoryName);$env:PATH"
    } else {
        Write-Warning "ffmpeg.exe not found on PATH or under $ffmpegPkgRoot"
    }
}

& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\app.py"

# Full path to UPX
$upx = "C:\Users\test\AppData\Local\Microsoft\WinGet\Packages\UPX.UPX_Microsoft.Winget.Source_8wekyb3d8bbwe\upx-5.1.0-win64\upx.exe"

# Get all DLLs and PYDs to compress
$files = Get-ChildItem -Path "dist/CLD/_internal" -Recurse -Include "*.dll","*.pyd" |
    Where-Object { $_.FullName -notmatch "numpy|scipy|mkl" }

# Compress in parallel using PowerShell 7 parallel foreach (if available)
# Falls back to sequential if PS7 not available
if ($PSVersionTable.PSVersion.Major -ge 7) {
    Write-Host "Compressing $($files.Count) files in parallel..."
    $files | ForEach-Object -Parallel {
        & $using:upx --best $_.FullName 2>&1 | Out-Null
        Write-Host "Compressed: $($_.Name)"
    } -ThrottleLimit 8
} else {
    Write-Host "Compressing $($files.Count) files sequentially..."
    $files | ForEach-Object {
        Write-Host "Compressing: $($_.Name)"
        & $upx --best $_.FullName 2>&1 | Out-Null
    }
}

# Compress main exe
Write-Host "Compressing: CLD.exe"
& $upx --best "dist/CLD/CLD.exe"

# Show final size
$size = (Get-ChildItem -Path "dist/CLD" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Final size: $([math]::Round($size, 2)) MB"

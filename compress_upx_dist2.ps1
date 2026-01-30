# Full path to UPX
$upx = "C:\Users\test\AppData\Local\Microsoft\WinGet\Packages\UPX.UPX_Microsoft.Winget.Source_8wekyb3d8bbwe\upx-5.1.0-win64\upx.exe"

# Get all DLLs and PYDs to compress (excluding numpy/scipy/mkl which don't compress well)
$files = Get-ChildItem -Path "dist2/CLD/_internal" -Recurse -Include "*.dll","*.pyd" |
    Where-Object { $_.FullName -notmatch "numpy|scipy|mkl" }

Write-Host "Compressing $($files.Count) files..."
$compressed = 0
$skipped = 0

foreach ($file in $files) {
    $result = & $upx --best $file.FullName 2>&1
    if ($result -match "NotCompressibleException|CantPackException|AlreadyPackedException") {
        $skipped++
    } else {
        $compressed++
    }
}

Write-Host "Compressed: $compressed files, Skipped: $skipped files"

# Compress main exe
Write-Host "Compressing: CLD.exe"
& $upx --best "dist2/CLD/CLD.exe"

# Show final size
$size = (Get-ChildItem -Path "dist2/CLD" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Final size: $([math]::Round($size, 2)) MB"

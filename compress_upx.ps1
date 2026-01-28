# Full path to UPX
$upx = "C:\Users\test\AppData\Local\Microsoft\WinGet\Packages\UPX.UPX_Microsoft.Winget.Source_8wekyb3d8bbwe\upx-5.1.0-win64\upx.exe"

# Compress DLLs and PYDs with UPX, excluding numpy/scipy/mkl
Get-ChildItem -Path "dist/CLD2/_internal" -Recurse -Include "*.dll","*.pyd" |
    Where-Object { $_.FullName -notmatch "numpy|scipy|mkl" } |
    ForEach-Object {
        Write-Host "Compressing: $($_.Name)"
        & $upx --best $_.FullName 2>&1 | Out-Null
    }

# Compress main exe
Write-Host "Compressing: CLD2.exe"
& $upx --best "dist/CLD2/CLD2.exe"

# Show final size
$size = (Get-ChildItem -Path "dist/CLD2" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "Final size: $([math]::Round($size, 2)) MB"

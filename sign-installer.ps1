# Sign CLD installer with MarvinFS certificate
$ErrorActionPreference = "Stop"

$installerPath = "D:\claudecli-dictate2\dist\CLD-0.5.2-Setup.exe"

# Find the MarvinFS certificate
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -like '*MarvinFS*' }

if (-not $cert) {
    Write-Error "MarvinFS code signing certificate not found!"
    exit 1
}

Write-Host "Using certificate: $($cert.Subject)"
Write-Host "Thumbprint: $($cert.Thumbprint)"
Write-Host "Signing: $installerPath"

$result = Set-AuthenticodeSignature -FilePath $installerPath -Certificate $cert -TimestampServer "http://timestamp.digicert.com"

if ($result.Status -eq "Valid") {
    Write-Host "Signature successful!" -ForegroundColor Green
} else {
    Write-Host "Signature applied (self-signed cert)" -ForegroundColor Yellow
}
Write-Host "Status: $($result.Status)"

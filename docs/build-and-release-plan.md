# CLD Build and Release Plan

This document covers the complete build, sign, and release workflow for CLD.

## Prerequisites

### Build Machine Setup

Install the following on the build machine (not OneDrive-synced folder):

1. Python 3.12+ with uv package manager
2. Visual Studio Build Tools (for PyInstaller)
3. Inno Setup 6 from https://jrsoftware.org/isdl.php
4. Code signing certificate (self-signed or purchased)

### Directory Structure

```
D:\claudecli-dictate\           # Build directory (local, not synced)
├── src/                        # Source code (synced from OneDrive)
├── sounds/                     # Audio assets
├── dist/                       # PyInstaller output
│   └── CLD/
│       ├── CLD.exe             # Main executable
│       └── _internal/          # Dependencies
├── installer_output/           # Inno Setup output
├── build-pyinstaller.ps1       # Build script
├── sign-simple.ps1             # Signing script
├── sign-and-package.ps1        # Full release script
├── installer.iss               # Inno Setup script
└── cld_codesign.pfx            # Code signing certificate

D:\OneDrive - NoWay Inc\APPS\claudecli-dictate\  # Source (OneDrive)
├── src/cld/                    # Python source code
├── docs/                       # Documentation
└── CLAUDE.md                   # Project instructions
```

## Build Workflow

### Step 1: Sync Source Code

```powershell
cd D:\claudecli-dictate
.\sync-and-build.ps1
```

This copies source from OneDrive to the local build directory. Never build directly in OneDrive folders due to file locking issues.

### Step 2: Build with PyInstaller

```powershell
.\build-pyinstaller.ps1
```

Or manually:
```powershell
uv run pyinstaller -y --onedir --windowed --name CLD `
    --icon cld_icon.ico `
    --add-data "sounds;sounds" `
    --add-data "cld_icon.png;." `
    --add-data "mic_256.png;." `
    src/cld/cli.py
```

Output: `dist\CLD\CLD.exe` (~365MB folder)

### Step 3: Sign the Executable

```powershell
.\sign-simple.ps1
```

This signs CLD.exe with the code signing certificate. Self-signed certificates show "Unknown Publisher" but the signature is valid.

### Step 4: Build Installer

```powershell
.\sign-and-package.ps1
```

Or open `installer.iss` in Inno Setup and compile manually.

Output: `installer_output\CLD-Setup-0.1.0.exe`

### Step 5: Sign the Installer

The `sign-and-package.ps1` script automatically signs the installer after building.

## Code Signing

### Creating a Self-Signed Certificate

```powershell
$cert = New-SelfSignedCertificate -Type CodeSigningCert `
    -Subject 'CN=CLD Developer' `
    -KeyUsage DigitalSignature -KeySpec Signature -KeyLength 2048 `
    -KeyExportPolicy Exportable -CertStoreLocation 'Cert:\CurrentUser\My' `
    -NotAfter (Get-Date).AddYears(5)

# Export to PFX
$password = ConvertTo-SecureString -String 'YourPassword' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath 'cld_codesign.pfx' -Password $password
```

### Signing an Executable

```powershell
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Subject -like '*CLD Developer*' }
Set-AuthenticodeSignature -FilePath 'dist\CLD\CLD.exe' -Certificate $cert
```

### For Production

Purchase a code signing certificate from DigiCert, Sectigo, or Comodo to avoid "Unknown Publisher" warnings.

## Installer Configuration

The `installer.iss` script configures:

- Install to `C:\Program Files\CLD\`
- Start Menu shortcut
- Optional Desktop shortcut
- Optional startup with Windows
- Uninstaller registration
- Kills running CLD process before install/uninstall

## Version Bumps

Update version in:
1. `pyproject.toml`
2. `src/cld/__init__.py`
3. `installer.iss` (MyAppVersion)

## Why PyInstaller over Nuitka

PyInstaller was chosen because:

1. Better handling of dynamic imports in av/faster-whisper packages
2. Automatic hook system for complex dependencies
3. Simpler configuration
4. Faster iteration during development

Nuitka failed due to complex runtime imports in:
- av (PyAV) - audio/video processing
- faster-whisper - speech recognition
- ctranslate2 - neural network inference

## Troubleshooting

### Build fails with permission error
The exe is still running. Kill CLD.exe and retry:
```powershell
taskkill /F /IM CLD.exe
```

### Missing dependencies in exe
Check if packages are bundled:
```powershell
Get-ChildItem dist\CLD\_internal -Directory | Select Name
```

Add missing packages with `--hidden-import`:
```powershell
pyinstaller ... --hidden-import=missing_package
```

### Exe doesn't start (silent exit)
Build with console to see errors:
```powershell
pyinstaller ... --console  # instead of --windowed
```

### Background spawn fails
Check if `sys.frozen` detection works. In frozen exe:
- PyInstaller: `sys.frozen = True`, `sys.executable = CLD.exe`
- Nuitka: `__compiled__` attribute on `__main__`

# Changelog

All notable changes to CLD are documented here, newest first.

## [0.8.2] - 2026-06-18

CLD now defaults to a new speech engine, adds in-app model management, and ships a batch of reliability fixes.

### Added
- New default engine: NVIDIA Nemotron-3.5-ASR (via sherpa-onnx). Runs entirely on the CPU with no GPU required, covers 40 locales including English and Russian, and writes punctuation as it transcribes. CLD downloads and verifies the model on first use.
- Models section in Settings: see which models are installed and their size, and download or remove them in-app.
- Engine-switch confirmation, shown even when the model is already installed.

### Changed
- Whisper is now the optional engine for GPU acceleration (Vulkan, 99 languages, translate-to-English). Switch engines anytime in Settings.
- Engine switching is transactional: the new engine loads before the old one is released, and a failed switch keeps the previous engine running.
- Model files are verified with SHA-256 (the Nemotron archive and every file inside it) before an engine is enabled.
- License metadata corrected to GPL-3.0-or-later.

### Fixed
- Windows startup issue where launching from the shortcut could leave the app with no tray icon or overlay; a second launch no longer closes the running copy.
- Nemotron no longer drops the closing punctuation of a sentence.

## [0.7.1] - 2026-05-12

### Fixed
- Crash after Windows sleep/wake that aborted the process about a minute after waking. The resume callback now runs on a plain background thread instead of Tk's `after()` queue, avoiding the unsafe Tcl-to-Python callback path.

### Changed
- The daemon proactively cleans up orphan state files (PID file, settings lock, shutdown sentinel) left by a previously-crashed process.

## [0.7.0] - 2026-05-11

### Changed
- Thread-safety hardening: dedicated transcription lock and queued UI updates from background threads.
- Path validation for the `CLD_CONFIG_DIR` environment variable to prevent path traversal.
- New runtime module for better resource management.

### Fixed
- Regressions from the review-fix batch, plus various stability and correctness fixes.

## [0.6.0] - 2026-03-15

### Added
- Sleep/wake resilience: survives Windows sleep/hibernate without crashing. Vulkan GPU resources are freed before sleep and reloaded on wake; audio, hotkey, and tray recover after resume; a time-gap fallback catches sleep/wake even when the overlay is gone.
- Overlay destroy/recreate with automatic retry, and runtime detection of pywhispercpp GPU capabilities.

### Fixed
- Process discovery for the frozen exe so the stop command works reliably, PID-file daemon tracking, and zombie-process cleanup that prevents duplicate instances.

## [0.5.2] - 2026-01-30

### Added
- Installer with update detection and running-process close handling.

## [0.5.1] - 2026-01-30

Initial public release.

### Added
- Local speech-to-text using Whisper, GPU acceleration via Vulkan (NVIDIA, AMD, Intel), 99-language support with auto-detection, system-tray overlay UI, toggle and push-to-talk recording modes, and text entry into any application.

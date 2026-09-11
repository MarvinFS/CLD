# Changelog

All notable changes to CLD are documented here, newest first.

## [0.9.0] - 2026-09-11

### Added
- Type while speaking, on by default, in Settings > STT Engine. With Whisper on a GPU, CLD types the text while you speak and fixes words as more speech makes them clear. When you stop, CLD replaces it with a transcription of the whole recording. Nemotron, and Whisper on the CPU, still type after you stop. Clear the checkbox to type after you stop, as in 0.8.3. CLD releases the hotkey for the window it types into, so right Alt doesn't turn the text into shortcuts or open a menu.

## [0.8.3] - 2026-09-10

### Added
- Input Device setting in Settings > Recording: choose which microphone CLD records from. System default keeps using the Windows default recording device. A new choice takes effect when you click Save.
- If the saved microphone is missing at startup, CLD records from the system default instead.
- Whisper Large v3 Turbo Q5 model (574 MB). CLD recommends it on PCs with a GPU, where it transcribes a 30-second dictation in about 0.2 s on an RTX 4090. It can't translate into English, so Settings hides Translate to English while it's selected. Use Medium Q5 to translate.

### Changed
- Nemotron uses the corrected model files that k2-fsa republished on 2026-07-09 (encoder attention context 56 instead of 70). The first time CLD starts after the update, the model setup dialog offers the download (about 475 MB). Once the new version is installed, CLD deletes the previous one.
- The Nemotron engine runs the model directly with onnxruntime instead of through sherpa-onnx. It follows NVIDIA's reference streaming recipe: NeMo's log-mel features, NeMo's chunk grid, and a final chunk sent with its true length. sherpa-onnx 1.13.7 pads the final chunk to a full window, and with the corrected model that loses the closing punctuation.
- Model recommendations: Whisper Large v3 Turbo Q5 on PCs with a GPU and the Nemotron engine on PCs without one. The Whisper setup dialog preselects Medium Q5 when there's no GPU. Before, Medium Q5 was recommended with a GPU and Medium on CPUs with 8 or more cores.
- The model setup dialog shows each model's use case and how long it takes to transcribe 30 seconds of speech on a CPU and on a GPU.
- On CPUs without AVX2, the model setup dialog warns for every Whisper model, not only for Medium.
- New installs use push-to-talk on the right Alt key: hold it while you speak, and let go to transcribe. Before, a new install used toggle mode on either Alt key. Saved settings keep their key and mode.

### Removed
- The full-precision Whisper Medium model (1.5 GB). Medium Q5 gives almost the same text at a third of the size and runs as fast or faster.
- Whisper Small (488 MB). It made the most recognition mistakes of the Whisper models, and Nemotron is as fast on the CPU.
- Settings that used Medium or Small switch to Medium Q5. CLD doesn't delete the old ggml-medium.bin or ggml-small.bin file.

### Fixed
- Dictation produced no text when the Windows default recording device was a silent input, such as an unused channel on an audio interface. You can now pick the right microphone in Input Device.
- Nemotron dropped words and sometimes whole phrases in long dictations. The earlier model files caused it.
- A recording that starts right on the first word no longer loses that word.
- In a window with a non-English keyboard layout, dictated punctuation and Latin letters came out as other characters, for example "." as "ю" and "," as "б" in the Russian layout. CLD now types every character as Unicode. If Windows blocks typed input, for example into an elevated window, CLD copies the text to the clipboard instead.

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

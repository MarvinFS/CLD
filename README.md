<div align="center">

# 🎙️ CLD - ClaudeCli-Dictate

**Version 0.5.1** | AI-Powered Voice Dictation That Stays on Your Machine

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows)](https://github.com/MarvinFS/CLD)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Vulkan](https://img.shields.io/badge/GPU-Vulkan%20Accelerated-AC162C?logo=vulkan)](https://vulkan.org)

Talk to your computer, get text anywhere. CLD captures your voice, transcribes it locally using a decent AI model, and types the result into whatever application you have focus in. Your audio never leaves your computer because everything runs right on your hardware with GPU acceleration (or CPU only - your choice).

</div>

---

<div align="center">

**📺 See CLD in Action**

https://github.com/user-attachments/assets/581e5ec1-b7af-47f8-93b2-9f47d97e5a8f

</div>

## 🚀 Quick Start

Getting CLD running takes about a minute:

1. Download the latest installer from the GitHub releases page
2. Run the installer, open the program from start menu and select a Whisper model when prompted (medium-q5_0 is recommended for non-potato PCs with dedicated GPUs)
3. Wait for the model download to complete (the default model is about 500MB)
4. Press Alt Gr (right Alt key, default) to start recording, speak, then press again to stop (alternative mode is push-to-talk)
5. Your words appear as typed text in whatever application is focused, in the language you dictate with - you may mix languages and it will automatically match the output (mix English and Spanish for example)

That's it. CLD now runs in your system tray with an on-screen overlay by default and is ready whenever you need to dictate.

---

## 💡 Why CLD?

Voice typing should be simple, fast, and private. CLD delivers all three. I saw how Apple macOS system dictate tool works and then cried how bad the same is implemented by the default Windows Speech-To-Text.

Many voice dictation tools also send your audio to cloud servers for processing. That means latency, privacy concerns, and often a subscription fee. CLD takes a different approach by running a decent AI model directly on your computer. The transcription happens in memory and the audio is discarded immediately after. There's no account to create, no data to upload, and no ongoing cost. You are welcome!

CLD also works with any application. It was designed to work with AI coding agents, but also can be used to compose emails in Outlook, write code in VS Code, chat in Discord, take notes in Obsidian, or fill out web forms in your browser. If you can type in it, CLD can dictate to it.

The project started as a fork of an open source project claude-stt (refer to credits section below), a voice input plugin for Claude Code. CLD evolved into a standalone Windows application with a GUI, system tray integration, and GPU acceleration for 50x faster transcription.

---

## ✨ Features at a Glance

CLD brings several capabilities together in one lightweight application.

**🔐 Local Processing:** Audio capture, transcription, and text injection all happen on your machine. Nothing is uploaded anywhere. Your conversations, notes, and thoughts stay private.

**🌐 Multilingual Support:** CLD uses Whisper, an open-source speech recognition model originally released by OpenAI. The actual implementation is whisper.cpp (a fast C++ port) with GGML model files from HuggingFace. Whisper understands 99 languages. Speak in English, German, Japanese, Russian, or any supported language and CLD transcribes in that language. It can even translate everything to English, if you tell it to do so in settings.

**⚡ GPU Acceleration:** CLD uses the Vulkan graphics API for GPU-accelerated inference. A 30-second recording transcribes in about 1-2 seconds on a mid-range GPU. Without GPU acceleration, the same recording might take 10-15 but in most cases close to 30 seconds.

**🔄 Recording Modes:** Choose toggle mode (press once to start, press again to stop) or push-to-talk mode (hold to record, release to transcribe). Either way, the overlay shows your recording duration and responds to your voice with animated waveform bars.

**🎯 Works Everywhere:** CLD injects text via keyboard simulation, just like if you typed it yourself. Applications that block this (like some password managers) get a clipboard fallback instead, if there are no currently focused window.

---

## 🌍 Supported Languages

Whisper supports 99 languages with automatic language detection. Just speak in your language and CLD transcribes it without any configuration:

<details>
<summary><b>Click to expand full language list</b></summary>

Afrikaans, Albanian, Amharic, Arabic, Armenian, Assamese, Azerbaijani, Bashkir, Basque, Belarusian, Bengali, Bosnian, Breton, Bulgarian, Burmese, Cantonese, Catalan, Chinese, Croatian, Czech, Danish, Dutch, English, Estonian, Faroese, Finnish, French, Galician, Georgian, German, Greek, Gujarati, Haitian Creole, Hausa, Hawaiian, Hebrew, Hindi, Hungarian, Icelandic, Indonesian, Italian, Japanese, Javanese, Kannada, Kazakh, Khmer, Korean, Lao, Latin, Latvian, Lingala, Lithuanian, Luxembourgish, Macedonian, Malagasy, Malay, Malayalam, Maltese, Maori, Marathi, Mongolian, Myanmar, Nepali, Norwegian, Occitan, Pashto, Persian, Polish, Portuguese, Punjabi, Romanian, Russian, Sanskrit, Serbian, Shona, Sindhi, Sinhala, Slovak, Slovenian, Somali, Spanish, Sundanese, Swahili, Swedish, Tagalog, Tajik, Tamil, Tatar, Telugu, Thai, Tibetan, Turkish, Turkmen, Ukrainian, Urdu, Uzbek, Vietnamese, Welsh, Yiddish, Yoruba

</details>

Accuracy varies by language. English, Spanish, German, French, Russian, Chinese, Japanese, and other major languages have excellent recognition. Less common languages may have much more reduced accuracy depending on how much training data was available, but I wouldn't expect much from a 500 megs model for Telugu language. Main languages, though, are very good.

---

## 💻 System Requirements

CLD is a Windows-only application, designed specifically for Windows 10 and Windows 11. The original claude-stt plugin supported macOS and Linux, but I dropped cross-platform support (FOR NOW! as of current version!) to focus on deep Windows integration including native system tray behavior, Windows-specific hotkey handling (Alt Gr support, virtual key code mapping), and DWM-based dark theme styling. The standalone executable now requires NO local Python installation.

### CPU Requirements

Your CPU needs SSE4.1 instruction support, which covers most processors from 2013 onward. AVX and AVX2 instructions significantly improve performance with larger models. Intel Haswell (2013) and AMD Excavator (2015) or newer support AVX2.

### RAM Requirements

| Model | RAM Required |
|-------|--------------|
| small | ~1 GB |
| medium-q5_0 | ~2 GB |
| medium | ~3 GB |

Most modern computers with 8GB or more RAM can run the recommended medium-q5_0 model comfortably.

### GPU Acceleration

GPU acceleration is optional but highly recommended. CLD uses Vulkan, which works with GPUs from all major vendors, including all iGPUs.

| Vendor | Supported Hardware |
|--------|-------------------|
| ![NVIDIA](https://img.shields.io/badge/-NVIDIA-76B900?logo=nvidia&logoColor=white) | GeForce GTX 10-series and newer (Pascal architecture or later) |
| ![AMD](https://img.shields.io/badge/-AMD-ED1C24?logo=amd&logoColor=white) | RX 5000/6000/7000 series, Radeon integrated graphics on Ryzen APUs |
| ![Intel](https://img.shields.io/badge/-Intel-0071C5?logo=intel&logoColor=white) | Arc discrete GPUs (A580, A770, B580), UHD and Iris integrated graphics |

With CLD I have originally tried to use NVIDIA CUDA for GPU acceleration. It was a disaster, so I migrated to Vulkan. CUDA only supports NVIDIA GPUs and requires architecture-specific builds (one binary for RTX 40-series, another for RTX 30-series, and so on). A single CUDA build with cuBLAS libraries adds over 600 MB to the application. Vulkan works with all GPU vendors from a single binary and adds only 100-150 MB. While CUDA may be marginally faster on NVIDIA hardware, Vulkan achieves 80-95% of that performance while supporting every discrete and integrated GPU on the market.

### Disk Space

The application requires approximately 67 MB when compressed. Model files are stored separately and range from 488 MB (small) to 1.5 GB (medium) depending on your choice.

---

## 📥 Installation

Download the latest release from the GitHub releases page, install it and then run `CLD.exe`. On first launch, a model setup dialog appears showing your detected hardware (CPU features like SSE4.1, AVX, AVX2) and recommends an appropriate model. Select a model from the dropdown, click Download, and watch the progress bar. After the download completes, CLD starts automatically with the overlay visible. You may opt to manual model installation with the respective button in model installer UI.

### From Source

For developers who prefer running from source:

```bash
git clone https://github.com/MarvinFS/CLD
cd CLD
uv sync --python 3.12
uv run python -m cld.daemon run --overlay
```

This requires Python 3.12 and uv for dependency management.

---

## 🧠 Understanding the Models

CLD uses GGML-format Whisper models from the whisper.cpp project. These models vary in size, accuracy, and hardware requirements.

| Model | Parameters | Quantization | File Size | RAM | Accuracy |
|-------|------------|--------------|-----------|-----|----------|
| small | 244 million | FP16 (full precision) | 488 MB | ~1 GB | Good |
| **medium-q5_0** | 769 million | 5-bit quantized | 539 MB | ~2 GB | Very Good ✨ |
| medium | 769 million | FP16 (full precision) | 1.5 GB | ~3 GB | Excellent |

The medium-q5_0 model offers the best balance for most users. It has three times more parameters than the small model but achieves a similar file size through quantization. This compression technique reduces weight precision from 16 bits to 5 bits while preserving most of the model's accuracy. The result is noticeably better transcription than the small model with modest additional resource requirements.

If medium-q5_0 struggles on your system, try the small model. If you have plenty of RAM and want the best possible accuracy, the full medium model delivers slightly better results at the cost of higher memory usage.

On my home computer I personally use medium model and it works amazingly - a bit slower than medium-q5_0, but on my GPU still almost instant.

Models are downloaded from HuggingFace during first-time setup and stored at `%LOCALAPPDATA%\CLD\models\`. File integrity is verified using MD5 hashes after download to catch corrupted files.

---

## 🎤 Your First Dictation

Here's how a typical dictation session works:

Open the application where you want text to appear and position your cursor. Press your activation key (Alt Gr by default). The overlay changes from its compact idle state to show the recording interface with animated waveform bars and a timer.

Speak naturally at a comfortable pace. The waveform bars respond to your voice volume, giving you visual feedback that audio is being captured.

Press the activation key again to stop recording. The overlay shows "Processing..." while the model transcribes your audio. On a GPU-accelerated system, this typically takes 1-2 seconds for a 30-second recording.

The transcribed text appears at your cursor position. For longer recordings (over 30 seconds), CLD automatically splits the audio into chunks and processes them sequentially. The results are concatenated with spaces between them.

The overlay returns to its idle state, ready for your next recording. The maximum recording duration is 300 seconds (5 minutes) by default, configurable up to 600 seconds in settings.

---

## ⚙️ Settings Guide

Access settings through the system tray icon (right-click and select Settings) or by clicking the gear icon on the overlay.

### 🎹 Activation Key

**Activation Key:** The key that triggers recording. Default is Alt Gr (the right Alt key). Click "Change" to capture a new key in settings UI.

**Modifiers:** Optional Ctrl, Shift, or Alt modifiers to combine with your activation key. Useful if your preferred key conflicts with other applications.

**Mode:** Toggle mode starts recording on first press and stops on second press. Push-to-talk mode records while you hold the key and transcribes when you release it. Toggle mode includes a 300ms debounce to prevent accidental double-presses.

**Hotkey Enabled:** Master switch for the hotkey listener. Disable this to temporarily suspend CLD without closing it.

### 🎛️ STT Engine

**Engine:** Currently Whisper is the only supported engine. It provides very good accuracy across many languages with automatic language detection.

**Model:** Select which Whisper model to use. Changing models requires restarting the daemon (CLD prompts you to restart after saving settings) and then model download window will be displayed where you will need to select the required model again to get it downloaded.

### 🖥️ Hardware

**Force CPU Only:** Disables GPU acceleration and uses CPU-only inference. Useful for troubleshooting GPU issues or when you want to reserve GPU resources for other applications. It will then use ALL CPU cores, except core 0.

**GPU Device:** When GPU acceleration is enabled, select which GPU to use. Auto-select chooses the first discrete GPU it finds, preferring NVIDIA over AMD over Intel. (I'm sorry, not my idea) If you have multiple GPUs, select a specific one from the dropdown.

### 📤 Output

**Output Mode:** Controls how transcribed text reaches applications. Injection uses keyboard simulation (fastest). Clipboard uses Ctrl+V paste (works with applications that block keyboard injection). Auto tries injection first and falls back to clipboard if needed.

**Sound Effects:** Plays audio feedback for recording start, stop, and errors. Uses custom open-sourced sounds.

### 🎙️ Recording

**Max Duration:** Maximum recording length from 1 to 600 seconds. Default is 300 seconds (5 minutes). Recordings that reach this limit are automatically stopped and transcribed.

---

## 🖥️ Command Line Reference

CLD provides a command-line interface for automation and troubleshooting.

### Global Options

`--version` or `-V` prints the version number and exits.

`--debug` shows a console window for debugging output. Essential for troubleshooting issues with GPU detection, model loading, or hotkey behavior.

### Commands

**cld** (no arguments): Starts the daemon in background with the overlay visible. This is the default behavior when double-clicking the executable.

**cld daemon run**: Runs the daemon in foreground mode (blocking). Useful for development. Add `--overlay` to show the floating overlay and `--log-level DEBUG` for verbose output.

**cld daemon start**: Starts the daemon. Add `--background` for detached operation and `--overlay` for the floating overlay.

**cld daemon stop**: Stops the running daemon.

**cld daemon status**: Shows whether the daemon is running and its process ID.

**cld setup**: Runs the first-time setup wizard. Options include `--skip-model-download`, `--skip-audio-test`, `--skip-hotkey-test`, and `--no-start`.

---

## ⚡ Performance Expectations

Transcription speed depends on your hardware and the selected model.

### CPU Performance

Without GPU acceleration, expect these approximate speeds for transcribing 10 seconds of audio:

| Model | Time |
|-------|------|
| small | 3-5 seconds |
| medium-q5_0 | 6-10-25 seconds |
| medium | 10-15-30 seconds |

These times assume a modern CPU with AVX2 support. Older CPUs may be CONSIDERABLY slower.

### GPU Performance

With Vulkan GPU acceleration on a mid-range to high-end GPU, the medium-q5_0 model transcribes 10 seconds of audio in approximately 1-2 seconds.

High-end GPUs achieve even faster results. An RTX 4090 can achieve real-time factors of 30-50x, meaning 30 seconds of audio transcribes in under 1 second. In testing, a 127-second recording completed in approximately 2.5 seconds total (split into three chunks of 1.44s, 0.87s, and 0.24s).

---

## 📁 File Locations

| Item | Location |
|------|----------|
| Settings | `%LOCALAPPDATA%\CLD\settings.json` |
| Models | `%LOCALAPPDATA%\CLD\models\` |
| Model checksums | `%LOCALAPPDATA%\CLD\models\models.json` |

The `%LOCALAPPDATA%` folder is typically `C:\Users\YourName\AppData\Local`.

---

## 🔧 Troubleshooting

<details>
<summary><b>🔇 Model and Download Issues</b></summary>

**Model not found on startup:** The model setup dialog appears automatically when the configured model is missing. Select a model and click Download. If automatic download fails, manual download URLs are displayed. Download the .bin file directly and place it in `%LOCALAPPDATA%\CLD\models\`.

**Download fails:** Check your internet connection. GGML model files are available at `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{model}.bin` where `{model}` is small, medium-q5_0, or medium.

**Model loads slowly:** Check if GPU acceleration is working. Run with `--debug` and look for "Vulkan" in the output. If you only see CPU features (SSE3, AVX, AVX2), GPU support is not active.

</details>

<details>
<summary><b>🐢 Transcription Issues</b></summary>

**Transcription too slow:** Try a smaller model or enable GPU acceleration. Ensure your GPU drivers are up to date.

**Out of memory:** Try a smaller model. The medium-q5_0 model requires approximately 2 GB of RAM, while the full medium model requires approximately 3 GB.

**Wrong language output:** CLD preserves the original spoken language. If you're getting English from non-English speech, most probably force translation to English check box is enabled in settings.

</details>

<details>
<summary><b>⌨️ Input and Output Issues</b></summary>

**Text not appearing:** Some applications block keyboard injection for security. Change Output Mode to "clipboard" in settings, if auto mode used - try Ctrl+V to paste instead.

**Text appears in wrong window:** Ensure the target application is focused before pressing the hotkey. CLD tracks the active window when recording starts.

</details>

<details>
<summary><b>🔑 Hotkey Issues</b></summary>

**Hotkey not working:** Check for conflicts with other applications. Some games and applications capture certain keys globally. Try a different activation key through Settings. Also verify that Hotkey Enabled is checked.

**Hotkey triggers twice:** Toggle mode includes a 300ms debounce. If you're still experiencing double-triggers, try a different key or switch to push-to-talk mode.

</details>

<details>
<summary><b>🎮 GPU Issues</b></summary>

**GPU not detected:** Ensure your GPU drivers are up to date. Vulkan support requires relatively recent drivers. Run with `--debug` to see GPU detection output.

**Vulkan not found:** The Vulkan runtime is included with modern GPU drivers. If missing, download the Vulkan Runtime from the LunarG website.

</details>

<details>
<summary><b>🖥️ Display Issues</b></summary>

**Overlay not appearing:** For the standalone executable, ensure the _internal folder exists alongside CLD.exe. For development builds, verify tkinter is properly installed with your Python distribution.

**Debug console shows nothing:** The debug flag must appear early in the command. Use `CLD.exe --debug daemon run --overlay`.

</details>

---

## 📝 Technical Notes

CLD uses a daemon-based architecture where a background process runs continuously, listening for hotkey events and coordinating audio capture, transcription, and text output.

The threading model places tkinter in the main thread (required on Windows for mouse events), with pystray running detached for system tray integration. Cross-thread communication uses queue-based state updates for thread safety.

Audio is captured at 16kHz sample rate (Whisper's native rate) using sounddevice. Recordings over 30 seconds are automatically chunked into segments matching Whisper's 30-second context window.

---

## 🛠️ Building pywhispercpp with Vulkan

CLD uses a modified pywhispercpp build with GPU device selection support. The source code with modifications is in `pywhispercpp-src/`.

<details>
<summary><b>Prerequisites</b></summary>

- Visual Studio 2022 Build Tools (C++ compiler and CMake)
- Python 3.12 (exclude Python 3.14 from PATH during build)
- Vulkan SDK (from https://vulkan.lunarg.com/)
- GPU drivers with Vulkan support

</details>

<details>
<summary><b>Build Steps</b></summary>

1. Open "Developer Command Prompt for VS 2022"
2. Navigate to the build-scripts directory:
   ```
   cd D:\claudecli-dictate2\build-scripts
   ```
3. Run the build script:
   ```
   build_vulkan_py312.bat
   ```

The build produces these key files in `.venv/Lib/site-packages/`:
- `_pywhispercpp.cp312-win_amd64.pyd` - Python extension module
- `ggml-vulkan.dll` - Vulkan compute backend (~55MB)
- `whisper.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll` - Core libraries

</details>

<details>
<summary><b>Modifications from Upstream</b></summary>

The `pywhispercpp-src/` directory contains these modifications to the upstream pywhispercpp:

1. `src/main.cpp`: Added `whisper_init_from_file_with_params` binding exposing `use_gpu` and `gpu_device` parameters
2. `pywhispercpp/model.py`: Added `use_gpu` and `gpu_device` constructor parameters with fallback for non-modified builds

These modifications allow CLD to select specific GPU devices on multi-GPU systems and explicitly enable/disable GPU acceleration.

</details>

---

## 📜 License

CLD is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see https://www.gnu.org/licenses/.

Source code: https://github.com/MarvinFS/CLD

---

## 🙏 Credits and Origin

CLD began as a fork of [claude-stt](https://github.com/jarrodwatts/claude-stt) by Jarrod Watts (MIT License), a Claude Code plugin for speech-to-text input. While the original project provided the foundation (audio recording pipeline, hotkey handling, basic overlay concept), CLD has been extensively reworked into a different application.

Major changes from the original:

- Replaced faster-whisper/Moonshine engines with pywhispercpp for simpler deployment and Vulkan GPU support
- Dropped cross-platform support to focus on Windows-specific features (DWM dark theming, proper Alt Gr handling, virtual key code mapping, system tray behavior)
- Rewrote the overlay from scratch with multi-mode states (tiny, recording, processing) and real audio visualization
- Added full settings dialog with hardware detection and GPU device selection
- Switched from TOML config in home directory to JSON in LOCALAPPDATA
- Added model management with download progress, hash verification, and automatic setup
- Implemented proper PyInstaller packaging with runtime hooks for tkinter, numpy, and pywhispercpp

The core recording and transcription logic remains inspired by the original, but the user interface, configuration system, and Windows integration are entirely new.

### Third-Party Credits

#### Speech Recognition Models

| Model | Author | License |
|-------|--------|---------|
| [Whisper](https://github.com/openai/whisper) | OpenAI | MIT |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | Georgi Gerganov | MIT |
| [GGML Models](https://huggingface.co/ggerganov/whisper.cpp) | Georgi Gerganov | MIT |

#### Core Dependencies

| Library | Author | License |
|---------|--------|---------|
| [pywhispercpp](https://github.com/abdeladim-s/pywhispercpp) | Abdeladim Sadiki | MIT |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | Matthias Geier | MIT |
| [pynput](https://github.com/moses-palmer/pynput) | Moses Palmer | LGPL-3.0 |
| [pystray](https://github.com/moses-palmer/pystray) | Moses Palmer | LGPL-3.0 |
| [keyboard](https://github.com/boppreh/keyboard) | Lucas Boppre Niehues | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | Jeffrey A. Clark et al. | MIT-CMU |
| [numpy](https://github.com/numpy/numpy) | NumPy Developers | BSD-3-Clause |
| [pyperclip](https://github.com/asweigart/pyperclip) | Al Sweigart | BSD-3-Clause |
| [psutil](https://github.com/giampaolo/psutil) | Giampaolo Rodola | BSD-3-Clause |

#### Build and Development

| Tool | Author | License |
|------|--------|---------|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | PyInstaller Development Team | GPL-2.0 |
| [UPX](https://github.com/upx/upx) | Markus Oberhumer, Laszlo Molnar | GPL-2.0 |
| [Vulkan SDK](https://vulkan.lunarg.com/) | LunarG, Khronos Group | Apache-2.0 |

#### Sound Effects

| Source | Author | License |
|--------|--------|---------|
| [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | Kenney.nl | CC0 (Public Domain) |
| [Kenney Digital SFX](https://opengameart.org/content/63-digital-sound-effects-lasers-phasers-space-etc) | Kenney.nl (KORG microKORG) | CC0 (Public Domain) |

### Acknowledgments

This software is based in part on the work of the Independent JPEG Group (libjpeg-turbo, bundled with Pillow).

Portions of this software use the FreeType library, copyright The FreeType Project.

The Whisper models were trained by OpenAI and converted to GGML format by Georgi Gerganov and the whisper.cpp community.

---

<div align="center">

**Made with ❤️ for the voice-typing community**

[⬆️ Back to Top](#️-cld---claudecli-dictate)

</div>

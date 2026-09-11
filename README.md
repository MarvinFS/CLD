<div align="center">

# CLD - ClaudeCli-Dictate

Version 0.9.0 | Voice dictation that stays on your machine

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows)](https://github.com/MarvinFS/CLD)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![Vulkan](https://img.shields.io/badge/GPU-Vulkan%20Accelerated-AC162C?logo=vulkan)](https://vulkan.org)

</div>

CLD records your voice, turns it into text on your own computer, and types the text into the window you're working in. That can be an AI coding agent in a terminal, Outlook, VS Code, or a form in your browser. Your audio never leaves the machine, and CLD keeps the recording in memory only until it types the text. It needs no account, and the default engine runs on the CPU, so you don't need a GPU.

<div align="center">

https://github.com/user-attachments/assets/581e5ec1-b7af-47f8-93b2-9f47d97e5a8f

</div>

## Quick start

1. Download the installer from the [releases page](https://github.com/MarvinFS/CLD/releases) and run it. It also updates an existing installation.
2. Start CLD from the Start menu. On the first start, the model setup dialog offers the Nemotron speech model, a download of about 475 MB.
3. Click where you want the text, hold the right Alt key while you speak, and let go when you're done.

CLD types what you said at the cursor. While you speak, the overlay shows a timer and bars that follow your voice. It stays in the system tray until you quit it.

## Models and hardware

CLD runs on Windows 10 and 11. You pick the engine and the model in Settings. CLD downloads a model the first time you use it and checks the file against a pinned SHA-256 hash.

| Model | Use it for | Hardware | Download | Time for 30 s of speech |
|---|---|---|---|---|
| Nemotron 3.5 (default) | PCs without a GPU | CPU with 4 cores | 475 MB | 6 s on the CPU |
| Whisper Large v3 Turbo Q5 | PCs with a GPU, most accurate | GPU with about 1 GB of free video memory, or 4 CPU cores | 574 MB | 0.2 s on the GPU, 23 s on the CPU |
| Whisper Medium Q5 | Translation into English | GPU with about 1 GB of free video memory, or 4 CPU cores | 539 MB | 0.4 s on the GPU, 14 s on the CPU |

The times are approximate and come from a Ryzen 7 7800X3D with 8 cores and an RTX 4090. Whisper works on 30-second windows, so a short dictation takes about as long as a 30-second one. The first time Whisper runs on a GPU, the dictation takes about 10 seconds longer while the graphics driver compiles its shaders. The driver saves them on disk, so later dictations and restarts don't wait. It compiles them again only after a driver update or if its shader cache gets cleared.

Every model also needs 2 GB of free RAM. Whisper needs a CPU with SSE4.1, which most processors from 2013 on have, and runs much faster with AVX2. The model setup dialog shows the RAM and CPU cores each model needs. For Whisper, it warns you when your PC has less or the CPU lacks AVX2.

Only Whisper uses a GPU, through Vulkan. Vulkan comes with current drivers for NVIDIA GeForce GTX 10-series and newer, AMD Radeon RX 5000, 6000, and 7000 series, Radeon graphics in Ryzen processors, and Intel Arc, UHD, and Iris graphics.

Whisper Medium Q5 is the only model that translates into English. Nemotron and Turbo type the language you spoke, so Settings hides Translate to English for them.

Nemotron understands 40 locales, including English and Russian. Whisper understands 99 languages and detects which one you speak.

<details>
<summary>Whisper's 99 languages</summary>

Afrikaans, Albanian, Amharic, Arabic, Armenian, Assamese, Azerbaijani, Bashkir, Basque, Belarusian, Bengali, Bosnian, Breton, Bulgarian, Burmese, Cantonese, Catalan, Chinese, Croatian, Czech, Danish, Dutch, English, Estonian, Faroese, Finnish, French, Galician, Georgian, German, Greek, Gujarati, Haitian Creole, Hausa, Hawaiian, Hebrew, Hindi, Hungarian, Icelandic, Indonesian, Italian, Japanese, Javanese, Kannada, Kazakh, Khmer, Korean, Lao, Latin, Latvian, Lingala, Lithuanian, Luxembourgish, Macedonian, Malagasy, Malay, Malayalam, Maltese, Maori, Marathi, Mongolian, Myanmar, Nepali, Norwegian, Occitan, Pashto, Persian, Polish, Portuguese, Punjabi, Romanian, Russian, Sanskrit, Serbian, Shona, Sindhi, Sinhala, Slovak, Slovenian, Somali, Spanish, Sundanese, Swahili, Swedish, Tagalog, Tajik, Tamil, Tatar, Telugu, Thai, Tibetan, Turkish, Turkmen, Ukrainian, Urdu, Uzbek, Vietnamese, Welsh, Yiddish, Yoruba

</details>

## Settings

Open Settings from the tray icon's menu or the gear icon on the overlay. Most changes take effect when you click Save. CLD keeps the settings in `%LOCALAPPDATA%\CLD\settings.json` and the models in `%LOCALAPPDATA%\CLD\models\`.

| Setting | What it does |
|---|---|
| Activation key | The key you record with, the right Alt key (Alt Gr) by default. Add Ctrl, Shift, or Alt if another program uses the key. Clear Hotkey Enabled to pause CLD. |
| Mode | Push-to-talk, the default, records while you hold the key. Toggle starts on one press and stops on the next, and two presses within 300 ms count as one. |
| Engine, Model | Switch the engine or the model without a restart. CLD loads the new model before it unloads the old one, so a failed switch keeps the previous one working. |
| Language | Nemotron only. The language you speak, or Auto. |
| Translate to English | Whisper Medium Q5 only. Types English whatever language you speak. |
| Type while speaking | On by default, for Whisper on a GPU. CLD types while you speak and fixes words as more speech makes them clear. When you stop, CLD replaces it with a transcription of the whole recording. Nemotron, and Whisper on the CPU, still type after you stop. Output Mode Clipboard turns it off. |
| Force CPU Only, GPU Device | Whisper only, and both take effect after a restart. Force CPU Only keeps Whisper on the CPU even when you have a GPU. GPU Device picks the GPU when you have several, and Auto-select uses the first one Vulkan reports. |
| Output Mode | Auto, the default, types the text and copies it to the clipboard when a window blocks typing. Injection types it, and Clipboard pastes it with Ctrl+V. |
| Sound Effects | Plays short sounds when recording starts and stops and when something goes wrong. |
| Input Device | The microphone. System default follows Windows. CLD lists the microphones at startup, so restart it after you connect a new one. |
| Max Duration | The longest recording, 1 to 600 seconds, 300 by default. CLD stops a recording that reaches it and transcribes it. |

## Command line

`cld` stands for `CLD.exe`, or for `python -m cld.cli` when you run from source.

| Command | What it does |
|---|---|
| `cld` | Starts CLD in the background with the overlay, like the Start menu shortcut. |
| `cld --debug` | Runs CLD in the foreground and opens a console with the debug log. |
| `cld --version` | Prints the version. |
| `cld status` | Shows whether CLD is running, its process ID, and the engine and hotkey it uses. |
| `cld stop` | Stops CLD. |
| `cld run --overlay` | Runs CLD in the foreground. Add `--log-level DEBUG` for more detail. |
| `cld setup` | Runs first-time setup. `--skip-model-download`, `--skip-audio-test`, `--skip-hotkey-test`, and `--no-start` skip its steps. |
| `cld transcribe <wav> [out.txt]` | Transcribes a 16-bit WAV file with the configured engine and prints or saves the text. |

## Troubleshooting

| Problem | What to do |
|---|---|
| Nothing gets transcribed | CLD may record from the wrong microphone, such as an unused input on an audio interface. Pick yours in Settings > Recording > Input Device. |
| The text doesn't appear | The window blocks typed input. With Output Mode on Auto, press Ctrl+V after the dictation, or set Output Mode to Clipboard. |
| The text lands in the wrong window | CLD types into the window that was active when recording started. Click the target window before you press the key. |
| The key does nothing | Another program may grab the key. Pick another key in Settings and check that Hotkey Enabled is on. |
| English instead of your language | Turn off Translate to English. |
| Whisper is slow | Start `CLD.exe --debug` and look for "Vulkan" in the log. If it's missing, Whisper runs on the CPU. Update the GPU driver, or install the Vulkan Runtime from LunarG. |
| A model download fails | The model setup dialog lists the download links. Whisper models come from `https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-<model>.bin`, where `<model>` is `medium-q5_0` or `large-v3-turbo-q5_0`. Save the file in `%LOCALAPPDATA%\CLD\models\`. |
| The overlay doesn't appear | The `_internal` folder must sit next to `CLD.exe`. |

## Building from source

Running or building CLD from source needs Python 3.12 and a Vulkan build of pywhispercpp, because the PyPI package lacks GPU support. [build.md](build.md) covers the setup and the PyInstaller build. `prebuilt/` holds ready-made Vulkan binaries for Python 3.12. `pywhispercpp-src/` holds CLD's modified pywhispercpp, which adds the `use_gpu` and `gpu_device` parameters so CLD can pick a GPU or stay on the CPU.

## License

CLD is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see https://www.gnu.org/licenses/.

Source code: https://github.com/MarvinFS/CLD

## Credits and origin

CLD began as a fork of [claude-stt](https://github.com/jarrodwatts/claude-stt) by Jarrod Watts (MIT License), a Claude Code plugin for speech-to-text input. The recording and transcription logic is still inspired by the original, but the user interface, settings, and Windows integration are new. The fork dropped cross-platform support for Windows features such as dark title bars and Alt Gr handling, and it switched speech recognition to pywhispercpp for Vulkan GPU support. It also rewrote the overlay and added a settings dialog with hardware detection, JSON settings in LOCALAPPDATA, model management with hash checks, and PyInstaller packaging.

### Third-party credits

#### Speech recognition models

| Model | Author | License |
|-------|--------|---------|
| [Whisper](https://github.com/openai/whisper) | OpenAI | MIT |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | Georgi Gerganov | MIT |
| [GGML Models](https://huggingface.co/ggerganov/whisper.cpp) | Georgi Gerganov | MIT |
| [Nemotron-3.5-ASR-Streaming-0.6B](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b) | NVIDIA (ONNX export: [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)) | OpenMDW-1.1 (ONNX export: MIT) |

#### Core dependencies

| Library | Author | License |
|---------|--------|---------|
| [pywhispercpp](https://github.com/abdeladim-s/pywhispercpp) | Abdeladim Sadiki | MIT |
| [onnxruntime](https://github.com/microsoft/onnxruntime) | Microsoft | MIT |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | Matthias Geier | MIT |
| [pynput](https://github.com/moses-palmer/pynput) | Moses Palmer | LGPL-3.0 |
| [pystray](https://github.com/moses-palmer/pystray) | Moses Palmer | LGPL-3.0 |
| [keyboard](https://github.com/boppreh/keyboard) | Lucas Boppre Niehues | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | Jeffrey A. Clark et al. | MIT-CMU |
| [numpy](https://github.com/numpy/numpy) | NumPy Developers | BSD-3-Clause |
| [pyperclip](https://github.com/asweigart/pyperclip) | Al Sweigart | BSD-3-Clause |
| [psutil](https://github.com/giampaolo/psutil) | Giampaolo Rodola | BSD-3-Clause |

#### Build and development

| Tool | Author | License |
|------|--------|---------|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | PyInstaller Development Team | GPL-2.0 |
| [UPX](https://github.com/upx/upx) | Markus Oberhumer, Laszlo Molnar | GPL-2.0 |
| [Vulkan SDK](https://vulkan.lunarg.com/) | LunarG, Khronos Group | Apache-2.0 |

#### Sound effects

| Source | Author | License |
|--------|--------|---------|
| [Kenney Interface Sounds](https://kenney.nl/assets/interface-sounds) | Kenney.nl | CC0 (Public Domain) |
| [Kenney Digital SFX](https://opengameart.org/content/63-digital-sound-effects-lasers-phasers-space-etc) | Kenney.nl (KORG microKORG) | CC0 (Public Domain) |

### Acknowledgments

This software is based in part on the work of the Independent JPEG Group (libjpeg-turbo, bundled with Pillow).

Portions of this software use the FreeType library, copyright The FreeType Project.

The Whisper models were trained by OpenAI and converted to GGML format by Georgi Gerganov and the whisper.cpp community.

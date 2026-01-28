# Original Claude-STT Plugin Analysis

This document analyzes the original claude-stt plugin functionality for reference during CLD development.

## Original claude-stt Capabilities

### Core Features

1. Push-to-talk voice dictation with configurable hotkey (default: Ctrl+Shift+Space)
2. Toggle mode alternative (press to start, press again to stop)
3. Local transcription via Moonshine ONNX or faster-whisper engines
4. Text injection via pynput keyboard simulation or clipboard fallback
5. Window focus restoration after transcription
6. Optional floating overlay with waveform animation
7. Sound effects for recording start/stop/complete/error
8. TOML-based configuration

### Components to Reuse

#### Audio Recording Pipeline (recorder.py)
- Uses sounddevice for audio capture
- Configurable sample rate (16kHz default)
- Maximum recording duration limit
- Float32 mono audio output for STT engines

#### Transcription Engines
- `engines/moonshine.py` - Moonshine ONNX (~400MB model, fast inference)
- `engines/whisper.py` - faster-whisper (medium model ~1.5GB, better multilingual)

#### Hotkey Listener (hotkey.py)
- Uses pynput for global hotkey detection
- Supports both toggle and push-to-talk modes
- Queue-based event handling for thread safety
- 300ms debounce for toggle mode
- Special handling for Alt_Gr key (separate from Alt_L/Alt_R)

#### Keyboard Output (keyboard.py)
- Injection via pynput Controller.type()
- Clipboard fallback via pyperclip
- Auto-detection of injection capability
- Window focus restoration before typing

#### Sound Effects (sounds.py)
- Plays WAV files for feedback
- Events: start, stop, complete, error
- Uses winsound on Windows

#### Overlay (overlay.py)
- tkinter-based floating window
- Dark theme matching macOS style
- Waveform visualization with 12 bars
- States: ready, recording, transcribing, error
- Draggable, right-click to close

### Threading Architecture

1. Main thread: tkinter mainloop (when overlay enabled)
2. Hotkey listener: pynput runs in background thread
3. Transcription: One-shot daemon thread per recording
4. State updates: Queue-based for thread safety

### Key Patterns

1. `_is_transcribing` flag prevents concurrent transcriptions
2. `DETACHED_PROCESS` NOT used when overlay enabled (tkinter provides message pump)
3. Unicode print errors handled with try/except and ASCII fallback
4. Status file written BEFORE print to avoid encoding crashes

### Configuration Structure (TOML)

```toml
[claude-stt]
hotkey = "ctrl+shift+space"
mode = "toggle"  # or "push-to-talk"
engine = "moonshine"  # or "whisper"
moonshine_model = "moonshine/base"
whisper_model = "medium"
sample_rate = 16000
max_recording_seconds = 300
output_mode = "auto"  # or "injection" or "clipboard"
sound_effects = true
```

### Plugin Structure

- `commands/` - Slash commands (setup, start, stop, status, config) as markdown
- `hooks/hooks.json` - Claude Code plugin hooks
- `scripts/setup.py` - Bootstrap script for venv, deps, model download
- `.claude-plugin/plugin.json` - Plugin metadata

## Features NOT Being Reused

1. Claude Code plugin structure (commands/, hooks/) - CLD is standalone
2. TOML config - Replaced with JSON in LOCALAPPDATA
3. Legacy config path (~/.claude/plugins/) - Using LOCALAPPDATA/CLD/

## New Features for CLD

1. Multi-mode overlay (tiny, recording, processing)
2. System tray integration via pystray
3. Settings popup from gear button
4. Full settings dialog from tray
5. Key scanner for activation key capture
6. Hardware detection for model recommendations
7. JSON-based configuration
8. Standalone application (not a Claude Code plugin)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Threading complexity | Follow patterns from windows-tray-app-patterns.md |
| Hotkey conflicts | KeyScanner validates; clear error if conflict |
| Focus stealing by dialogs | Use transient/grab_set/lift/focus_force pattern |
| Unicode encoding on Windows | ASCII fallback; critical ops before print |

## References

- Original repo: https://github.com/jarrodwatts/claude-stt
- Windows patterns: docs/windows-tray-app-patterns.md (scripts workspace)

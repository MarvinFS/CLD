# Audio Spectrum Visualization for Voice Apps

This document captures lessons learned from implementing real-time audio spectrum visualization for voice recording applications.

## Overview

Voice recording apps benefit from visual feedback showing audio levels. A spectrum analyzer with multiple frequency bands provides more informative feedback than a simple volume meter.

## Key Insight: Focus on Voice Frequencies

Human voice occupies a specific frequency range. Attempting to visualize the full audio spectrum (20Hz-20kHz) results in poor voice visualization because most of the spectrum is empty during speech.

### Voice Frequency Ranges

| Component | Frequency Range | Description |
|-----------|-----------------|-------------|
| Fundamental (male) | 85-180 Hz | Base pitch of male voice |
| Fundamental (female) | 165-255 Hz | Base pitch of female voice |
| Formants | 300-3400 Hz | Vowel characteristics, intelligibility |
| Consonants | 2000-4000 Hz | "S", "T", "F" sounds |
| Sibilants | 4000-8000 Hz | Sharp "S" and "SH" sounds |

For visualization, the most useful range is 200-4000 Hz, which captures the majority of speech content.

## Implementation Approaches

### Approach A: Full Spectrum with Fake Bass (Failed)

Initial approach: Map 16 bars to 85-8000 Hz using logarithmic spacing, then synthesize fake bass response from overall volume level.

```python
# Logarithmic frequency bands from 85Hz to 8kHz
for i in range(16):
    f_low = 85 * (8000 / 85) ** (i / 16)
    f_high = 85 * (8000 / 85) ** ((i + 1) / 16)
    # ... compute FFT magnitude for band

# Synthesize bass (bands 0-7) from overall level
for i in range(8):
    noise = random.uniform(0.8, 1.2)
    bass_weight = 1.2 - (i * 0.1)
    bands[i] = level * bass_weight * noise
```

Problems with this approach:
- Bass bands were maxed out constantly regardless of voice content
- Fake randomization looked unnatural
- Right side (high frequencies) didn't respond to voice

### Approach B: Voice-Focused Spectrum (Recommended)

Focus all 16 bars on the actual voice frequency range (200-4000 Hz).

```python
# Voice-focused frequency range
min_freq, max_freq = 200, 4000
for i in range(16):
    f_low = min_freq * (max_freq / min_freq) ** (i / 16)
    f_high = min_freq * (max_freq / min_freq) ** ((i + 1) / 16)
    bin_low = int(f_low * n_bins * 2 / sample_rate)
    bin_high = int(f_high * n_bins * 2 / sample_rate)
    band_mag = np.mean(magnitudes[bin_low:bin_high])
    bands.append(band_mag)

# Pure FFT normalization, no fake bass
max_mag = max(bands) if bands else 1.0
if max_mag > 0:
    bands = [min(1.0, (b / max_mag) * level * 3.0) for b in bands]
```

Benefits:
- All 16 bars respond to actual voice content
- Left bars (200-400 Hz): Fundamental tones, vowels
- Middle bars (400-1500 Hz): Formants, vowel character
- Right bars (1500-4000 Hz): Consonants, speech clarity
- Natural variation without artificial randomization

### FFT Computation Details

For a 16kHz sample rate with 512-sample chunks:
- FFT produces 257 bins (N/2 + 1 for real FFT)
- Each bin represents ~31.25 Hz (16000 / 512)
- Bin index = frequency * n_bins * 2 / sample_rate

```python
import numpy as np

def compute_spectrum_bands(audio_chunk, sample_rate=16000, n_bands=16):
    """Compute frequency band magnitudes for visualization."""
    fft = np.fft.rfft(audio_chunk)
    magnitudes = np.abs(fft)
    n_bins = len(magnitudes)

    bands = []
    min_freq, max_freq = 200, 4000

    for i in range(n_bands):
        f_low = min_freq * (max_freq / min_freq) ** (i / n_bands)
        f_high = min_freq * (max_freq / min_freq) ** ((i + 1) / n_bands)

        bin_low = int(f_low * n_bins * 2 / sample_rate)
        bin_high = int(f_high * n_bins * 2 / sample_rate)
        bin_low = max(0, min(bin_low, n_bins - 1))
        bin_high = max(bin_low + 1, min(bin_high, n_bins))

        band_mag = np.mean(magnitudes[bin_low:bin_high])
        bands.append(band_mag)

    return bands
```

## Logarithmic vs Linear Spacing

Use logarithmic frequency spacing because:
1. Human hearing is logarithmic (octaves, not Hz)
2. Voice formants are distributed logarithmically
3. Equal visual spacing maps to perceptually equal frequency differences

With 16 bands from 200-4000 Hz (logarithmic):
- Band 0: 200-252 Hz
- Band 8: 800-1008 Hz
- Band 15: 3175-4000 Hz

## Normalization

Normalize band magnitudes relative to the current frame's maximum, then scale by overall audio level:

```python
max_mag = max(bands) if bands else 1.0
if max_mag > 0:
    # Normalize to peak, then scale by level
    bands = [min(1.0, (b / max_mag) * level * multiplier) for b in bands]
```

The multiplier (2.5-3.0) controls sensitivity. Higher values make quiet speech more visible but can cause clipping during loud speech.

## Threading Considerations

Audio callbacks run in a separate thread from the UI. Use thread-safe communication:

```python
class AudioRecorder:
    def __init__(self):
        self._spectrum_lock = threading.Lock()
        self._spectrum: list[float] = [0.0] * 16

    def _audio_callback(self, indata, frames, time, status):
        # Compute spectrum in audio thread
        bands = compute_spectrum_bands(indata[:, 0])

        # Thread-safe update
        with self._spectrum_lock:
            self._spectrum = bands

    def get_spectrum(self) -> list[float]:
        """Get current spectrum (thread-safe)."""
        with self._spectrum_lock:
            return self._spectrum.copy()
```

## UI Integration

Poll the spectrum from the UI thread at ~30-60 FPS:

```python
class SpectrumVisualizer:
    def __init__(self, recorder):
        self._recorder = recorder
        self._update_interval = 33  # ~30 FPS

    def _update_bars(self):
        if not self._is_recording:
            return

        spectrum = self._recorder.get_spectrum()
        for i, bar in enumerate(self._bars):
            height = int(spectrum[i] * self._max_height)
            bar.configure(height=height)

        self._root.after(self._update_interval, self._update_bars)
```

## Summary

For voice visualization:
1. Focus on 200-4000 Hz, not full spectrum
2. Use logarithmic frequency spacing
3. Normalize per-frame, then scale by level
4. Don't fake bass - let FFT show real content
5. Thread-safe spectrum updates via lock
6. Poll at 30-60 FPS for smooth animation

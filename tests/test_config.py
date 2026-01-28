import unittest

from cld.config import Config, ActivationConfig, EngineConfig, OutputConfig, RecordingConfig


class ConfigTests(unittest.TestCase):
    def test_config_validation_clamps_invalid_values(self):
        """Test that config validation clamps invalid values to defaults."""
        config = Config(
            activation=ActivationConfig(mode="bad"),
            engine=EngineConfig(type="nope"),
            output=OutputConfig(mode="wat"),
            recording=RecordingConfig(max_seconds=0, sample_rate=8000),
        ).validate()

        # Mode should default to push_to_talk
        self.assertEqual(config.activation.mode, "push_to_talk")
        # Engine should default to whisper
        self.assertEqual(config.engine.type, "whisper")
        # Output mode should default to auto
        self.assertEqual(config.output.mode, "auto")
        # Max seconds should be clamped to minimum 1
        self.assertEqual(config.recording.max_seconds, 1)
        # Sample rate should be forced to 16000
        self.assertEqual(config.recording.sample_rate, 16000)

    def test_config_legacy_properties(self):
        """Test that legacy properties work with new config structure."""
        config = Config(
            activation=ActivationConfig(key="ctrl", mode="toggle"),
            engine=EngineConfig(type="whisper", whisper_model="small"),
            output=OutputConfig(mode="clipboard", sound_effects=False),
            recording=RecordingConfig(max_seconds=60, sample_rate=16000),
        )

        # Legacy property access
        self.assertEqual(config.hotkey, "<ctrl>")
        self.assertEqual(config.mode, "toggle")
        self.assertEqual(config.whisper_model, "small")
        self.assertEqual(config.output_mode, "clipboard")
        self.assertFalse(config.sound_effects)
        self.assertEqual(config.max_recording_seconds, 60)
        self.assertEqual(config.sample_rate, 16000)


if __name__ == "__main__":
    unittest.main()

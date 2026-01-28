import unittest

from cld.config import Config, EngineConfig
from cld.engine_factory import build_engine
from cld.engines.whisper import WhisperEngine
from cld.errors import EngineError


class EngineFactoryTests(unittest.TestCase):
    def test_unknown_engine_rejected(self):
        """Test that unknown engine type raises EngineError."""
        config = Config(engine=EngineConfig(type="whisper"))
        # Directly set engine type to invalid value (bypassing validation)
        config.engine.type = "unknown"
        with self.assertRaises(EngineError):
            build_engine(config)

    def test_whisper_engine_constructed(self):
        """Test that whisper engine is correctly constructed."""
        config = Config(engine=EngineConfig(type="whisper", whisper_model="tiny"))
        engine = build_engine(config)
        self.assertIsInstance(engine, WhisperEngine)
        self.assertEqual(engine.model_name, "tiny")


if __name__ == "__main__":
    unittest.main()

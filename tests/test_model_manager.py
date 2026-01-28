import unittest

from cld.model_manager import ModelManager, WHISPER_MODELS, get_models_dir


class ModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = ModelManager()

    def test_models_dir_in_localappdata(self):
        """Test that models directory is in LOCALAPPDATA."""
        models_dir = get_models_dir()
        # Should be under LOCALAPPDATA/CLD/models on Windows
        self.assertIn("CLD", str(models_dir))
        self.assertIn("models", str(models_dir))

    def test_all_models_have_required_fields(self):
        """Test that all model definitions have required fields."""
        required_fields = ["size", "ram", "vram", "cores", "description", "repo_id"]
        for name, info in WHISPER_MODELS.items():
            for field in required_fields:
                self.assertIn(
                    field, info, f"Model '{name}' missing field '{field}'"
                )

    def test_get_model_info_returns_correct_data(self):
        """Test that get_model_info returns correct model data."""
        info = self.manager.get_model_info("medium")
        self.assertIsNotNone(info)
        self.assertEqual(info["size"], "1.5GB")
        self.assertEqual(info["repo_id"], "Systran/faster-whisper-medium")

    def test_get_model_info_returns_none_for_unknown(self):
        """Test that get_model_info returns None for unknown models."""
        info = self.manager.get_model_info("unknown_model")
        self.assertIsNone(info)

    def test_get_download_url_format(self):
        """Test that download URLs are correctly formatted."""
        url = self.manager.get_download_url("medium")
        self.assertEqual(url, "https://huggingface.co/Systran/faster-whisper-medium")

    def test_check_cpu_capabilities(self):
        """Test CPU capability detection returns valid data."""
        can_run, supported, missing = self.manager.check_cpu_capabilities()
        # Should return boolean and lists
        self.assertIsInstance(can_run, bool)
        self.assertIsInstance(supported, list)
        self.assertIsInstance(missing, list)
        # On modern CPUs, should at least support something
        self.assertTrue(can_run or len(supported) == 0)

    def test_check_hardware_compatibility(self):
        """Test hardware compatibility check returns tuple."""
        compatible, warning = self.manager.check_hardware_compatibility("tiny")
        self.assertIsInstance(compatible, bool)
        self.assertIsInstance(warning, str)
        # Tiny model should be compatible on most hardware
        self.assertTrue(compatible)

    def test_check_hardware_compatibility_unknown_model(self):
        """Test hardware compatibility returns False for unknown model."""
        compatible, warning = self.manager.check_hardware_compatibility("unknown")
        self.assertFalse(compatible)
        self.assertIn("Unknown model", warning)


if __name__ == "__main__":
    unittest.main()

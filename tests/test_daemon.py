import unittest

from cld import daemon


class DaemonTests(unittest.TestCase):
    """Test daemon module functions."""

    def test_is_daemon_running_returns_bool(self):
        """Test that is_daemon_running returns a boolean."""
        result = daemon.is_daemon_running()
        self.assertIsInstance(result, bool)

    def test_daemon_status_returns_dict(self):
        """Test that daemon_status returns a dictionary."""
        result = daemon.daemon_status()
        self.assertIsInstance(result, dict)
        self.assertIn("running", result)
        self.assertIsInstance(result["running"], bool)

    def test_find_cld_processes_returns_list(self):
        """Test that _find_cld_processes returns a list of PIDs."""
        pids = daemon._find_cld_processes()
        self.assertIsInstance(pids, list)
        for pid in pids:
            self.assertIsInstance(pid, int)


if __name__ == "__main__":
    unittest.main()

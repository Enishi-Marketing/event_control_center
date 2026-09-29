import tempfile
import unittest
from pathlib import Path

from config.config import AppConfig


class ConfigPathTests(unittest.TestCase):
    def test_quoted_event_paths_save_without_outer_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = root / "Shared Drive" / "Events"
            local = root / "Local Events"

            class TestConfig(AppConfig):
                LOCAL_SETTINGS_PATH = root / "local_settings.conf"

            TestConfig.set_event_roots(f"'{shared}'", f'"{local}"')

            self.assertEqual(TestConfig.MULTIMEDIA_EVENTS_ROOT, shared)
            self.assertEqual(TestConfig.LOCAL_EVENTS_ROOT, local)
            self.assertEqual(TestConfig.EVENT_ROOT, shared / TestConfig.DEFAULT_EVENT_YEAR)
            self.assertEqual(
                TestConfig.LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"),
                f"MULTIMEDIA_EVENTS_ROOT={shared}\nLOCAL_EVENTS_ROOT={local}\n",
            )


if __name__ == "__main__":
    unittest.main()

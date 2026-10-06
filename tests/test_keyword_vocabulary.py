import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.keyword_service import KeywordVocabulary
from services.metadata_service import MetadataService
from services.search_service import MetadataSearchService


def event(keywords: list[str], created: str) -> SimpleNamespace:
    return SimpleNamespace(keywords=keywords, created=created, date="", last_modified="")


class KeywordVocabularyTests(unittest.TestCase):
    def test_case_whitespace_and_frequency_choose_one_canonical_keyword(self) -> None:
        vocabulary = KeywordVocabulary.from_events([
            event([" sports ", "SPORTS", "Sports Day"], "2025-01-01"),
            event(["Sports", "Sportsmanship"], "2025-02-01"),
        ])

        self.assertEqual(vocabulary.by_key["sports"].usage_count, 2)
        self.assertEqual(vocabulary.canonicalize([" SPORTS ", "sports", "Sports Day"]),
                         ["Sports", "Sports Day"])
        self.assertEqual([entry.display_value for entry in vocabulary.suggest("spor")],
                         ["Sports", "Sportsmanship", "Sports Day"])
        self.assertEqual(KeywordVocabulary.from_events([
            event(["stem"], "2025-01-01"), event(["STEM"], "2025-01-02"),
        ]).by_key["stem"].display_value, "STEM")

    def test_prefix_word_then_substring_and_recency(self) -> None:
        vocabulary = KeywordVocabulary.from_events([
            event(["Open House"], "2024-01-01"),
            event(["Open Day"], "2025-01-01"),
            event(["Campus Open"], "2026-01-01"),
            event(["Reopening"], "2026-02-01"),
        ])
        self.assertEqual([entry.display_value for entry in vocabulary.suggest("open")],
                         ["Open Day", "Open House", "Campus Open", "Reopening"])

    def test_new_keyword_is_free_form_and_appears_after_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "2025" / "first" / "Data" / "metadata.json"
            first.parent.mkdir(parents=True)
            first.write_text(json.dumps({
                "event_name": "First", "keywords": ["Sports", " Sports ", "Sports Day"],
                "created": "2025-01-01T10:00:00+00:00",
            }), encoding="utf-8")
            search = MetadataSearchService()
            vocabulary = KeywordVocabulary.from_events(search.build_index({"Events": root}).records)
            metadata = MetadataService().create_metadata(
                event_name="Second", event_date="2025.02.01", school_year="2024-2025",
                description="", keywords_text=[" sports ", "House   Competition", "house competition"],
                grades=[], keyword_vocabulary=vocabulary,
            )
            self.assertEqual(metadata["keywords"], ["House Competition", "Sports"])
            second = root / "2025" / "second" / "Data" / "metadata.json"
            second.parent.mkdir(parents=True)
            MetadataService().write_metadata(second, metadata)
            refreshed = KeywordVocabulary.from_events(search.build_index({"Events": root}).records)
            self.assertEqual(refreshed.suggest("house")[0].display_value, "House Competition")
            self.assertEqual(refreshed.by_key["sports"].usage_count, 2)
            self.assertIn("sports day", refreshed.by_key)


if __name__ == "__main__":
    unittest.main()

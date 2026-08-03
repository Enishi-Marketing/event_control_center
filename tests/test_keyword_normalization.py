import unittest

from services.google_sheets_service import GoogleSheetsService
from services.metadata_service import MetadataService
from services.search_service import MetadataSearchService


class KeywordNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata_service = MetadataService()

    def test_keywords_are_lowercase_clean_and_deduplicated(self) -> None:
        self.assertEqual(
            self.metadata_service.normalize_keywords(
                "Sports,,  FIELD   DAY, sports, , Assembly"
            ),
            ["assembly", "field day", "sports"],
        )

    def test_keyword_lists_can_contain_comma_separated_values(self) -> None:
        self.assertEqual(
            self.metadata_service.normalize_keywords(
                ["Sports,", "", " FIELD DAY ", "sports,Assembly"]
            ),
            ["assembly", "field day", "sports"],
        )

    def test_search_records_normalize_existing_metadata_keywords(self) -> None:
        search_service = MetadataSearchService()

        self.assertEqual(
            search_service.metadata_service.normalize_keywords(
                ["Sports,,", " FIELD   DAY ", "sports", ""]
            ),
            ["field day", "sports"],
        )

    def test_google_sheets_keyword_cell_has_no_blank_or_double_commas(self) -> None:
        sheets_service = GoogleSheetsService("creds.json", "spreadsheet", "Main")

        self.assertEqual(
            sheets_service._join_keywords(["Sports,,", " FIELD   DAY ", "sports", ""]),
            "field day, sports",
        )


if __name__ == "__main__":
    unittest.main()

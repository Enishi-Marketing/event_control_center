import json
from datetime import datetime
from pathlib import Path

from services.keyword_service import KeywordVocabulary


class MetadataService:
    """Builds event metadata dictionaries from UI input."""

    def create_metadata(
        self,
        event_name: str,
        event_date: str,
        school_year: str,
        description: str,
        keywords_text: object,
        grades: list[str],
        keyword_vocabulary: KeywordVocabulary | None = None,
    ) -> dict[str, object]:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        return {
            "version": 1,
            "event_name": event_name.strip(),
            "date": event_date.strip(),
            "school_year": school_year.strip(),
            "grades": grades,
            "keywords": (keyword_vocabulary or KeywordVocabulary()).canonicalize(keywords_text),
            "description": description.strip(),
            "photo_count": 0,
            "video_count": 0,
            "unedited_jpg_count": 0,
            "created": timestamp,
            "last_modified": timestamp,
        }

    def normalize_keywords(self, keywords_text: object) -> list[str]:
        keywords_by_key: dict[str, str] = {}
        raw_keywords = (
            keywords_text
            if isinstance(keywords_text, list | tuple | set)
            else [keywords_text]
        )

        for raw_value in raw_keywords:
            for raw_keyword in str(raw_value or "").split(","):
                keyword = " ".join(raw_keyword.strip().casefold().split())
                if not keyword:
                    continue

                keywords_by_key.setdefault(keyword, keyword)

        return sorted(keywords_by_key.values())

    def write_metadata(self, metadata_path: Path, metadata: dict[str, object]) -> None:
        metadata_path.write_text(
            json.dumps(metadata, indent=4) + "\n",
            encoding="utf-8",
        )

    def read_metadata(self, metadata_path: Path) -> dict[str, object]:
        with metadata_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("metadata.json must contain a JSON object.")

        return data

    def update_import_counts(
        self,
        metadata_path: Path,
        photos_imported: int,
        videos_imported: int,
    ) -> dict[str, object]:
        metadata = self.read_metadata(metadata_path)
        metadata["photo_count"] = int(metadata.get("photo_count", 0)) + photos_imported
        metadata["video_count"] = int(metadata.get("video_count", 0)) + videos_imported
        metadata["last_modified"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.write_metadata(metadata_path, metadata)
        return metadata

    def update_media_counts(
        self,
        metadata_path: Path,
        photo_count: int,
        video_count: int,
    ) -> dict[str, object]:
        metadata = self.read_metadata(metadata_path)
        metadata["photo_count"] = photo_count
        metadata["video_count"] = video_count
        metadata["last_modified"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.write_metadata(metadata_path, metadata)
        return metadata

    def update_unedited_jpg_count(
        self,
        metadata_path: Path,
        unedited_jpg_count: int,
    ) -> dict[str, object]:
        metadata = self.read_metadata(metadata_path)
        metadata["unedited_jpg_count"] = unedited_jpg_count
        metadata["last_modified"] = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        self.write_metadata(metadata_path, metadata)
        return metadata

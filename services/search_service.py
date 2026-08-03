import json
from dataclasses import dataclass
from pathlib import Path

from services.metadata_service import MetadataService


@dataclass(frozen=True)
class MetadataSearchRecord:
    """Searchable event metadata loaded from an event folder."""

    event_folder: Path
    metadata_path: Path
    source_name: str
    event_name: str
    date: str
    school_year: str
    grades: list[str]
    keywords: list[str]
    description: str
    photo_count: int
    video_count: int
    unedited_jpg_count: int
    created: str
    last_modified: str

    @property
    def total_media_count(self) -> int:
        return self.photo_count + self.video_count

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.event_name,
                self.date,
                self.school_year,
                " ".join(self.grades),
                " ".join(self.keywords),
                self.description,
                self.event_folder.name,
            ]
        ).casefold()


@dataclass(frozen=True)
class MetadataSearchIndex:
    """Records and autocomplete/filter values discovered from metadata files."""

    records: list[MetadataSearchRecord]
    suggestions: list[str]
    school_years: list[str]
    grades: list[str]
    keywords: list[str]
    errors: list[str]


class MetadataSearchService:
    """Discovers and loads Data/metadata.json files for local searching."""

    def __init__(self) -> None:
        self.metadata_service = MetadataService()

    def build_index(self, roots: dict[str, Path]) -> MetadataSearchIndex:
        records: list[MetadataSearchRecord] = []
        errors: list[str] = []
        seen_metadata_paths: set[Path] = set()

        for source_name, root in roots.items():
            if not root.exists() or not root.is_dir():
                continue

            for metadata_path in sorted(root.rglob("Data/metadata.json")):
                resolved_path = metadata_path.resolve()
                if resolved_path in seen_metadata_paths:
                    continue
                seen_metadata_paths.add(resolved_path)

                try:
                    records.append(self._load_record(source_name, metadata_path))
                except Exception as exc:
                    errors.append(f"{metadata_path}: {exc}")

        records.sort(key=lambda record: (record.date, record.event_name.casefold()))
        return MetadataSearchIndex(
            records=records,
            suggestions=self._suggestions(records),
            school_years=self._unique_values(record.school_year for record in records),
            grades=self._unique_values(grade for record in records for grade in record.grades),
            keywords=self._unique_values(
                keyword for record in records for keyword in record.keywords
            ),
            errors=errors,
        )

    def _load_record(
        self,
        source_name: str,
        metadata_path: Path,
    ) -> MetadataSearchRecord:
        with metadata_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("metadata.json must contain a JSON object.")

        return MetadataSearchRecord(
            event_folder=metadata_path.parent.parent,
            metadata_path=metadata_path,
            source_name=source_name,
            event_name=self._string(data.get("event_name")),
            date=self._string(data.get("date")),
            school_year=self._string(data.get("school_year")),
            grades=self._string_list(data.get("grades")),
            keywords=self.metadata_service.normalize_keywords(data.get("keywords")),
            description=self._string(data.get("description")),
            photo_count=self._int(data.get("photo_count")),
            video_count=self._int(data.get("video_count")),
            unedited_jpg_count=self._int(data.get("unedited_jpg_count")),
            created=self._string(data.get("created")),
            last_modified=self._string(data.get("last_modified")),
        )

    def _suggestions(self, records: list[MetadataSearchRecord]) -> list[str]:
        values: list[str] = []
        for record in records:
            values.extend(
                [
                    record.event_name,
                    record.date,
                    record.school_year,
                    record.event_folder.name,
                ]
            )
            values.extend(record.grades)
            values.extend(record.keywords)
        return self._unique_values(values)

    def _unique_values(self, values: object) -> list[str]:
        unique: dict[str, str] = {}
        for value in values:
            text = str(value).strip()
            if text:
                unique.setdefault(text.casefold(), text)
        return sorted(unique.values(), key=str.casefold)

    def _string(self, value: object) -> str:
        return "" if value is None else str(value).strip()

    def _string_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _int(self, value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

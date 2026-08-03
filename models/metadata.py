from dataclasses import dataclass, field


@dataclass
class Metadata:
    """Typed placeholder for metadata records as the app grows."""

    version: int = 1
    event_name: str = ""
    date: str = ""
    school_year: str = ""
    grades: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    description: str = ""
    photo_count: int = 0
    video_count: int = 0
    unedited_jpg_count: int = 0
    created: str = ""
    last_modified: str = ""

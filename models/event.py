from dataclasses import dataclass, field


@dataclass
class Event:
    """Represents a media event managed by the application."""

    name: str = ""
    description: str = ""
    grades: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

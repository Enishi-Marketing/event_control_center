"""Free-form event keyword vocabulary derived from event metadata."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Protocol


def clean_keyword(value: object) -> str:
    """Collapse formatting whitespace without changing the user's wording."""
    return " ".join(str(value or "").split())


def keyword_key(value: object) -> str:
    return clean_keyword(value).casefold()


class EventWithKeywords(Protocol):
    keywords: list[str]
    last_modified: str
    created: str
    date: str


@dataclass(frozen=True)
class KeywordEntry:
    normalized_value: str
    display_value: str
    usage_count: int
    last_used: str


class KeywordVocabulary:
    """A disposable index; event JSON remains the source of truth."""

    def __init__(self, entries: Iterable[KeywordEntry] = ()) -> None:
        self.entries = list(entries)
        self.by_key = {entry.normalized_value: entry for entry in self.entries}

    @classmethod
    def from_events(cls, events: Iterable[EventWithKeywords]) -> KeywordVocabulary:
        counts: Counter[str] = Counter()
        variants: dict[str, Counter[str]] = defaultdict(Counter)
        recent: dict[str, str] = {}
        for event in events:
            seen: set[str] = set()
            for raw in event.keywords:
                display = clean_keyword(raw)
                key = keyword_key(display)
                if not key or key in seen:
                    continue
                seen.add(key)
                counts[key] += 1
                variants[key][display] += 1
                timestamp = event.created or event.date or event.last_modified
                recent[key] = max(recent.get(key, ""), timestamp)

        entries = []
        for key, count in counts.items():
            display = sorted(
                variants[key],
                key=lambda value: (cls._display_quality(value), -variants[key][value], value),
            )[0]
            if display.islower() or (display.isupper() and len(display) > 5):
                display = display.title()
            entries.append(KeywordEntry(key, display, count, recent.get(key, "")))
        return cls(sorted(entries, key=lambda entry: entry.display_value.casefold()))

    @staticmethod
    def _display_quality(value: str) -> int:
        if value.islower():
            return 2
        if value.isupper() and len(value) > 1:
            return 1
        return 0

    def canonicalize(self, values: object) -> list[str]:
        raw_values = values if isinstance(values, (list, tuple, set)) else [values]
        unique: dict[str, str] = {}
        for raw in raw_values:
            for piece in str(raw or "").split(","):
                display = clean_keyword(piece)
                key = keyword_key(display)
                if key:
                    unique.setdefault(key, self.by_key[key].display_value if key in self.by_key else display)
        return sorted(unique.values(), key=str.casefold)

    def suggest(self, query: str, excluded: Iterable[str] = (), limit: int = 8) -> list[KeywordEntry]:
        needle = keyword_key(query)
        if not needle:
            return []
        excluded_keys = {keyword_key(value) for value in excluded}

        def match_rank(key: str) -> int:
            if key.startswith(needle):
                return 0
            if any(word.startswith(needle) for word in key.split()[1:]):
                return 1
            return 2

        matches = [
            entry for entry in self.entries
            if needle in entry.normalized_value and entry.normalized_value not in excluded_keys
        ]
        matches.sort(key=lambda entry: entry.display_value.casefold())
        matches.sort(key=lambda entry: entry.last_used, reverse=True)
        matches.sort(key=lambda entry: entry.usage_count, reverse=True)
        matches.sort(key=lambda entry: match_rank(entry.normalized_value))
        return matches[:limit]

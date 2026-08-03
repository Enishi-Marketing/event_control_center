import hashlib
from pathlib import Path


class HashService:
    """Generates and compares SHA-256 file hashes."""

    def sha256(self, file_path: Path) -> str:
        digest = hashlib.sha256()

        with file_path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    def verify(self, source: Path, destination: Path) -> bool:
        return self.sha256(source) == self.sha256(destination)

"""Raw archive: every fetched body is stored gzip-compressed and never deleted, so any
parser can be fixed and everything re-derived without refetching."""

import gzip
import hashlib
import os
import tempfile
from pathlib import Path


class RawArchive:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, kind: str, key: str, ext: str = "txt") -> Path:
        safe = key.replace("/", "_")
        shard = hashlib.sha1(safe.encode()).hexdigest()[:2]
        return self.root / kind / shard / f"{safe}.{ext}.gz"

    def put(self, kind: str, key: str, data: bytes, ext: str = "txt") -> Path:
        path = self.path_for(kind, key, ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(gzip.compress(data))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return path

    def get(self, kind: str, key: str, ext: str = "txt") -> bytes:
        return self.read_path(self.path_for(kind, key, ext))

    def exists(self, kind: str, key: str, ext: str = "txt") -> bool:
        return self.path_for(kind, key, ext).exists()

    def read_path(self, path: Path) -> bytes:
        return gzip.decompress(Path(path).read_bytes())

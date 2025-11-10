import hashlib
from typing import Optional


def compute_file_hash(path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

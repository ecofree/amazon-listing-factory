from __future__ import annotations

import re
from urllib.parse import urlparse


def same_amazon_image_exists(urls: list[str], candidate: str) -> bool:
    candidate_key = amazon_image_identity(candidate)
    if not candidate_key:
        return False
    return any(amazon_image_identity(url) == candidate_key for url in urls)


def amazon_image_identity(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.rsplit("/", 1)[-1]
    if not path:
        return ""
    stem = path.split(".", 1)[0]
    stem = re.sub(r"\._[^.]+_$", "", stem)
    stem = re.sub(r"\._[^.]+", "", stem)
    return stem.casefold()

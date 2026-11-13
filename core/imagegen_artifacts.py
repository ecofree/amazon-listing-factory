from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .api_registry import image_provider_physical_identity
from .image_provider_common import ImageGenerationError


IMAGEGEN_OUTPUT_CACHE_VERSION = "imagegen-output-v13-visible-native-integrity"
NATIVE_IMAGE_POLICY = "native-square-v2-visible-rgb-1024-4096"
IMAGE_OUTPUT_MAX_BYTES = 32 * 1024 * 1024
IMAGE_RESPONSE_MAX_BYTES = 48 * 1024 * 1024
IMAGE_OUTPUT_MAX_DIMENSION = 4096
IMAGE_OUTPUT_MAX_PIXELS = 4096 * 4096
NATIVE_IMAGE_MIN_DIMENSION = 1024


def _is_invalid_image_encoding(exc: OSError) -> bool:
    from PIL import UnidentifiedImageError
    message = str(exc)
    return isinstance(exc, UnidentifiedImageError) or (exc.errno is None and (
        message in ('Truncated File Read', 'truncated PNG file',
                    'buffer overrun when reading image file', 'broken data stream when reading image file',
                    'unrecognized data stream contents when reading image file')
        or message.startswith('image file is truncated')))


def assert_native_image(data: bytes) -> dict:
    """Validate paid native bytes before any conversion; failures never authorize another POST."""
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image
    from .image_provider_common import CandidateCommitError, ImageOutputRejected
    try:
        if not data or len(data) > IMAGE_OUTPUT_MAX_BYTES:
            raise ValueError('Native image is empty or exceeds the output byte limit')
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if (width != height or min(width, height) < NATIVE_IMAGE_MIN_DIMENSION
                    or max(width, height) > IMAGE_OUTPUT_MAX_DIMENSION
                    or width * height > IMAGE_OUTPUT_MAX_PIXELS):
                raise ValueError(f'Native canvas must be square, 1024..4096 pixels: {width}x{height}')
            image.verify()
        with Image.open(BytesIO(data)) as image:
            if ('A' in image.getbands() or 'transparency' in image.info) and image.convert('RGBA').getchannel('A').getextrema()[1] == 0:
                raise ValueError('Native canvas is entirely transparent')
            if all(low == high for low, high in _visible_rgb(image).getextrema()):
                raise ValueError('Native canvas is solid RGB color')
        return {'policy': NATIVE_IMAGE_POLICY, 'sha256': sha256(data).hexdigest(), 'size': [width, height]}
    except MemoryError as exc:
        raise CandidateCommitError('Native validation needs local memory recovery; paid bytes retained') from exc
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        if isinstance(exc, OSError) and not _is_invalid_image_encoding(exc):
            raise CandidateCommitError('Native validation needs local system recovery; paid bytes retained') from exc
        raise ImageOutputRejected(f'Native image rejected; paid bytes retained, no automatic resend: {exc}') from exc
    except Exception as exc:
        raise CandidateCommitError(f'Native validation needs local recovery; paid bytes retained: {type(exc).__name__}: {exc}') from exc


def _visible_rgb(image):
    from PIL import Image
    if 'A' in image.getbands() or 'transparency' in image.info:
        rgba = image.convert('RGBA')
        background = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert('RGB')
    return image.convert('RGB')


def normalize_native_image(data: bytes) -> bytes:
    """The commit authority calls this only after native integrity validation."""
    from io import BytesIO
    from PIL import Image
    with Image.open(BytesIO(data)) as image:
        if image.format == 'PNG' and image.mode == 'RGB' and 'transparency' not in image.info:
            return data
        image = _visible_rgb(image)
        output = BytesIO(); image.save(output, format='PNG', optimize=True)
        return output.getvalue()


class ImageArtifactContractError(RuntimeError):
    pass


def imagegen_output_marker(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".source.json")


def staged_imagegen_output(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".pending")


def publish_staged_imagegen_output(staging_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise ImageArtifactContractError(f"Immutable image artifact already exists: {output_path}")
    if not staging_path.is_file():
        raise ImageArtifactContractError(f"Staged image artifact is missing: {staging_path}")
    os.replace(staging_path, output_path)


def provider_model(provider: str) -> str:
    identity = image_provider_physical_identity(provider)
    return str(identity.get("model") or identity.get("builtin") or "")


def replace_output(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ImageArtifactContractError(f"Immutable image artifact already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=f".tmp{path.suffix}", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.link(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def assert_image_output(path: Path) -> None:
    if not path.is_file() or not 0 < path.stat().st_size <= IMAGE_OUTPUT_MAX_BYTES:
        raise ImageGenerationError(f"Generated image is empty: {path}")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            if max(width, height) > IMAGE_OUTPUT_MAX_DIMENSION or width * height > IMAGE_OUTPUT_MAX_PIXELS:
                raise ImageGenerationError(f'Generated image exceeds pixel limit: {path}')
            extrema = _visible_rgb(image).getextrema()
        if min(width, height) < 1000:
            raise ImageGenerationError(f"Generated image is too small: {path}: {width}x{height}")
        if width != height:
            raise ImageGenerationError(f"Generated image must be square: {path}: {width}x{height}")
        if all(low == high for low, high in extrema):
            raise ImageGenerationError(f"Generated image is solid color: {path}")
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(f"Generated image is unreadable: {path}: {exc}") from exc

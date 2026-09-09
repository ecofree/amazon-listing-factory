from __future__ import annotations

import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


PUBLIC_IMAGE_SIZE = 1600
UPSCALE_BACKEND = "pillow-lanczos-v1"
REALESRGAN_MODEL = "realesrgan-x4plus"
_DEFAULT_REALESRGAN_EXE = Path(__file__).resolve().parents[1] / "tools" / "realesrgan" / "realesrgan-ncnn-vulkan.exe"


class ImageUpscaleError(RuntimeError):
    pass


def _realesrgan_executable() -> Path:
    return Path(os.environ.get("AMAZON_FACTORY_REALESRGAN_EXE") or _DEFAULT_REALESRGAN_EXE)


def _realesrgan_model_dir(executable: Path) -> Path:
    return Path(os.environ.get("AMAZON_FACTORY_REALESRGAN_MODEL_DIR") or (executable.parent / "models"))


def _configured_backend() -> str:
    return str(os.environ.get("AMAZON_FACTORY_UPSCALE_BACKEND") or "auto").strip().casefold()


def _resize_lanczos(source: Image.Image, target: int) -> bytes:
    mode = "RGBA" if source.mode == "RGBA" else "RGB"
    image = source.convert(mode)
    if image.size != (target, target):
        image = image.resize((target, target), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _realesrgan_resize(data: bytes, target: int) -> bytes:
    executable = _realesrgan_executable()
    if not executable.is_file():
        raise ImageUpscaleError(f"Real-ESRGAN executable is unavailable: {executable}")
    with tempfile.TemporaryDirectory(prefix="amazon_factory_upscale_") as tmp:
        root = Path(tmp)
        source_path = root / "source.png"
        enhanced_path = root / "enhanced.png"
        source_path.write_bytes(data)
        command = [
            str(executable),
            "-i", str(source_path),
            "-o", str(enhanced_path),
            "-m", str(_realesrgan_model_dir(executable)),
            "-n", REALESRGAN_MODEL,
            "-s", "4",
            "-f", "png",
            "-g", "auto",
        ]
        try:
            subprocess.run(
                command,
                cwd=str(executable.parent),
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
        except Exception as exc:
            raise ImageUpscaleError(f"Real-ESRGAN failed: {type(exc).__name__}") from exc
        try:
            with Image.open(enhanced_path) as enhanced:
                enhanced.load()
                return _resize_lanczos(enhanced, target)
        except Exception as exc:
            raise ImageUpscaleError("Real-ESRGAN output is unreadable") from exc


def upscale_for_publication_with_backend(
    data: bytes,
    *,
    target_size: int = PUBLIC_IMAGE_SIZE,
) -> tuple[bytes, str]:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImageUpscaleError("image bytes are empty")
    try:
        target = max(PUBLIC_IMAGE_SIZE, int(target_size or PUBLIC_IMAGE_SIZE))
        with Image.open(BytesIO(data)) as source:
            width, height = int(source.width), int(source.height)
            if width != height:
                raise ImageUpscaleError(f"generated image must be square before sizing: {width}x{height}")
            if (width, height) == (target, target) and source.format == "PNG" and source.mode == "RGB":
                return bytes(data), UPSCALE_BACKEND
            source.load()
            backend = _configured_backend()
            if backend in {"auto", "realesrgan", "real-esrgan"} and _realesrgan_executable().is_file():
                try:
                    return _realesrgan_resize(bytes(data), target), REALESRGAN_MODEL
                except ImageUpscaleError as exc:
                    fallback = f"{UPSCALE_BACKEND}:fallback_from_realesrgan:{type(exc).__name__}"
                    return _resize_lanczos(source, target), fallback
            return _resize_lanczos(source, target), UPSCALE_BACKEND
    except ImageUpscaleError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageUpscaleError(f"generated image cannot be prepared for publication: {type(exc).__name__}") from exc


def upscale_for_publication(data: bytes, *, target_size: int = PUBLIC_IMAGE_SIZE) -> bytes:
    return upscale_for_publication_with_backend(data, target_size=target_size)[0]


def publication_dimensions(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception as exc:
        raise ImageUpscaleError(f"publication image dimensions are unreadable: {type(exc).__name__}") from exc

"""Pixel-reconstruction enlargement; Lanczos requires confirmed artifact recovery."""
from __future__ import annotations

import os
import hashlib
import re
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError, __version__ as PILLOW_VERSION
from .image_provider_common import provider_concurrency_slot
from .io import file_sha256

PUBLIC_IMAGE_SIZE = 1600
UPSCALE_BACKEND = 'pillow-lanczos-v1'  # Identity of the deterministic branch, not the default enlargement policy.
MODEL_BACKEND = 'realesrnet-x4plus'
POSTPROCESS_POLICY = 'publication-processing-v1'
_DEFAULT_EXE = Path(__file__).resolve().parents[1] / 'tools/realesrgan/realesrgan-ncnn-vulkan.exe'


class ImageUpscaleError(RuntimeError):
    partial_output: bytes | None = None


def _resize_lanczos(source: Image.Image, target: int) -> bytes:
    image = source.convert('RGBA' if source.mode == 'RGBA' else 'RGB')
    if image.size != (target, target):
        image = image.resize((target, target), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()


def _integer_setting(key: str, default: str, minimum: int, maximum: int) -> int:
    raw = os.environ.get(key, default).strip()
    if not raw.isdecimal() or not minimum <= int(raw) <= maximum:
        raise ImageUpscaleError(f'{key} must be explicitly valid in {minimum}..{maximum}')
    return int(raw)


def _realesrgan_settings() -> dict:
    backend = (os.environ.get('AMAZON_FACTORY_UPSCALE_BACKEND') or 'auto').strip().casefold()
    if backend not in {'auto', 'realesrgan', 'real-esrgan'}:
        raise ImageUpscaleError('Global Lanczos upscaling is disabled; confirm an artifact on an exact candidate for local recovery')
    gpu = _integer_setting('AMAZON_FACTORY_REALESRGAN_GPU_ID', '', 0, 31)
    name = os.environ.get('AMAZON_FACTORY_REALESRGAN_GPU_NAME', '').strip()
    if not name:
        raise ImageUpscaleError('AMAZON_FACTORY_REALESRGAN_GPU_NAME must bind the configured NCNN GPU index')
    tile = _integer_setting('AMAZON_FACTORY_REALESRGAN_TILE_SIZE', '256', 32, 512)
    if tile % 32:
        raise ImageUpscaleError('RealESRGAN tile size must be a multiple of 32; automatic tiles are not used')
    timeout = _integer_setting('AMAZON_FACTORY_REALESRGAN_TIMEOUT_SECONDS', '120', 10, 300)
    exe = Path(os.environ.get('AMAZON_FACTORY_REALESRGAN_EXE') or _DEFAULT_EXE).resolve()
    models = Path(os.environ.get('AMAZON_FACTORY_REALESRGAN_MODEL_DIR') or exe.parent / 'models').resolve()
    for path in (exe, models / f'{MODEL_BACKEND}.bin', models / f'{MODEL_BACKEND}.param'):
        if not path.is_file():
            raise ImageUpscaleError(f'RealESRGAN executable/model is unavailable: {path}')
    return {'exe': exe, 'models': models, 'gpu': gpu, 'gpu_name': name, 'tile': tile, 'timeout': timeout}


def _realesrgan_resize(data: bytes, target: int, *, deadline: float | None = None) -> tuple[bytes, dict]:
    settings = _realesrgan_settings()
    deadline = min(time.monotonic() + settings['timeout'], deadline if deadline is not None else float('inf'))
    with Image.open(BytesIO(data)) as source:
        expected = (source.width * 4, source.height * 4)
    with tempfile.TemporaryDirectory(prefix='amazon_factory_upscale_') as tmp:
        root = Path(tmp)
        source_path, enhanced_path = root / 'source.png', root / 'enhanced.png'
        source_path.write_bytes(data)
        command = [str(settings['exe']), '-i', str(source_path), '-o', str(enhanced_path),
                   '-m', str(settings['models']), '-n', MODEL_BACKEND, '-s', '4', '-f', 'png',
                   '-g', str(settings['gpu']), '-t', str(settings['tile']), '-j', '1:1:1']
        try:
            # Same exclusive resource as SAM. The legacy lock name does NOT select a GPU.
            with provider_concurrency_slot('host_gpu_auto', deadline=deadline):
                assets = {kind: {'path': str(path), 'sha256': file_sha256(path)} for kind, path in {
                    'exe': settings['exe'], 'bin': settings['models'] / f'{MODEL_BACKEND}.bin',
                    'param': settings['models'] / f'{MODEL_BACKEND}.param'}.items()}
                started = time.monotonic()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ImageUpscaleError('Local finalization deadline exhausted before upscale')
                result = subprocess.run(command, cwd=str(settings['exe'].parent), check=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=remaining)
                elapsed = round(time.monotonic() - started, 6)
                if any(not Path(row['path']).is_file() or file_sha256(row['path']) != row['sha256'] for row in assets.values()):
                    error = ImageUpscaleError('RealESRGAN assets changed during execution; native retained, no regeneration')
                    error.partial_output = enhanced_path.read_bytes() if enhanced_path.is_file() else None
                    raise error
        except subprocess.TimeoutExpired as exc:
            raise ImageUpscaleError(f'RealESRGAN GPU {settings["gpu"]} timeout after {settings["timeout"]}s; native bytes retained, no Lanczos fallback') from exc
        except subprocess.CalledProcessError as exc:
            log = (exc.stdout or b'').decode('utf-8', errors='replace')
            raise ImageUpscaleError(f'RealESRGAN GPU {settings["gpu"]} exit={exc.returncode}: {log[-500:]}') from exc
        except OSError as exc:
            raise ImageUpscaleError(f'RealESRGAN GPU {settings["gpu"]} launch failed: {exc}') from exc
        log = (result.stdout or b'').decode('utf-8', errors='replace')
        devices = dict(re.findall(r'^\[(\d+) ([^\]]+)\]\s+queueC=', log, re.MULTILINE))
        actual = devices.get(str(settings['gpu']), '')
        if actual.casefold() != settings['gpu_name'].casefold():
            raise ImageUpscaleError(f'RealESRGAN GPU mapping mismatch: index={settings["gpu"]}, expected={settings["gpu_name"]}, observed={actual or "missing"}')
        try:
            with Image.open(enhanced_path) as enhanced:
                if enhanced.format != 'PNG' or enhanced.size != expected:
                    raise ImageUpscaleError(f'RealESRGAN output is not the expected 4x PNG: {enhanced.size}, expected={expected}')
                enhanced.load()
                output = _resize_lanczos(enhanced, target)
                return output, {'model': MODEL_BACKEND, 'assets': assets,
                    'gpu_id': settings['gpu'], 'gpu_name': actual, 'tile': settings['tile'],
                    'threads': '1:1:1', 'scale': 4, 'timeout_seconds': settings['timeout'],
                    'output_format': 'png', 'enhanced_size': list(expected), 'execution_seconds': elapsed}
        except ImageUpscaleError:
            raise
        except (OSError, ValueError) as exc:
            raise ImageUpscaleError('RealESRGAN output is unreadable; no interpolation fallback') from exc


def upscale_for_publication(
    data: bytes, *, target_size: int = PUBLIC_IMAGE_SIZE, artifact_confirmation: dict | None = None, deadline: float | None = None,
) -> tuple[bytes, dict]:
    if artifact_confirmation is not None and (
        not isinstance(artifact_confirmation, dict)
        or not re.fullmatch('[0-9a-f]{64}', str(artifact_confirmation.get('parent_candidate_sha256', '')))
        or not str(artifact_confirmation.get('reason', '')).strip()
    ):
        raise ImageUpscaleError('Artifact recovery requires an exact candidate SHA and confirmation reason')
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImageUpscaleError('image bytes are empty')
    try:
        target = max(PUBLIC_IMAGE_SIZE, int(target_size or PUBLIC_IMAGE_SIZE))
        started = time.monotonic()
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if width != height:
                raise ImageUpscaleError(f'generated image must be square before sizing: {width}x{height}')
            source.load()
            model = None
            if artifact_confirmation is not None:
                output, branch = _resize_lanczos(source, target), 'explicit_artifact_recovery'
            elif source.size == (target, target) and source.format == 'PNG' and source.mode == 'RGB':
                output, branch = bytes(data), 'passthrough'
            elif width < target:
                output, model = _realesrgan_resize(bytes(data), target, deadline=deadline)
                branch = 'model_enlargement'
            else:
                output, branch = _resize_lanczos(source, target), 'downsample' if width > target else 'format_conversion'
            provenance = {'policy': POSTPROCESS_POLICY, 'branch': branch,
                'backend': MODEL_BACKEND if model else UPSCALE_BACKEND,
                'input_sha256': hashlib.sha256(data).hexdigest(), 'output_sha256': hashlib.sha256(output).hexdigest(),
                'input_size': [width, height], 'output_size': [target, target],
                'pillow_version': PILLOW_VERSION, 'algorithm': 'unchanged' if branch == 'passthrough' else 'LANCZOS',
                'duration_seconds': round(time.monotonic() - started, 6)}
            if model is not None: provenance['model_execution'] = model
            if artifact_confirmation is not None:
                provenance['artifact_confirmation'] = {key: artifact_confirmation[key] for key in ('parent_candidate_sha256', 'reason')}
            return output, provenance
    except ImageUpscaleError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageUpscaleError(f'generated image cannot be prepared for publication: {type(exc).__name__}') from exc


def publication_dimensions(data: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(data)) as image:
            return image.size
    except Exception as exc:
        raise ImageUpscaleError('publication image dimensions are unreadable: ' + type(exc).__name__) from exc

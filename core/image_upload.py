"""Storage-independent upload copies; approved originals remain immutable."""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

from PIL import Image, ImageCms, __version__ as pillow_version

from .io import file_sha256, read_json, write_json

UPLOAD_ENCODING = 'jpeg-q95-444-v1'


def prepare_upload_copy(job_path: Path, source: Path, source_sha: str) -> dict[str, str]:
    if file_sha256(source) != source_sha:
        raise ValueError('Approved original changed before upload encoding')
    encoder = f'pillow-{pillow_version}'
    folder = job_path / 'images' / 'upload_copies' / source_sha
    target = folder / f'{source.stem}_{UPLOAD_ENCODING}.jpg'
    receipt = target.with_suffix('.json')
    if receipt.exists() and target.exists():
        saved = read_json(receipt)
        if (saved.get('source_sha256') == source_sha and saved.get('upload_encoding') == UPLOAD_ENCODING
                and saved.get('upload_encoder') == encoder and saved.get('upload_path') == str(target)
                and saved.get('upload_sha256') == file_sha256(target)):
            return {k: v for k, v in saved.items() if k != 'source_sha256'}
    with Image.open(source) as opened:
        opened.load()
        # Transparency is a format requirement, not a failed JPEG fallback.
        if ('A' in opened.getbands() and opened.getchannel('A').getextrema() != (255, 255)
                or 'transparency' in opened.info):
            return {}
        profile = opened.info.get('icc_profile')
        image = opened.convert('RGB')
        if profile:
            srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
            image = ImageCms.profileToProfile(image, ImageCms.ImageCmsProfile(BytesIO(profile)), srgb, outputMode='RGB')
            profile = srgb.tobytes()
        folder.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f'.{os.getpid()}.tmp')
        try:
            image.save(tmp, format='JPEG', quality=95, subsampling=0, optimize=True,
                       progressive=False, **({'icc_profile': profile} if profile else {}))
            with Image.open(tmp) as check:
                check.load()
                if check.size != opened.size or check.format != 'JPEG':
                    raise ValueError('Upload copy dimensions or format changed')
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    result = {'upload_path': str(target), 'upload_sha256': file_sha256(target),
              'upload_encoding': UPLOAD_ENCODING, 'upload_encoder': encoder,
              'upload_bytes': str(target.stat().st_size), 'upload_mime': 'image/jpeg'}
    write_json(receipt, {**result, 'source_sha256': source_sha})
    return result

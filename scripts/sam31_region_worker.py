"""Local SAM inference subprocess. No job state, semantic decisions or network calls."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    channel = sys.stdout
    def send(value):
        channel.write('__SAM31__' + json.dumps(value, ensure_ascii=True) + '\n');channel.flush()
    def _stage(name,**details):
        send({'event':'stage','stage':name,'pid':os.getpid(),'parent_pid':os.getppid(),'monotonic':time.monotonic(),**details})
    _stage('python_start')
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    log = Path(config['log']).open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    _stage('imports_start')
    os.environ['HF_HUB_OFFLINE'] = os.environ['TRANSFORMERS_OFFLINE'] = '1'
    sys.path.insert(0, config['comfy_root'])
    import comfy.options
    comfy.options.enable_args_parsing()
    sys.argv = [sys.argv[0], '--disable-dynamic-vram', '--use-pytorch-cross-attention',
                '--force-fp16', '--disable-pinned-memory']
    import numpy as np
    from PIL import Image
    import torch
    from torch.nn import functional as F
    import comfy.sd
    import comfy.utils
    import comfy.model_management as mm
    from comfy_extras.nodes_sam3 import _extract_text_prompts

    _stage('imports_complete')
    torch.set_num_threads(4)
    model = None
    cache = OrderedDict()
    counts = dict(image_encodings=0, semantic_forwards=0, interactive_forwards=0,
                  crop_cache_hits=0, crop_cache_misses=0, cache_evictions=0, encoder_cache_hits=0)
    try:
        with torch.inference_mode():
            _stage('weights_load_start')
            model, clip, _, _ = comfy.sd.load_checkpoint_guess_config(config['weights'], output_vae=False)
            _stage('weights_loaded')
            _stage('gpu_transfer_start')
            mm.load_model_gpu(model)
            _stage('gpu_transfer_complete')
            sam = model.model.diffusion_model
            device, dtype = mm.get_torch_device(), model.model.get_dtype()
            encoder = sam.tracker.interactive_sam_prompt_encoder
            decoder = sam.tracker.interactive_sam_mask_decoder
            # Match the already tested Comfy tracker epsilon; no quantization rewrite.
            encoder.mask_downscaling[1].eps = encoder.mask_downscaling[4].eps = decoder.output_upscaling[1].eps = 1e-6
            _stage('ready')
            send({'ready': True})
            for line in sys.stdin:
                request = json.loads(line)
                if request.get('close'):
                    break
                _stage('inference_start',request_id=request.get('id'))
                start = time.monotonic()
                diagnostics = []
                try:
                    path, directory = Path(request['source']), Path(request['output'])
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    if digest != request['source_sha256']:
                        raise ValueError('SAM source SHA changed')
                    with Image.open(path) as image:
                        original = image.convert('RGB')
                    width, height = original.size
                    directory.mkdir(parents=True, exist_ok=True)
                    rows = []
                    for unit in request['units']:
                        unit_start, encoded_before = time.monotonic(), counts['image_encodings']
                        metric = dict(unit_id=unit['id'], method=unit['method'], presence_probability=None,
                            highest_score=None, candidates_before_filter=None,
                            candidates_after_score=None, candidates_returned=0)
                        box = unit['crop']
                        bounds = (int(box['left'] * width), int(box['top'] * height),
                                  max(1, int(box['right'] * width)), max(1, int(box['bottom'] * height)))
                        left, top, right, bottom = bounds
                        cw, ch = right - left, bottom - top
                        if cw < 1 or ch < 1:
                            raise ValueError('Empty SAM crop')
                        key = (digest, bounds)
                        metric['crop_cache_hit'] = key in cache
                        counts['crop_cache_hits' if key in cache else 'crop_cache_misses'] += 1
                        if key not in cache:
                            arr = np.asarray(original.crop(bounds))
                            x = torch.from_numpy(arr.astype('float32') / 127.5 - 1)[None].movedim(-1, 1)
                            x = comfy.utils.common_upscale(x, 1008, 1008, 'bilinear', crop='disabled').to(device=device, dtype=dtype)
                            cache[key] = {'image': x}
                            while len(cache) > 2:
                                cache.popitem(last=False)
                                counts['cache_evictions'] += 1
                        entry = cache[key]
                        cache.move_to_end(key)
                        if unit['method'] == 'semantic':
                            metric['encoder_cache_hit'] = 'semantic' in entry
                            if 'semantic' not in entry:
                                entry['semantic'] = sam.detector._get_backbone_features(entry['image'])[:2]
                                counts['image_encodings'] += 1
                            conditions = clip.encode_from_tokens_scheduled(clip.tokenize(unit['query']))
                            emb, attention, _ = _extract_text_prompts(conditions, device, dtype)[0]
                            emb = sam.detector.backbone['language_backbone']['resizer'](emb)
                            features, positions = entry['semantic']
                            _, scores, masks, detection = sam.detector._detect(features, positions, emb, attention.bool())
                            counts['semantic_forwards'] += 1
                            presence = detection.get('presence')
                            metric['presence_probability'] = None if presence is None else float(presence.sigmoid().max())
                            probs = scores[0].sigmoid()
                            metric.update(highest_score=float(probs.max()) if probs.numel() else None,
                                candidates_before_filter=int(probs.numel()),
                                candidates_after_score=int((probs > .45).sum()))
                            selected = (probs > .45).nonzero().flatten()
                            selected = sorted(selected, key=lambda i: float(probs[i]), reverse=True)[:10]
                            predictions = [(masks[:, i:i+1], float(probs[i])) for i in selected]
                        else:
                            metric['encoder_cache_hit'] = 'interactive' in entry
                            if 'interactive' not in entry:
                                _, _, feats, _ = sam.detector.backbone['vision_backbone'](
                                    entry['image'], tracker_mode='interactive', tracker_only=True)
                                entry['interactive'] = feats
                                counts['image_encodings'] += 1
                            feats = entry['interactive']
                            low = feats[-1] + sam.tracker.interactivity_no_mem_embed.to(feats[-1]).reshape(1, 256, 1, 1)
                            positive = unit['positive_points']
                            # Outside-crop negatives are already excluded by the spatial support.
                            negative = [p for p in unit['negative_points'] if left <= p['x']*width < right and top <= p['y']*height < bottom]
                            xy = positive + negative
                            points = dict(point_coords=torch.tensor([[[(p['x'] * width-left)/cw*1008,
                                (p['y']*height-top)/ch*1008] for p in xy]], device=device, dtype=dtype),
                                point_labels=torch.tensor([[1]*len(positive)+[0]*len(negative)], device=device, dtype=torch.int32))
                            if entry.get('prior_request') != request['id']:
                                entry['priors'], entry['prior_request'] = {}, request['id']
                            prior_key = (unit['parent_id'], unit['part_id'], unit['operation'], unit['id'])
                            prior = entry.get('priors', {}).get(prior_key)
                            logits, high, _, _ = sam.tracker._forward_sam_heads(low, point_inputs=points,
                                mask_inputs=prior, high_res_features=feats[:-1], multimask_output=False)
                            entry.setdefault('priors', {})[prior_key] = logits.detach().clone().clamp(-32, 32)
                            counts['interactive_forwards'] += 1
                            predictions = [(high, None)]
                        counts['encoder_cache_hits'] += int(metric['encoder_cache_hit'])
                        metric['candidates_returned'] = len(predictions)
                        for index, (logits, score) in enumerate(predictions):
                            mask = F.interpolate(logits.float(), size=(ch, cw), mode='bilinear', align_corners=False)[0, 0].cpu().numpy() > 0
                            result = np.zeros((height, width), dtype=np.uint8)
                            result[top:bottom, left:right] = mask.astype('uint8') * 255
                            output = directory / (unit['id'] + '_' + str(index) + '.png')
                            Image.fromarray(result).save(output)
                            rows.append(dict(unit_id=unit['id'], parent_id=unit['parent_id'], part_id=unit['part_id'],
                                path=str(output), sha256=hashlib.sha256(output.read_bytes()).hexdigest(), score=score,
                                crop=box, method=unit['method'], pixels=int(mask.sum())))
                        metric.update(seconds=round(time.monotonic()-unit_start, 3),
                                      image_encodings=counts['image_encodings']-encoded_before)
                        diagnostics.append(metric)
                    _stage('inference_complete',request_id=request['id'])
                    send({'id': request['id'], 'source_sha256': request['source_sha256'], 'rows': rows,
                          'unit_diagnostics': diagnostics, 'counts': dict(counts), 'seconds': round(time.monotonic()-start, 3)})
                except Exception as exc:
                    import traceback
                    traceback.print_exc(file=log)
                    send({'id': request['id'], 'source_sha256': request['source_sha256'],
                          'error': f'{type(exc).__name__}: {exc}', 'unit_diagnostics': diagnostics,
                          'counts': dict(counts), 'seconds': round(time.monotonic()-start, 3)})
    finally:
        cache.clear()
        if model is not None:
            mm.unload_all_models()
        log.close()


if __name__ == '__main__':
    main()

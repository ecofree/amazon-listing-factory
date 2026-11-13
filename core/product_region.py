"""SAM tools inside the existing planner. Geometry is evidence, never a semantic judge."""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

from .io import file_sha256, load_env, read_json, write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .image_provider_common import ProviderQueueUnavailable
from .sam_diagnostics import geometry_revision,worker_status,terminate_tree

POLICY = 'sam31-owned-region-v9-planner-tool'
ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = {'SAM31_PYTHON', 'SAM31_COMFY_ROOT', 'SAM31_WEIGHTS', 'SAM31_WEIGHTS_SHA256'}
BACKEND_FILES = ('comfy/ldm/sam3/detector.py', 'comfy/ldm/sam3/sam.py', 'comfy/ldm/sam3/tracker.py',
    'comfy_extras/nodes_sam3.py', 'comfy/ops.py', 'comfy/quant_ops.py', 'comfy/sd.py',
    'comfy/model_base.py', 'comfy/model_detection.py', 'comfy/utils.py', 'comfy/model_management.py')


class RegionToolError(ValueError):
    def __init__(self, message, *, issue_code='invalid_tool_operation', correction_started=False):
        super().__init__(message)
        self.issue_code, self.correction_started = issue_code, correction_started


def region_runtime_binding():
    load_env(ROOT / 'config.local.env', only_keys=CONFIG_KEYS)
    comfy = Path(os.environ.get('SAM31_COMFY_ROOT', ''))
    files = {name: file_sha256(comfy/name) if (comfy/name).is_file() else None for name in BACKEND_FILES}
    python = Path(os.environ.get('SAM31_PYTHON', ''))
    runtime = python.parent.parent if python.parent.name.casefold() == 'scripts' else python.parent
    metadata = runtime / 'Lib/site-packages'
    packages = {p.parent.name: file_sha256(p) for package in ('torch', 'numpy', 'safetensors', 'pillow')
                for p in metadata.glob(package+'-*.dist-info/METADATA')} if python.is_file() else {}
    return {'weights_sha256': os.environ.get('SAM31_WEIGHTS_SHA256', ''), 'comfy_files': files,
        'geometry_revision': geometry_revision(Path(__file__),ROOT/'scripts/sam31_region_worker.py'),
        'python_sha256': file_sha256(python) if python.is_file() else None,
        'packages': packages, 'policy': POLICY}


def _text(value: Any, maximum=240, *, field='region_intent'):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{field}: expected bounded nonempty text')
    return value


def _geometry(unit: dict, *, field='region', require_anchor=True):
    from .image_reference_context import source_box, source_point
    bounds = source_box(unit.get('crop'))
    for kind in ('positive_points', 'negative_points'):
        points = unit.get(kind)
        if not isinstance(points, list) or len(points) > 24 or (kind == 'positive_points' and require_anchor and not points):
            raise ValueError(f'{field}.{kind}: expected bounded anchors')
        for point in points:
            x, y = source_point(point)
            if kind == 'positive_points' and not (bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]):
                raise ValueError(f'{field}.{kind}: anchor outside declared crop')


def validate_region_intent(intent: Any, source: dict):
    from .planning_contract import region_schema
    if not isinstance(intent, dict) or set(intent) != set(region_schema([source])['properties']):
        raise ValueError('region_intent needs current named fields')
    _text(intent['reason'], 500)
    if not isinstance(intent['mode'], str) or intent['mode'] not in {'protect_visible', 'not_applicable'}:
        raise ValueError('Unknown region eligibility')
    for key in ('editable_objects', 'special_surfaces'):
        if not isinstance(intent[key], list) or len(intent[key]) > 16:
            raise ValueError(f'{key}: expected at most 16 strings')
        for item in intent[key]:
            _text(item)
    targets = intent['targets']
    if not isinstance(targets, list) or len(targets) > 4:
        raise ValueError('Region needs bounded target instances')
    if not targets and intent['mode'] == 'protect_visible':
        raise ValueError('Protection requested without a target')
    objects = {o['object_id'] for o in source['observation'].get('objects', []) if o['sale_membership'] in {'product', 'included_accessory'}}
    objects.update(f['object_id'] for f in source['observation']['product_features'])
    seen = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {'object_id', 'query', 'crop', 'positive_points', 'negative_points', 'parts'}:
            raise ValueError('Region target fields are invalid')
        if not isinstance(target['object_id'], str) or target['object_id'] not in objects or target['object_id'] in seen:
            raise ValueError('Region target needs a unique observed owner')
        seen.add(target['object_id']); _text(target['query']); _geometry(target, require_anchor=intent['mode']=='protect_visible')
        if not isinstance(target['parts'], list) or len(target['parts']) > 8:
            raise ValueError('Invalid component list')
        parts = set()
        for part in target['parts']:
            if not isinstance(part, dict) or set(part) != {'part_id', 'query', 'crop', 'positive_points', 'negative_points'}:
                raise ValueError('Region part fields are invalid')
            _text(part['part_id']); _text(part['query']); _geometry(part, require_anchor=intent['mode']=='protect_visible')
            if part['part_id'] in parts or part['part_id'] == '__whole__':
                raise ValueError('Repeated or reserved component identity')
            parts.add(part['part_id'])
    if sum(1+len(t['parts']) for t in targets) > 16:
        raise ValueError('Region component budget exceeded')


def validate_region_reference(value: Any):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256', 'input_key', 'content_key'}
            or not isinstance(value['path'], str) or not value['path']
            or any(not isinstance(value[k], str) or not re.fullmatch('[0-9a-f]{64}', value[k]) for k in ('sha256', 'input_key', 'content_key'))):
        raise ValueError('Region needs an immutable artifact reference')


def region_requested(brief: dict) -> bool:
    return isinstance(brief.get('region_intent'),dict) and brief['region_intent'].get('mode') == 'protect_visible'


def read_region(reference: dict, *, job: Path, child: str | None = None, base: dict | None = None):
    validate_region_reference(reference)
    path = resolve_job_owned_path(job, reference['path'])
    if not path.is_file() or file_sha256(path) != reference['sha256']:
        raise ValueError('Product region artifact changed or is missing')
    row = read_json(path)
    if row['policy'] != POLICY or any(row[k] != reference[k] for k in ('input_key', 'content_key')):
        raise ValueError('Product region content binding changed')
    if child is not None and row['child'] != child:
        raise ValueError('Region belongs to another child')
    if base is not None and any(row['base'][k] != base[k] for k in ('sha256', 'source_id')):
        raise ValueError('Region belongs to another edit base')
    for item in [row['mask'], *row['views'], *row['candidates']]:
        path = resolve_job_owned_path(job, item['path'])
        if not path.is_file() or file_sha256(path) != item['sha256']:
            raise ValueError('Region mask or tool evidence changed')
    if _region_content_key(row, job) != row['content_key']:
        raise ValueError('Region content binding changed')
    return row


def _mask(job: Path, row: dict):
    import numpy as np
    from PIL import Image
    with Image.open(resolve_job_owned_path(job, row['path'])) as image:
        return np.asarray(image.getchannel('A') if image.mode == 'RGBA' else image.convert('L')) > 127


def _owned_masks(row: dict, selection: dict, job: Path):
    import numpy as np
    width, height = row['base']['size']
    catalog = {c['candidate_id']: c for c in row['candidates']}
    owned = {t['object_id']: np.zeros((height, width), dtype=bool) for t in row['intent']['targets']}
    for owner, identities in selection.items():
        if owner not in owned or any(identity not in catalog or catalog[identity]['parent_id'] != owner for identity in identities):
            raise ValueError('Selected candidate belongs to another owner')
        for identity in identities:
            owned[owner] |= _mask(job, catalog[identity])
    return owned


def _region_content_key(row: dict, job: Path):
    from hashlib import sha256
    merged = _mask(job, row['mask'])
    owned = {owner: sha256((support & merged).tobytes()).hexdigest() for owner, support in _owned_masks(row, row['selection'], job).items()}
    return input_revision_id({k: row[k] for k in ('policy', 'child', 'base', 'input_key', 'intent')}
        | {'mask_sha256': row['mask']['sha256'], 'owned_support': owned})


def region_point_map(intent: dict):
    points = {}
    for i, target in enumerate(intent['targets']):
        root = f'region_intent.targets[{i}]'
        units = [(target, '__whole__', root)] + [(p, p['part_id'], f'{root}.parts[{j}]') for j, p in enumerate(target['parts'])]
        for unit, part, path in units:
            for polarity, field in [('positive', 'positive_points'), ('negative', 'negative_points')]:
                for j, point in enumerate(unit[field]):
                    identity = ('P' if polarity == 'positive' else 'N') + str(len(points)+1)
                    points[identity] = {'object_id': target['object_id'], 'part_id': part, 'query': unit['query'],
                        'polarity': polarity, **point, 'unit_path': path, 'target_path': f'{path}.{field}[{j}]'}
    return points


def region_tool_diagnostics(row: dict, job: Path):
    """Raw geometry, including negative conflicts. No inferred material or readiness."""
    merged = _mask(job, row['mask']); width, height = row['base']['size']
    points = region_point_map(row['intent'])
    masks = {c['candidate_id']: _mask(job, c) for c in row['candidates']}
    for point in points.values():
        x, y = min(width-1, int(point['x']*width)), min(height-1, int(point['y']*height))
        point.update(merged_hit=bool(merged[y, x]), candidate_hits=[c['candidate_id'] for c in row['candidates']
            if c['parent_id'] == point['object_id'] and c['part_id'] == point['part_id'] and masks[c['candidate_id']][y, x]])
    return {'protected_pixels': int(merged.sum()), 'points': points}


def validate_region_action(action: dict, row: dict):
    from .image_reference_context import source_box
    if not isinstance(action, dict) or not action or set(action)-{'select', 'deltas'}:
        raise RegionToolError('Region action only accepts select/deltas')
    owners = {t['object_id']: t for t in row['intent']['targets']}
    catalog = {c['candidate_id']: c for c in row['candidates']}
    selections, deltas = action.get('select', []), action.get('deltas', [])
    if not isinstance(selections, list) or not isinstance(deltas, list) or not (selections or deltas) or len(deltas) > 8:
        raise RegionToolError('Region action needs one bounded nonempty change')
    seen = set()
    for selection in selections:
        if (not isinstance(selection, dict) or set(selection) != {'object_id', 'candidate_ids'}
                or not isinstance(selection['object_id'], str) or selection['object_id'] not in owners or selection['object_id'] in seen):
            raise RegionToolError('Selection needs a unique owned instance')
        seen.add(selection['object_id']); ids = selection['candidate_ids']
        if (not isinstance(ids, list) or any(not isinstance(k, str) or k not in catalog for k in ids)
                or len(ids) != len(set(ids)) or any(catalog[k]['parent_id'] != selection['object_id'] for k in ids)):
            raise RegionToolError('Selection contains foreign or duplicate candidate IDs')
    for delta in deltas:
        if (not isinstance(delta, dict) or set(delta) != {'parent_id', 'part', 'operation', 'query', 'crop', 'positive_points', 'negative_points'}
                or not isinstance(delta['parent_id'], str) or delta['parent_id'] not in owners
                or not isinstance(delta['operation'], str) or delta['operation'] not in {'add_product', 'remove_nonproduct'}):
            raise RegionToolError('Delta needs an owned signed operation')
        target = owners[delta['parent_id']]
        parts = {'__whole__': target, **{p['part_id']: p for p in target['parts']}}
        if not isinstance(delta['part'], str) or delta['part'] not in parts:
            raise RegionToolError('Delta names an unknown owned part')
        _text(delta['query']); _geometry(delta)
        outer, inner = source_box(parts[delta['part']]['crop']), source_box(delta['crop'])
        if inner[0] < outer[0] or inner[1] < outer[1] or inner[2] > outer[2] or inner[3] > outer[3]:
            raise RegionToolError(f"Delta exceeds the declared window for {delta['parent_id']}/{delta['part']}: "
                                  f"allowed={parts[delta['part']]['crop']}, actual={delta['crop']}. "
                                  "Keep this correction inside that window, or use patch_plan to revise the source-backed region_intent first.")
        if delta['operation'] == 'remove_nonproduct' and not delta['negative_points']:
            raise RegionToolError('Deletion needs product counterexamples')


class ProductRegions:
    """One lazy local worker in the existing brief controller."""
    def __init__(self, job: Path, deadline: float):
        self.job, self.deadline = job, deadline
        self.lock = threading.RLock()
        self.stack, self.process, self.answers = ExitStack(), None, queue.Queue()
        self.backend, self.latest = None, {}
        self.last_stage='not_started';self.worker_pid=None

    def close(self, *, abort=False):
        process, self.process = self.process, None
        stack, self.stack = self.stack, ExitStack(); self.answers = queue.Queue()
        try:
            if process is None:
                return
            try:
                if process.poll() is None:
                    if abort:
                        terminate_tree(process)
                    else:
                        process.stdin.write('{"close":true}\n'); process.stdin.flush()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                terminate_tree(process)
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
        finally:
            stack.close()

    def _backend(self):
        if self.backend is not None:
            return self.backend
        load_env(ROOT / 'config.local.env', only_keys=CONFIG_KEYS)
        values = {k: os.environ.get(k, '') for k in CONFIG_KEYS}
        if not all(values.values()):
            raise ValueError('Local SAM31 paths and weight SHA are not configured')
        for key in ('SAM31_PYTHON', 'SAM31_WEIGHTS'):
            if not Path(values[key]).is_file():
                raise ValueError(f'{key} is not a local file')
        if file_sha256(Path(values['SAM31_WEIGHTS'])) != values['SAM31_WEIGHTS_SHA256']:
            raise ValueError('Configured SAM31 weight SHA does not match')
        if any(not (Path(values['SAM31_COMFY_ROOT'])/name).is_file() for name in BACKEND_FILES):
            raise ValueError('Configured Comfy SAM backend files are missing')
        self.config = values; self.backend = region_runtime_binding()
        return self.backend

    def _receive(self):
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Brief deadline exhausted during SAM preparation')
        try:
            return self.answers.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError('SAM worker exceeded the brief deadline; last_stage='+self.last_stage) from None

    def _start(self):
        if self.process is not None:
            if self.process.poll() is not None:
                self.close(abort=True); raise ValueError('Local SAM worker exited')
            return
        from .image_provider_common import provider_concurrency_slot
        self._backend()
        self.stack.enter_context(provider_concurrency_slot('host_gpu_auto', deadline=self.deadline))
        directory = self.job/'planning/product_regions'; directory.mkdir(parents=True, exist_ok=True)
        config = directory/'worker.json'
        write_json(config, {'comfy_root': self.config['SAM31_COMFY_ROOT'], 'weights': self.config['SAM31_WEIGHTS'], 'log': str(directory/'worker.log')})
        self.process = subprocess.Popen([self.config['SAM31_PYTHON'], '-u', str(ROOT/'scripts/sam31_region_worker.py'), '--config', str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        process, answers = self.process, self.answers
        self.last_stage='subprocess_spawn';worker_status(directory,self.last_stage,launcher_pid=process.pid)
        def receive():
            try:
                for line in process.stdout:
                    if line.startswith('__SAM31__'):
                        message=json.loads(line[len('__SAM31__'):])
                        if message.get('event')=='stage':
                            self.last_stage=message['stage'];self.worker_pid=message.get('pid')
                            worker_status(directory,self.last_stage,launcher_pid=process.pid,worker_pid=self.worker_pid,
                                worker_parent_pid=message.get('parent_pid'),request_id=message.get('request_id'))
                        else:answers.put(message)
                    else:
                        with (directory/'worker_stdout.log').open('a',encoding='utf-8') as output:output.write(line)
            except (OSError, ValueError):
                answers.put({'error': 'Invalid SAM worker response'})
            finally:
                answers.put({'error': 'SAM worker exited before completing request'})
        threading.Thread(target=receive, daemon=True).start()
        try:
            value = self._receive()
            if not isinstance(value, dict) or not value.get('ready'):
                raise ValueError(value.get('error', 'SAM initialization failed') if isinstance(value, dict) else 'SAM initialization failed')
        except (ValueError, OSError, TimeoutError):
            self.close(abort=True); raise

    def _infer(self, base, units, directory):
        origin, attempt = directory, 0
        while True:
            saved=directory/'request.json';received=directory/'response.json'
            if not received.is_file():break
            request=read_json(saved);response=read_json(received)
            if request['source_sha256']!=base['sha256'] or request['units']!=units:
                raise ValueError('Saved SAM response belongs to another operation')
            self._validate_response(request, response, units)
            if not response.get('error'):return response['rows']
            # Keep failed receipts and partial masks immutable; one new local attempt per invocation.
            attempt += 1;directory=origin/f'retry-{attempt}'
        try:
            self._start()
        except (ValueError, OSError, TimeoutError, ProviderQueueUnavailable):
            self.close(abort=True); raise
        request = {'source': str(resolve_job_owned_path(self.job, base['path'])), 'source_sha256': base['sha256'],
            'output': str(directory), 'units': units, 'request_nonce': uuid4().hex}
        request['id'] = input_revision_id(request); write_json(saved, request)
        worker_status(self.job/'planning/product_regions','request_submitted',launcher_pid=self.process.pid,
            request_id=request['id'],operation_path=directory.relative_to(self.job).as_posix())
        try:
            self.process.stdin.write(json.dumps(request, ensure_ascii=True)+'\n'); self.process.stdin.flush()
            response = self._receive()
        except (ValueError,OSError,TimeoutError):
            self.close(abort=True);raise
        self._validate_response(request, response, units)
        if not received.is_file():write_json(received, response)
        if response.get('error'):
            raise ValueError(response['error'])
        return response['rows']

    def _validate_response(self, request, response, units):
        try:
            if not isinstance(response, dict) or response.get('id') != request['id'] or response.get('source_sha256') != request['source_sha256']:
                raise ValueError('Unbound SAM response')
            diagnostics = response.get('unit_diagnostics'); expected = [u['id'] for u in units]
            fields = {'unit_id', 'method', 'presence_probability', 'highest_score', 'candidates_before_filter',
                'candidates_after_score', 'candidates_returned', 'seconds', 'image_encodings', 'crop_cache_hit', 'encoder_cache_hit'}
            if (not isinstance(diagnostics, list) or any(not isinstance(d, dict) or not fields <= d.keys() for d in diagnostics)
                    or [d['unit_id'] for d in diagnostics] != expected[:len(diagnostics)]
                    or not response.get('error') and (len(diagnostics) != len(expected) or not isinstance(response.get('rows'), list))):
                raise ValueError('SAM response omitted bound unit diagnostics')
        except (ValueError, OSError, TimeoutError):
            self.close(abort=True); raise

    def prepare(self, brief: dict, source: dict, *, child: str, allow_inference=True):
        from PIL import Image
        intent = brief.get('region_intent'); validate_region_intent(intent, source)
        if intent['mode'] == 'not_applicable':
            brief.pop('product_region', None); return
        path = resolve_job_owned_path(self.job, source['source_path'])
        if file_sha256(path) != source['source_sha256']:
            raise ValueError('Region edit-base source changed')
        with Image.open(path) as image:
            size = list(image.size)
        base = {'path': source['source_path'], 'sha256': source['source_sha256'], 'source_id': source['source_id'], 'size': size}
        geometry = {k:v for k,v in intent.items() if k != 'reason'}
        reference = brief.get('product_region')
        if reference:
            previous = read_region(reference, job=self.job, child=child)
            # A validated immutable output keeps its recorded runtime identity.
            # New launcher/model settings do not change these existing pixels.
            if (all(previous['base'][k] == base[k] for k in ('sha256','source_id','size'))
                    and {k:v for k,v in previous['intent'].items() if k != 'reason'} == geometry):
                return
        backend = self._backend()
        key = input_revision_id({'policy': POLICY, 'child': child, 'base': base, 'intent': geometry, 'backend': backend})
        if key in self.latest:
            reference = self.latest[key]; read_region(reference, job=self.job, child=child, base=base)
            brief['product_region'] = reference; return
        directory = self.job/'planning/product_regions'/child/key
        cache = directory/'initial.json'
        if cache.is_file():
            reference = read_json(cache); read_region(reference, job=self.job, child=child, base=base)
        else:
            if not allow_inference:
                raise ProviderQueueUnavailable('sam', 'Region saved work may be recovered, but new inference waits for planning allowance and related receipts')
            units = []
            for target in intent['targets']:
                for part in [{'part_id': '__whole__', **{k: target[k] for k in ('query', 'crop', 'positive_points', 'negative_points')}}, *target['parts']]:
                    unit = {**part, 'parent_id': target['object_id'], 'method': 'semantic'}
                    unit['id'] = input_revision_id(unit)[:20]; units.append(unit)
            candidates = self._candidates(self._infer(base, units, directory/'initial'), units, size)
            # One highest-scoring nonempty proposal per tool unit, not an approval.
            # P/N anchors are visible diagnostics; neither is a semantic veto.
            proposed = {}
            for candidate in candidates:
                if candidate['pixels'] and (candidate['unit_id'] not in proposed
                        or (candidate.get('score') or 0) > (proposed[candidate['unit_id']].get('score') or 0)):
                    proposed[candidate['unit_id']] = candidate
            selection = {t['object_id']: [c['candidate_id'] for c in proposed.values()
                if c['parent_id'] == t['object_id']] for t in intent['targets']}
            row = {'policy': POLICY, 'child': child, 'base': base, 'intent': deepcopy(intent), 'input_key': key,
                'backend': backend, 'candidates': candidates, 'selection': selection, 'repair_round': 0, 'delta': None}
            reference = self._export(row, directory); write_json(cache, reference)
        self.latest[key] = brief['product_region'] = reference

    def _candidates(self, rows, units, size):
        lookup = {u['id']: u for u in units}; result, seen = [], set()
        for raw in rows:
            if raw['unit_id'] not in lookup:
                raise ValueError('Unknown SAM unit')
            unit = lookup[raw['unit_id']]
            row = {**raw, 'path': Path(raw['path']).relative_to(self.job).as_posix()}
            pixels = _mask(self.job, row)
            if list(reversed(pixels.shape)) != size:
                raise ValueError('SAM returned incorrect original geometry')
            if file_sha256(resolve_job_owned_path(self.job, row['path'])) != row['sha256']:
                raise ValueError('SAM candidate bytes changed')
            hit = lambda p: bool(pixels[min(size[1]-1, int(p['y']*size[1])), min(size[0]-1, int(p['x']*size[0]))])
            identity = input_revision_id({'unit': unit, 'mask': row['sha256']})[:20]
            if identity in seen:
                continue
            seen.add(identity)
            result.append({**row, 'pixels': int(pixels.sum()), 'parent_id': unit['parent_id'], 'part_id': unit['part_id'], 'candidate_id': identity,
                'positive_points': unit['positive_points'], 'negative_points': unit['negative_points'],
                'positive_anchor_hits': sum(hit(p) for p in unit['positive_points']),
                'negative_anchor_hits': sum(hit(p) for p in unit['negative_points'])})
        return result

    def apply_action(self, brief: dict, action: dict, *, child: str):
        """Execute one planner operation durably; never approve its own result."""
        import numpy as np
        reference = brief['product_region']; row = read_region(reference, job=self.job, child=child)
        validate_region_action(action, row)
        directory = resolve_job_owned_path(self.job, reference['path']).parent.parent
        key = input_revision_id({'parent': reference, 'action': action})
        receipt = directory/('action-'+key+'.json')
        if receipt.is_file():
            result = read_json(receipt); read_region(result, job=self.job, child=child)
            brief['product_region'] = result
            return result['content_key'] != reference['content_key']
        if row['repair_round'] >= 1:
            raise RegionToolError('One modifying region operation already executed')
        before = _mask(self.job, row['mask'])
        selection = deepcopy(row['selection'])
        selection.update({r['object_id']: list(r['candidate_ids']) for r in action.get('select', [])})
        owned = _owned_masks(row, selection, self.job)
        current = np.zeros_like(before)
        for mask in owned.values():
            current |= mask
        if selection == row['selection']:
            current = before.copy()
        additions, deletions = np.zeros_like(before), np.zeros_like(before)
        deltas = action.get('deltas', [])
        if deltas:
            units = [{**r, 'part_id': r['part'], 'id': input_revision_id(r)[:20], 'method': 'interactive'} for r in deltas]
            candidates = self._candidates(self._infer(row['base'], units, directory/('delta-'+key)), units, row['base']['size'])
            if {c['unit_id'] for c in candidates} != {u['id'] for u in units}:
                raise RegionToolError('SAM did not return every delta', correction_started=True)
            for candidate in candidates:
                unit = next(u for u in units if u['id'] == candidate['unit_id'])
                delta = _mask(self.job, candidate)
                other = np.zeros_like(before)
                for owner, mask in owned.items():
                    if owner != candidate['parent_id']:
                        other |= mask
                if np.any(delta & other):
                    raise RegionToolError('Delta crosses another declared instance support', correction_started=True)
                if unit['operation'] == 'add_product':
                    additions |= delta; row['candidates'].append(candidate)
                    selection[candidate['parent_id']].append(candidate['candidate_id'])
                else:
                    deletions |= delta
        merged = (current | additions) & ~deletions
        if not merged.any():
            raise RegionToolError('Tool operation removed all protection', correction_started=bool(deltas))
        row.update(selection=selection, repair_round=1,
            delta={'parent_sha256': reference['sha256'], 'added_pixels': int((merged & ~before).sum()),
                   'deleted_pixels': int((before & ~merged).sum()), 'action': deepcopy(action)})
        for field in ('content_key', 'mask', 'views'):
            row.pop(field)
        result = self._export(row, directory, merged=merged, before=before)
        write_json(receipt, result)
        self.latest[row['input_key']] = brief['product_region'] = result
        return result['content_key'] != reference['content_key']

    def _export(self, row, directory, *, merged=None, before=None):
        import numpy as np
        from PIL import Image, ImageDraw, ImageOps
        width, height = row['base']['size']
        if merged is None:
            merged = np.zeros((height, width), dtype=bool)
            for support in _owned_masks(row, row['selection'], self.job).values():
                merged |= support
        revision = input_revision_id({'row': row, 'pixels': __import__('hashlib').sha256(merged.tobytes()).hexdigest()})
        output = directory/revision; output.mkdir(parents=True, exist_ok=True)
        def save(image, name):
            path = output/name; image.save(path)
            return {'path': path.relative_to(self.job).as_posix(), 'sha256': file_sha256(path)}
        rgba = np.zeros((height, width, 4), dtype=np.uint8); rgba[:, :, 3] = merged.astype('uint8')*255
        row['mask'] = save(Image.fromarray(rgba, 'RGBA'), 'api_mask.png')
        with Image.open(resolve_job_owned_path(self.job, row['base']['path'])) as source:
            pixels = np.asarray(source.convert('RGB'))
        def overlay(mask):
            image = pixels.copy(); image[mask] = (image[mask]*.6+np.array([20,220,80])*.4).astype('uint8')
            return Image.fromarray(image)
        points = region_point_map(row['intent'])
        raw = Image.fromarray(pixels); draw = ImageDraw.Draw(raw)
        for identity, point in points.items():
            x, y = point['x']*width, point['y']*height
            color = '#005bff' if point['polarity'] == 'positive' else '#ed183b'
            draw.rectangle((x-5,y-5,x+5,y+5), outline=color, width=2)
            draw.text((x+7,y), identity, fill=color)
        sheet = Image.new('RGB', (1600, 840), 'white'); draw = ImageDraw.Draw(sheet)
        draw.text((10,8), row['child']+' / '+row['base']['source_id']+' | RAW SOURCE / proposed protection (not verified truth)', fill='black')
        sheet.paste(ImageOps.contain(raw, (780,790)), (10,40))
        sheet.paste(ImageOps.contain(overlay(merged), (780,790)), (810,40))
        views = [save(sheet, 'proposed_overlay.png')]
        # Keep source-center detail available without another semantic judge or
        # inherited point verdict. Conflicts are a focus hint, not a gate.
        locations = {}
        for identity, point in points.items():
            x, y = min(width-1, int(point['x']*width)), min(height-1, int(point['y']*height))
            entry = locations.setdefault((x,y), {'ids': [], 'points': []})
            entry['ids'].append(identity); entry['points'].append(point)
        focus = sorted(locations.items(), key=lambda pair: not any(
            (p['polarity'] == 'positive') != bool(merged[pair[0][1],pair[0][0]]) for p in pair[1]['points']))[:8]
        if focus:
            sheet = Image.new('RGB', (1600, ((len(focus)+3)//4)*240), 'white'); draw = ImageDraw.Draw(sheet)
            protected = overlay(merged)
            for i, ((x,y), entry) in enumerate(focus):
                half = max(20, round(min(width,height)*.1))
                crop = (max(0,x-half), max(0,y-half), min(width,x+half), min(height,y+half))
                left, top = i%4*400, i//4*240
                draw.text((left+3,top+3), '/'.join(entry['ids'])+' | RAW / proposed', fill='black')
                draw.text((left+3,top+19), '; '.join(dict.fromkeys(p['query'] for p in entry['points']))[:55], fill='black')
                for offset, original in ((0,Image.fromarray(pixels)),(200,protected)):
                    local = ImageOps.contain(original.crop(crop), (195,195))
                    cx, cy = (x-crop[0])*local.width/(crop[2]-crop[0]), (y-crop[1])*local.height/(crop[3]-crop[1])
                    marker = ImageDraw.Draw(local)
                    for dx,dy in ((-1,-1),(-1,1),(1,-1),(1,1)):
                        marker.line([(cx+dx*5,cy+dy*8),(cx+dx*5,cy+dy*5),(cx+dx*8,cy+dy*5)],fill='#ff2030',width=2)
                    sheet.paste(local,(left+offset,top+42))
            views.append(save(sheet,'anchor_details.png'))
        # Keep all candidate IDs visible, without repeated point verdict/catalog prose.
        for offset in range(0, len(row['candidates']), 9):
            page = row['candidates'][offset:offset+9]
            sheet = Image.new('RGB', (900, ((len(page)+2)//3)*340), 'white'); draw = ImageDraw.Draw(sheet)
            for i, candidate in enumerate(page):
                x, y = i%3*300, i//3*340
                crop = candidate['crop']; bounds = (int(crop['left']*width), int(crop['top']*height), int(crop['right']*width), int(crop['bottom']*height))
                sheet.paste(ImageOps.contain(overlay(_mask(self.job, candidate)).crop(bounds), (300,290)), (x,y+45))
                draw.text((x+3,y+3), candidate['candidate_id'], fill='black')
                draw.text((x+3,y+18), candidate['parent_id']+'/'+candidate['part_id'], fill='black')
                draw.text((x+3,y+31), f"positive={candidate['positive_anchor_hits']} negative={candidate['negative_anchor_hits']} (diagnostic)", fill='black')
            views.append(save(sheet, f'candidates_{offset//9:02d}.png'))
        if before is not None:
            delta = pixels.copy(); delta[merged & ~before] = [20,220,80]; delta[before & ~merged] = [245,35,40]
            views.append(save(Image.fromarray(delta), 'delta.png'))
        row['views'] = views; row['content_key'] = _region_content_key(row, self.job)
        path = output/'region.json'; write_json(path, row)
        return {'path': path.relative_to(self.job).as_posix(), 'sha256': file_sha256(path), 'input_key': row['input_key'], 'content_key': row['content_key']}

"""Child design execution contracts; no simulated verdict claims image quality."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from core.image_prompt_compiler import compile_task_prompt
from core.palette_registry import planned_palette_diagnostics
from core.visual_design_kit import _finish_image_briefs
from core.visual_design_kit_compiler import compile_visual_design_kit_response, design_binding_request
from tests.current_image_contract_fixture import current_art_direction, current_image_direction, current_image_task, current_physical_view, supported_review_results


def check_child_components(case):
    source = {'source_id': 'source_06', 'source_index': 6, 'role': 'scene', 'source_sha256': 'a'*64,
              'input_revision_id': 'regression', 'claims': [], 'measurements': [],
              'observation': {'physical_views': [current_physical_view()], 'objects': [], 'text_gaps': [],
                              'reference_views': [{'view_id': 'view_01', 'purposes': ['appearance']}], 'evidence_gaps': []}}
    art = current_art_direction()
    art['palette_direction']['bedding'] = {
        'fitted_sheet': '#F0EDE6 cotton, solid', 'duvet_cover': '#D9A066 cotton, honeycomb weave',
        'primary_pillowcase': '#F0EDE6 cotton, solid', 'throw_blanket': '#C87D55 linen, solid',
    }
    components = ['room.wall', 'room.floor', *('bedding.' + key for key in art['palette_direction']['bedding'])]
    direction = current_image_direction(source_id=source['source_id'])
    direction['presentation']['components'] = components
    raw = {'family_art_direction': art, 'image_briefs': [
        {'role': role, 'source_id': source['source_id'], 'image_direction': deepcopy(direction)} for role in ('main', 'scene')]}
    request = design_binding_request(raw['image_briefs'][1], art, source=source)
    case.assertEqual(['presentation_state:scene'], request['physical_operations'])
    with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as reviewer, patch(
            'core.visual_design_kit.gemini_stream_generate') as repair:
        planned = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame',
            source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+5, cached=None)
        case.assertTrue(all(row['status'] == 'ready' for row in planned['image_briefs'] if row['role'] in {'main', 'scene'}))
        case.assertEqual(1, reviewer.call_count)
        repair.assert_not_called()
    unknown = deepcopy(raw)
    unknown['image_briefs'][1]['image_direction']['unowned_design'] = 'A second per-image palette'
    invalid = compile_visual_design_kit_response(unknown, source_manifest=[source])
    case.assertIn('current named design fields', next(row for row in invalid['image_briefs'] if row['role'] == 'scene')['error'])
    for role in ('main', 'scene', 'func', 'size'):
        task = current_image_task(role, category_id='bed_frame')
        task['category_image_policy']['main_image_policy'] = 'product_first_lifestyle'
        task['family_art_direction'] = art
        task['image_direction']['environment_mode'] = 'designed_environment'
        task['image_direction']['presentation']['components'] = components
        prompt = compile_task_prompt(task=task)
        for component in components:
            group, part = component.split('.')
            case.assertEqual(1, prompt.count(component + ' = ' + art['palette_direction'][group][part]))
        task['image_direction']['presentation']['components'] = []
        conditional = compile_task_prompt(task=task)
        for component in components:
            group, part = component.split('.')
            case.assertEqual(1, conditional.count(component + ' = ' + art['palette_direction'][group][part]))
        case.assertIn('they do not add objects or change the product presentation', conditional)
        task['image_direction']['environment_mode'] = 'graphic_canvas'
        canvas = compile_task_prompt(task=task)
        case.assertNotIn('room.wall =', canvas)
        for component in art['palette_direction']['bedding']:
            case.assertNotIn('bedding.' + component + ' =', canvas)
        case.assertNotIn('Target components:', canvas)
        case.assertNotIn(art['environment_and_staging'], canvas)
        if role == 'main':
            task['category_image_policy']['main_image_policy'] = 'white_background'
            task['image_direction']['environment_mode'] = 'designed_environment'
            case.assertNotIn('Target components:', compile_task_prompt(task=task))
    white = design_binding_request(raw['image_briefs'][0], art, source=source, main_policy='white_background')
    lifestyle = design_binding_request(raw['image_briefs'][0], art, source=source, main_policy='product_first_lifestyle')
    case.assertNotIn('room', white['shared_design']['palette_direction'])
    case.assertNotIn('environment_and_staging', white['shared_design'])
    case.assertIn('room', lifestyle['shared_design']['palette_direction'])
    altered_room = deepcopy(art)
    altered_room['palette_direction']['room']['wall'] = '#DDCCBB paint'
    case.assertEqual(white['key'], design_binding_request(raw['image_briefs'][0], altered_room, source=source,
        main_policy='white_background')['key'])
    case.assertNotEqual(lifestyle['key'], design_binding_request(raw['image_briefs'][0], altered_room, source=source,
        main_policy='product_first_lifestyle')['key'])
    case.assertIn('palette_direction.bedding.throw_blanket', planned_palette_diagnostics(art)['colors'])
    _check_execution_conflicts(case, source, raw)
    _check_shared_leaf_scope(case, source, raw)
    _check_p4_contracts(case)


def _check_shared_leaf_scope(case, source, raw):
    from core.image_task_inputs import shared_design_values
    from core.image_tasks import _task_fingerprint
    from core.visual_semantics import _planning_review_rows
    leaf = 'palette_direction.room.wall'
    changed = '#F7F5EF matte mineral paint, solid'
    def review(requests, **kwargs):
        result = supported_review_results(requests)
        for request in requests:
            shared = shared_design_values(request['shared_design'])
            if request['role_design']['role'] == 'scene' and shared.get(leaf) != changed:
                result[request['key']]['findings'].append(dict(operation='shared_design:' + leaf,
                    status='contradiction', reason='Only the wall definition conflicts with the intended finish'))
        return result
    for edits, accepted in (({leaf: changed}, True),
                            ({leaf: changed, 'palette_direction.bedding.duvet_cover': '#CC5522 cotton'}, False),
                            ({'palette_direction': raw['family_art_direction']['palette_direction']}, False)):
        def repair(prompt, paths, **kwargs):
            payload = json.loads(prompt.split('\n', 1)[1])
            case.assertEqual({leaf: shared_design_values(raw['family_art_direction'])[leaf]}, payload['shared_paths_to_repair'])
            return json.dumps({'image_briefs': [raw['image_briefs'][1]], 'shared_design_repairs': edits})
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review), patch(
                'core.visual_design_kit.gemini_stream_generate', side_effect=repair):
            fixed = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+5, cached=None)
            scene = next(row for row in fixed['image_briefs'] if row['role'] == 'scene')
            case.assertEqual('ready' if accepted else 'pending', scene['status'])
        before = shared_design_values(raw['family_art_direction'])
        after = shared_design_values(fixed['family_art_direction'])
        case.assertEqual({leaf} if accepted else set(), {key for key in before if before[key] != after[key]})
        task = current_image_task('scene', category_id='bed_frame')
        task['family_art_direction'] = raw['family_art_direction']
        task['image_direction']['presentation']['components'] = []
        task['image_direction']['environment_mode'] = 'graphic_canvas'
        previous = _task_fingerprint(task)
        task['family_art_direction'] = fixed['family_art_direction']
        case.assertEqual(previous, _task_fingerprint(task))
    request = dict(key='binding', kind='design_binding', physical_operations=[], shared_design=raw['family_art_direction'])
    for path in ('palette_direction', 'palette_direction.bedding', 'palette_direction.undefined.item'):
        good, errors = _planning_review_rows([dict(key='binding', status='contradiction', reason='Conflict', findings=[
            dict(operation='shared_design:' + path, status='contradiction', reason='Conflict')])], [request])
        case.assertFalse(good)
        case.assertIn('existing leaf path', errors['binding'])


def _check_execution_conflicts(case, source, raw):
    """Exercise routing of model findings, not claim regexes can judge designs."""
    from core.visual_design_kit import compact_product_claims
    claims = compact_product_claims({'title': 'White wood bed frame', 'specs': {'width': '64 in'}})
    for wrong in ('Show a black metal bed frame', 'Make the frame 60 inches wide', 'Use blue bedding instead of the assigned component color'):
        planned = deepcopy(raw)
        scene = next(row for row in planned['image_briefs'] if row['role'] == 'scene')
        good = scene['image_direction']['visual_goal']
        scene['image_direction']['visual_goal'] = wrong
        requests_seen = []
        def review(requests, **kwargs):
            requests_seen.append(requests)
            results = supported_review_results(requests)
            for request in requests:
                case.assertEqual(claims, request['required_facts']['product_claims'])
                if request['role_design']['visual_goal'] == wrong:
                    results[request['key']].update(status='contradiction', findings=[{
                        'operation': 'presentation_state:scene', 'status': 'contradiction', 'reason': wrong}])
            return results
        def repair(prompt, paths, **kwargs):
            payload = json.loads(prompt.split('\n', 1)[1])
            case.assertEqual(['scene'], [row['role'] for row in payload['pending']])
            ids = {key for row in payload['claim_texts'] for key in row['evidence_ids']}
            case.assertTrue({row['evidence_id'] for row in claims} <= ids)
            case.assertNotIn('source_00', {row['source_id'] for row in payload['source_evidence']})
            fixed = deepcopy(scene)
            fixed['image_direction']['visual_goal'] = good
            return json.dumps({'image_briefs': [fixed]})
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review), patch(
                'core.visual_design_kit.gemini_stream_generate', side_effect=repair) as remote:
            result = _finish_image_briefs(planned, job=Path(tmp), child='B1', source_manifest=[source], product_claims=claims,
                category_id='bed_frame', source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
        case.assertEqual(1, remote.call_count)
        case.assertEqual(['scene'], [row['role_design']['role'] for row in requests_seen[1]])
        case.assertTrue(all(row['status'] == 'ready' for row in result['image_briefs'] if row['role'] in {'main', 'scene'}))
        case.assertEqual(raw['family_art_direction'], result['family_art_direction'])
    planned = deepcopy(raw)
    scene = next(row for row in planned['image_briefs'] if row['role'] == 'scene')
    planned['family_art_direction']['palette_direction']['product'] = {'frame': '#000000 black metal'}
    planned['image_briefs'][0]['image_direction']['presentation']['components'].append('product.frame')
    def review_shared(requests, **kwargs):
        results = supported_review_results(requests)
        for request in requests:
            if 'product' in request['shared_design']['palette_direction']:
                results[request['key']].update(status='contradiction', findings=[{
                    'operation': 'shared_design:palette_direction.product.frame', 'status': 'contradiction',
                    'reason': 'Sold frame finish is not editable staging'}])
        return results
    def repair_shared(prompt, paths, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        case.assertEqual({'palette_direction.product.frame': '#000000 black metal'}, payload['shared_paths_to_repair'])
        drafts = [row['draft'] for row in payload['pending']]
        for draft in drafts:
            draft['image_direction']['presentation']['components'] = [key for key in draft['image_direction']['presentation']['components'] if key != 'product.frame']
        return json.dumps({'image_briefs': drafts,
                           'shared_design_repairs': {'palette_direction.product.frame': None}})
    with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review_shared), patch(
            'core.visual_design_kit.gemini_stream_generate', side_effect=repair_shared) as remote:
        result = _finish_image_briefs(planned, job=Path(tmp), child='B1', source_manifest=[source], product_claims=claims,
            category_id='bed_frame', source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
    case.assertEqual(1, remote.call_count)
    case.assertEqual(raw['family_art_direction'], result['family_art_direction'])
    case.assertTrue(all(row['status'] == 'ready' for row in result['image_briefs'] if row['role'] in {'main', 'scene'}))


def _check_p4_contracts(case):
    from core.visual_design_kit_compiler import _compile_art_direction, validate_image_brief_draft
    from core.image_task_inputs import task_specs, role_art_direction
    from core.design_reference_library import brand_design_brief
    from tests.test_visual_design_remediation import _evidence_source
    art = current_art_direction()
    nested = deepcopy(art)
    nested['palette_direction'] = {'non_product_group': {'room': '#F5F2EB plaster, #CBB89D oak'}}
    with case.assertRaisesRegex(ValueError, 'replace schema placeholders'):
        _compile_art_direction(nested)
    nested['palette_direction'] = {'bedding': {'duvet': '#FAF8F5 linen, #D9CDBF throw'}}
    with case.assertRaisesRegex(ValueError, 'separate combined components'):
        _compile_art_direction(nested)
    case.assertEqual([], planned_palette_diagnostics(_compile_art_direction(art))['unresolved'])
    with tempfile.TemporaryDirectory() as tmp:
        brief = brand_design_brief(Path(tmp))
        case.assertIn('Large pill-shaped', brief['avoid'])
        case.assertIn('Small local backing', brief['avoid'])
    source = _evidence_source('func')
    source['observation']['physical_views'][0]['extent'] = 'detail'
    direction = current_image_direction()
    draft = dict(role='func', source_id=source['source_id'], image_direction=direction,
                 display_copy={'title': None, 'labels': []})
    with case.assertRaisesRegex(ValueError, 'whole_product presentation needs'):
        validate_image_brief_draft(draft, source, art, [source], 'bed_frame')
    direction['presentation']['scope'] = 'detail_only'
    validate_image_brief_draft(draft, source, art, [source], 'bed_frame')
    whole = _evidence_source('main', source_id='source_07')
    direction['presentation']['scope'] = 'whole_product'
    direction['evidence_usage'].append(dict(source_id='source_07', view_id='view_01', usage='verification', covered_by=[]))
    validate_image_brief_draft(draft, source, art, [source, whole], 'bed_frame')
    earlier = _evidence_source('size', source_id='source_01')
    case.assertEqual('source_07', task_specs({}, [earlier, whole])[0]['source']['source_id'])
    case.assertEqual('source_01', task_specs({}, [earlier])[0]['source']['source_id'])
    direction['environment_mode'] = 'graphic_canvas'
    direction['presentation']['components'] = []
    case.assertEqual({}, role_art_direction(art, direction, 'size')['palette_direction'])
    direction['presentation']['components'] = ['bath.towels']
    case.assertEqual({'bath': art['palette_direction']['bath']}, role_art_direction(art, direction, 'func')['palette_direction'])
    measured = _evidence_source('size')
    measured['claims'] = [{'evidence_id': 'm', 'text': 'Bed Frame: 83 in x 64 in x 16 in'}]
    size = dict(role='size', source_id=measured['source_id'], image_direction=current_image_direction(environment='graphic_canvas'),
                display_copy={'title': None, 'labels': [{'evidence_ids': ['m'], 'text': measured['claims'][0]['text']}]})
    with case.assertRaisesRegex(ValueError, 'numeric dimensions and capacity'):
        validate_image_brief_draft(size, measured, art, [measured], 'bed_frame')
    _check_link_repair(case, art, source, whole)


def _check_link_repair(case, art, source, whole):
    from tests.test_visual_design_remediation import _evidence_source
    measured = _evidence_source('size', source_id='source_01')
    measured['claims'] = [{'evidence_id': 'capacity', 'text': '400 lb'}]
    size = dict(role='size', source_id=measured['source_id'], image_direction=current_image_direction(
        source_id=measured['source_id'], environment='graphic_canvas'),
        display_copy={'title': None, 'labels': [{'evidence_ids': ['capacity'], 'text': '400 lb'}]})
    direction = current_image_direction(source_id=whole['source_id'])
    direction['evidence_usage'].append(dict(source_id=source['source_id'], view_id='view_01', usage='integrated',
                                          covered_by=[{'source_id': whole['source_id'], 'view_id': 'view_01'}]))
    detail = current_image_direction(source_id=source['source_id'])
    detail['presentation']['scope'] = 'detail_only'
    raw = dict(family_art_direction=art, image_briefs=[
        dict(role='main', source_id=whole['source_id'], image_direction=direction),
        dict(role='func', source_id=source['source_id'], image_direction=detail, display_copy={'title': None, 'labels': []}), size])
    for mode in ('valid', 'removed', 'unknown_usage', 'malformed_usage', 'missing', 'duplicate', 'wrong_anchor'):
        def repair(prompt, paths, **kwargs):
            request = json.loads(prompt.split('\n', 1)[1])
            case.assertEqual(['source_00/view_01'], request['schemas'][0]['image_direction']['evidence_usage'][1]['covered_by'])
            fixed = deepcopy(raw['image_briefs'][0])
            usage = fixed['image_direction']['evidence_usage']
            usage[-1]['covered_by'] = [whole['source_id'] + '/view_01']
            if mode == 'removed':
                usage.pop()
            elif mode == 'unknown_usage':
                usage[-1]['usage'] = 'covered'
            elif mode == 'malformed_usage':
                usage[-1]['usage'] = ['integrated']
            elif mode == 'wrong_anchor':
                fixed['source_id'] = 'unknown'
            fixed_size = deepcopy(size)
            fixed_size['display_copy']['labels'] = []
            rows = [fixed_size] + ([] if mode == 'missing' else [fixed, fixed] if mode == 'duplicate' else [fixed])
            response = json.dumps({'image_briefs': rows})
            case.assertTrue(kwargs['response_validator'](response))
            return response
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results), patch(
                'core.visual_design_kit.gemini_stream_generate', side_effect=repair) as remote:
            result = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source, whole, measured],
                category_id='bed_frame', source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+5, cached=None)
            if mode != 'valid':
                case.assertEqual({'main'}, set(json.loads((Path(tmp) / 'brief_repair_error.txt').read_text())))
        main = next(row for row in result['image_briefs'] if row['role'] == 'main')
        case.assertEqual('ready' if mode == 'valid' else 'pending', main['status'])
        case.assertEqual('ready', next(row for row in result['image_briefs'] if row['role'] == 'size')['status'])
        case.assertEqual(detail, next(row for row in result['image_briefs'] if row['role'] == 'func')['image_direction'])
        case.assertEqual(art, result['family_art_direction'])
        case.assertEqual(1, remote.call_count)

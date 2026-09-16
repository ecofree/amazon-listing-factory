"""Target-component contracts; simulated verdicts are not visual-quality evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from core.image_prompt_compiler import compile_task_prompt
from core.palette_registry import planned_palette_diagnostics
from core.visual_design_kit import _finish_source_briefs
from core.visual_design_kit_compiler import compile_visual_design_kit_response, design_binding_request
from tests.current_image_contract_fixture import (
    current_art_direction, current_image_direction, current_image_task, current_physical_view, supported_review_results,
)


def check_child_components(case):
    source = {'source_id': 'source_06', 'role': 'scene', 'source_sha256': 'a'*64,
              'input_revision_id': 'regression', 'claims': [], 'measurements': [],
              'observation': {'physical_views': [current_physical_view()], 'objects': []}}
    art = current_art_direction()
    art['palette_direction']['bedding'] = {
        'fitted_sheet': '#F0EDE6 cotton, solid', 'duvet_cover': '#D9A066 cotton, honeycomb weave',
        'primary_pillowcase': '#F0EDE6 cotton, solid', 'throw_blanket': '#C87D55 linen, solid',
    }
    draft = {'source_id': source['source_id'], 'image_direction': current_image_direction(source_id=source['source_id'])}
    components = ['room.wall', 'room.floor', *('bedding.' + key for key in art['palette_direction']['bedding'])]
    draft['image_direction'].update(scene_objects=components, creative_brief='Add designed bedding and a new room, using child component names.')
    raw = {'family_art_direction': art, 'source_briefs': [draft]}
    request = design_binding_request(draft, art, source=source)
    case.assertEqual(['target_consistency:source_06'], request['physical_operations'])
    case.assertEqual('ready', compile_visual_design_kit_response(raw, source_manifest=[source],
        category_id='bed_frame', claim_reviews=supported_review_results([request]))['source_briefs'][0]['status'])
    changed = deepcopy(source)
    changed['observation']['objects'] = [{'object_id': 'quilt', 'sale_membership': 'staging', 'visibility': 'visible',
        'kind': 'bedding', 'state': 'occludes frame', 'relations': []}]
    case.assertEqual(request['key'], design_binding_request(draft, art, source=changed)['key'])
    unknown = deepcopy(raw)
    unknown['source_briefs'][0]['image_direction']['scene_objects'].append('bedding.undefined')
    case.assertIn('defined target components', compile_visual_design_kit_response(unknown,
        source_manifest=[source])['source_briefs'][0]['error'])
    for role in ('main', 'scene', 'func', 'size'):
        task = current_image_task(role, category_id='bed_frame')
        task['category_image_policy']['main_image_policy'] = 'product_first_lifestyle'
        task['family_art_direction'] = art
        task['image_direction']['scene_objects'] = components
        prompt = compile_task_prompt(task=task)
        for component in components:
            group, part = component.split('.')
            case.assertEqual(1, prompt.count(component + ' = ' + art['palette_direction'][group][part]))
        task['image_direction']['scene_objects'] = ['bedding.duvet_cover']
        task['image_direction']['environment_mode'] = 'graphic_canvas'
        canvas = compile_task_prompt(task=task)
        case.assertNotIn('room.wall =', canvas)
        case.assertIn('bedding.duvet_cover =', canvas)
        if role == 'main':
            task['image_direction']['scene_objects'] = components
            task['category_image_policy']['main_image_policy'] = 'white_background'
            case.assertNotIn('room.wall =', compile_task_prompt(task=task))
    case.assertIn('palette_direction.bedding.throw_blanket', planned_palette_diagnostics(art)['colors'])

    # Both lifestyle roles reach the existing joint review, without source-prop checks.
    for role in ('main', 'scene'):
        target = dict(source, role=role)
        conflict = deepcopy(raw)
        conflict['source_briefs'][0]['image_direction']['creative_brief'] = 'Use bright blue bedding.duvet_cover beside the bed.'
        def check_target(requests, **kwargs):
            case.assertEqual(1, len(requests))
            case.assertEqual(['target_consistency:source_06'], requests[0]['physical_operations'])
            case.assertIn('bright blue', requests[0]['role_design']['creative_brief'])
            result = supported_review_results(requests)
            result[requests[0]['key']]['findings'][0].update(status='contradiction', reason='Target blue duvet conflicts with the named warm duvet component')
            return result
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=check_target) as checked, patch(
                'core.visual_design_kit.gemini_stream_generate', side_effect=TimeoutError('offline repair unavailable')):
            result = _finish_source_briefs(conflict, source_manifest=[target], category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
            case.assertEqual(1, checked.call_count)
            case.assertEqual('pending', result['source_briefs'][0]['status'])
            case.assertEqual('brief', result['source_briefs'][0]['failure_owner'])

    # Repair identified faulty definitions, not unrelated shared colors.
    broken = deepcopy(raw)
    source['role'] = 'func'
    draft['display_copy'] = {'title': None, 'labels': []}
    broken['source_briefs'] = [draft]
    broken['family_art_direction']['palette_direction']['bedding']['duvet_cover'] = '#000000 conflicting assignment'
    field = 'palette_direction.bedding.duvet_cover'
    def review(requests, **kwargs):
        result = supported_review_results(requests)
        if kwargs['shared_design']['palette_direction']['bedding']['duvet_cover'].startswith('#000000'):
            for row in result.values():
                row['findings'].append({'operation': 'shared_prose:' + field,
                    'status': 'contradiction', 'reason': 'Explicit target assignment conflict, not an aesthetic score'})
        return result
    for repair_field, expected in ((field, 'ready'), ('graphic_direction.text_color', 'pending')):
        payload = {'source_briefs': [draft], 'shared_prose': {repair_field: art['palette_direction']['bedding']['duvet_cover']}}
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review), \
                patch('core.visual_design_kit.gemini_stream_generate', return_value=json.dumps(payload)) as call:
            result = _finish_source_briefs(broken, source_manifest=[source], category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
            case.assertEqual(1, call.call_count)
            case.assertEqual(expected, result['source_briefs'][0]['status'])
            case.assertEqual(art if expected == 'ready' else broken['family_art_direction'], result['family_art_direction'])

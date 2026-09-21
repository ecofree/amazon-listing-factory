"""Boundary counterexamples exercised by the existing production test cases."""
from core.image_task_inputs import initial_output_inventory
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from core.image_task_inputs import task_specs
from core.visual_design_kit_compiler import (
    compile_visual_design_kit_response, design_binding_request, validate_compiled_visual_design_kit,
)
from tests.current_image_contract_fixture import (
    current_art_direction, current_image_direction, current_product_feature,
    supported_design_reviews, supported_review_results,
)


def _source(key='source_00', role='func', *, disputed=False):
    return {'source_id': key, 'source_index': int(key.split('_')[-1]),
            'source_sha256': 'a' * 64, 'input_revision_id': 'evidence-1',
            'role': role, 'measurements': [],
            'claims': [{'evidence_id': 'shelf', 'text': 'Adjustable Shelf'}] if role == 'func' else [],
            'observation': {'status': 'success', 'product_features': [current_product_feature()], 'product_extent': 'whole_view',
                'reference_purposes': ['appearance', 'feature'],
                'evidence_gaps': [], 'text_gaps': [],
                'objects': [{'object_id': 'frame', 'kind': 'frame', 'state': 'visible',
                             'sale_membership': 'unknown', 'membership_evidence': [],
                             'visibility': 'visible'}] if disputed else []}}


def _draft(key='source_00', role='func'):
    draft = {'role': role, 'source_id': key, 'image_direction': current_image_direction(source_id=key)}
    if role.split('_', 1)[0] == 'func':
        draft['display_copy'] = {'title': None, 'labels': [{'evidence_ids': ['shelf'], 'text': 'Adjustable Shelf'}]}
    return draft


def _plan(sources):
    return {'family_art_direction': current_art_direction(), 'image_briefs': [
        _draft(spec['source']['source_id'], spec['role'])
        for spec in task_specs({}, sources, inventory=initial_output_inventory(sources), include_optional=True) if spec['source']]}


def _brief(payload, role):
    return next(row for row in payload['image_briefs'] if row['role'] == role)


def verify_review_projection(test):
    source = _source(disputed=True)
    raw = _plan([source])
    draft = _brief(raw, 'func')
    before = deepcopy(raw)
    reviews = supported_design_reviews(raw, [source])
    compiled = compile_visual_design_kit_response(raw, output_inventory=initial_output_inventory([source]), source_manifest=[source], claim_reviews=reviews)
    test.assertEqual('ready', _brief(compiled, 'func')['status'])
    test.assertEqual(draft['image_direction'], _brief(compiled, 'func')['image_direction'])
    test.assertEqual(['Adjustable Shelf'], _brief(compiled, 'func')['display_copy_contract']['labels'])
    test.assertEqual(before, raw)
    for field, value in (('visual_goal', 'Show the shelf support and its joints'), ('environment_mode', 'graphic_canvas')):
        changed = deepcopy(compiled)
        _brief(changed, 'func')['image_direction'][field] = value
        with test.assertRaisesRegex(ValueError, 'no longer matches'):
            validate_compiled_visual_design_kit(changed, source_manifest=[source])
    previous_request = design_binding_request(draft, raw['family_art_direction'], source=source)
    test.assertIn(previous_request['key'], reviews)
    from tests.current_image_contract_fixture import current_measurement_rows
    source['measurements'] = current_measurement_rows()
    draft['image_direction']['measurement_ids'] = ['source_00:width']
    request = design_binding_request(draft, raw['family_art_direction'], source=source)
    test.assertEqual('Cabinet', request['required_facts']['measurements'][0]['measured_part'])
    test.assertNotEqual(previous_request['key'], request['key'])
    from core.visual_design_kit import _finish_image_briefs
    for field, invalid in (('product_sources', ['unknown_source']),
                           ('design_transfer', [{'reference_id': 'missing'}]), ('environment_mode', None)):
        sources = [_source(), _source('source_01', 'scene')]
        malformed = _plan(sources)
        _brief(malformed, 'func')['image_direction'][field] = invalid
        with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate', return_value=json.dumps({'image_briefs': [_draft()]})), patch(
                'core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as review:
            result = _finish_image_briefs(malformed, output_inventory=initial_output_inventory(sources), job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
        review.assert_not_called()
        test.assertEqual({'main': 'ready', 'scene': 'ready', 'func': 'ready', 'size': 'pending'},
                         {row['role']: row['status'] for row in result['image_briefs']})
        test.assertEqual('observation', _brief(result, 'size')['failure_owner'])


def verify_shared_repair(test):
    """A role-local repair cannot escalate into shared design or sibling changes."""
    from core.visual_design_kit import _finish_image_briefs
    sources = [_source(), _source('source_01')]
    raw = _plan(sources)
    _brief(raw, 'func')['image_direction']['environment_mode'] = None
    valid_raw = deepcopy(raw)
    _brief(valid_raw, 'func')['image_direction'] = current_image_direction()
    before = compile_visual_design_kit_response(raw, output_inventory=initial_output_inventory(sources), source_manifest=sources, claim_reviews=supported_design_reviews(valid_raw, sources))
    def repair(prompt, paths, **kwargs):
        request = json.loads(prompt.split('\n', 1)[1])
        test.assertEqual(['func'], [row['role'] for row in request['pending']])
        test.assertEqual(['source_00', 'source_01'], [row['source_id'] for row in request['source_evidence']])
        test.assertEqual(raw['family_art_direction'], request['shared_design'])
        return json.dumps({'image_briefs': [_draft()]})
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as review, patch(
            'core.visual_design_kit.gemini_stream_generate', side_effect=repair) as remote:
        result = _finish_image_briefs(raw, output_inventory=initial_output_inventory(sources), job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame', source_paths=[],
            source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
    test.assertEqual(1, remote.call_count)
    review.assert_not_called()
    test.assertEqual('ready', _brief(result, 'func')['status'])
    test.assertEqual(raw['family_art_direction'], result['family_art_direction'])
    for sibling in ('main', 'scene', 'func_02', 'size'):
        test.assertEqual(_brief(before, sibling), _brief(result, sibling))
    unauthorized = {'image_briefs': [_draft()], 'family_art_direction': current_art_direction()}
    unauthorized['family_art_direction']['graphic_direction']['text_color'] = '#000000'
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as review, patch(
            'core.visual_design_kit.gemini_stream_generate', return_value=json.dumps(unauthorized)):
        result = _finish_image_briefs(raw, output_inventory=initial_output_inventory(sources), job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame', source_paths=[],
            source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertIn('outside the current repair contract', (Path(tmp) / 'brief_repair_error.txt').read_text())
    review.assert_not_called()
    test.assertEqual(before, result)
    alternate = deepcopy(valid_raw)
    _brief(alternate, 'func')['image_direction'] = current_image_direction(source_id='source_01')
    _brief(valid_raw, 'func')['image_direction']['product_sources'] = ['unknown_source']
    sources[1]['observation']['reference_purposes'] = ['feature']
    def switch_reference(prompt, paths, **kwargs):
        request = json.loads(prompt.split('\n', 1)[1])
        test.assertEqual(['source_00', 'source_01'], [r['source_id'] for r in request['source_evidence']])
        test.assertEqual([dict(attachment_number=1, source_id='source_00')], request['evidence_attachments'])
        test.assertEqual(['00.png'], [p.name for p in paths])
        return json.dumps({'image_briefs': [_brief(alternate, 'func')]})
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results), patch(
            'core.visual_design_kit.gemini_stream_generate', side_effect=switch_reference):
        corrected = _finish_image_briefs(valid_raw, output_inventory=initial_output_inventory(sources), job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame',
            source_paths=[Path(tmp)/'00.png'], source_originals=[], trace_dir=Path(tmp),
            deadline_monotonic=time.monotonic()+10, cached=None)
    test.assertEqual('ready', _brief(corrected, 'func')['status'])
    test.assertEqual('source_01', _brief(corrected, 'func')['image_direction']['product_sources'][0])
    for sibling in ('main', 'scene', 'func_02', 'size'):
        test.assertEqual(_brief(before, sibling), _brief(corrected, sibling))


def verify_observation_feedback(test):
    from core.visual_design_kit import observation_corrections
    source = _source(disputed=True)
    raw = _plan([source])
    reviews = supported_design_reviews(raw, [source])
    request = design_binding_request(_brief(raw, 'func'), raw['family_art_direction'], source=source)
    review = reviews[request['key']]
    review['findings'] = [{'operation': 'source_product:source_00', 'status': 'contradiction',
                          'reason': 'A sold frame support is clipped in the evidence crop'}]
    compiled = compile_visual_design_kit_response(raw, output_inventory=initial_output_inventory([source]), source_manifest=[source], claim_reviews=reviews)
    kit = {'children': {'B1': {**compiled, 'main_image_policy': 'product_first_lifestyle',
                             'source_references': [source], 'product_claims': [], 'input_revision_id': 'kit-1'}}}
    corrections = observation_corrections(kit)
    test.assertEqual({'B1'}, set(corrections))
    test.assertEqual({'source_00'}, set(corrections['B1']))
    test.assertEqual(source['source_sha256'], corrections['B1']['source_00']['source_sha256'])
    test.assertEqual(review['key'], corrections['B1']['source_00']['findings'][0]['review_key'])
    for extra in ('sold_membership:source_00', 'shared_design:photography_direction'):
        mixed = deepcopy(reviews)
        mixed[request['key']]['findings'].append({'operation': extra, 'status': 'contradiction',
                                                'reason': 'Requested depiction also conflicts with the clipped evidence'})
        combined = compile_visual_design_kit_response(raw, output_inventory=initial_output_inventory([source]), source_manifest=[source], claim_reviews=mixed)
        test.assertEqual('observation', _brief(combined, 'func')['failure_owner'])
        test.assertEqual(corrections, observation_corrections({'children': {'B1': {
            **kit['children']['B1'], **combined}}}))
    unreviewed_copy = deepcopy(raw)
    _brief(unreviewed_copy, 'func')['display_copy']['labels'][0]['text'] = 'Shelf height adjusts'
    combined = compile_visual_design_kit_response(unreviewed_copy, output_inventory=initial_output_inventory([source]), source_manifest=[source], claim_reviews=reviews)
    test.assertEqual('observation', _brief(combined, 'func')['failure_owner'])
    changed = deepcopy(kit)
    changed['children']['B1']['source_references'][0]['input_revision_id'] = 'changed'
    test.assertEqual({}, observation_corrections(changed))
    _verify_observation_cache(test, corrections['B1']['source_00'])
    _verify_feedback_stage(test, kit, corrections)
    _verify_correction_scope(test, corrections)
    _verify_bound_artifact_repair(test)


def verify_partial_review_rows(test):
    from core.image_task_inputs import shared_design_values
    from core.visual_design_kit import _finish_image_briefs
    from core.visual_semantics import _planning_review_rows
    sources = [_source(disputed=True), _source('source_01', 'scene', disputed=True)]
    raw = _plan(sources)
    _brief(raw, 'func')['display_copy']['labels'][0]['text'] = 'Shelf height adjusts'
    _brief(raw, 'func')['image_direction']['environment_mode'] = 'graphic_canvas'
    expected_scope = shared_design_values(design_binding_request(
        _brief(raw, 'func'), raw['family_art_direction'], source=sources[0])['shared_design'])
    scopes_seen = []
    requests_seen, repair_count = [], [0]

    def response(prompt, paths, **kwargs):
        payload = json.loads(prompt.split('\n', 1)[1])
        requests = payload['bindings']
        if requests_seen:
            test.assertEqual({requests[0]['key']}, set(payload['prior_protocol_errors']))
            test.assertIn('findings', payload['prior_protocol_errors'][requests[0]['key']])
        shared = shared_design_values(payload['shared_design'])
        test.assertNotIn('shared_design_fields', prompt)
        test.assertTrue(all('shared_design' not in row for row in requests))
        scopes_seen.append({row['role_design']['role']: {path: shared[path] for path in row['shared_design_paths']}
                           for row in requests if row['kind'] == 'design_binding'})
        test.assertEqual(expected_scope, scopes_seen[-1]['func'])
        requests_seen.append([(r['kind'], r.get('role_design', {}).get('role')) for r in requests])
        rows = [{**row, 'reason': 'Bound product evidence supports this operation'}
                for row in supported_review_results(requests).values()]
        for request, row in zip(requests, rows):
            if request['kind'] == 'product_claim':
                row.pop('findings', None)
            if request.get('role_design', {}).get('role') == 'func' and repair_count[0] == 0:
                row['findings'] = 'invalid list'
        payload = json.dumps({'reviews': rows})
        test.assertTrue(kwargs['response_validator'](payload))
        kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
        kwargs['attempt_observer']({'status': 'success', 'response_text': payload})
        return payload

    with TemporaryDirectory() as tmp, patch('core.visual_semantics.resolve_edit_references', return_value=[]), patch(
            'core.visual_semantics.gemini_stream_generate', side_effect=response), patch('core.visual_design_kit.gemini_stream_generate') as repair:
        arguments = dict(job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame',
                         source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10)
        result = _finish_image_briefs(raw, output_inventory=initial_output_inventory(arguments['source_manifest']), cached=None, **arguments)
        test.assertEqual('ready', _brief(result, 'main')['status'])
        test.assertEqual('ready', _brief(result, 'scene')['status'])
        test.assertEqual('review', _brief(result, 'func')['failure_owner'])
        test.assertTrue(_brief(result, 'func')['claim_reviews'])
        test.assertEqual([('design_binding', 'func')], requests_seen[1])
        findings = json.loads((Path(tmp)/'initial/planning_review_attempts.json').read_text())[0]
        test.assertEqual(1, findings['semantic_failed_rows'])
        test.assertEqual(3, findings['semantic_valid_rows'])
        repair_count[0] = 1
        resumed = _finish_image_briefs(raw, output_inventory=initial_output_inventory(arguments['source_manifest']), cached=result, **arguments)
        test.assertEqual([('design_binding', 'func')], requests_seen[2])
        test.assertEqual('ready', _brief(resumed, 'func')['status'])
        test.assertEqual(_brief(result, 'main'), _brief(resumed, 'main'))
        test.assertEqual(3, json.loads((Path(tmp)/'attempt_budget.json').read_text())['review'])
        repair.assert_not_called()
    test.assertTrue(any(path.startswith('palette_direction.room.') for path in scopes_seen[0]['scene']))
    test.assertFalse(any(path.startswith('palette_direction.room.') for path in scopes_seen[0]['func']))
    test.assertEqual(scopes_seen[0]['func'], scopes_seen[1]['func'])
    test.assertEqual(scopes_seen[0]['func'], scopes_seen[2]['func'])

    source_request = design_binding_request(_brief(raw, 'func'), raw['family_art_direction'], source=sources[0])
    source_review = dict(key=source_request['key'], status='contradiction', reason='Crop is incomplete', findings=[
        dict(operation='source_product:source_00', status='contradiction', reason='Support leg clipped')])
    valid, errors = _planning_review_rows([source_review], [source_request])
    test.assertFalse(errors)
    test.assertIn(source_request['key'], valid)
    required = dict(key='binding', kind='design_binding', physical_operations=['depiction'], shared_design={})
    finding = dict(operation='depiction', status='supported', reason='Visible in reference')
    for findings in ([], [finding, finding], [dict(finding, operation='unknown')], [finding, dict(finding, operation='unknown')]):
        valid, errors = _planning_review_rows([dict(key='binding', status='supported', reason='Review', findings=findings)], [required])
        test.assertFalse(valid)
        test.assertIn('binding', errors)

    requests = [dict(key=key, kind='product_claim') for key in ('a', 'b', 'c')]
    a = dict(key='a', status='supported', reason='Supported source', findings=[])
    b = dict(a, key='b')
    for rows in ([a, b, b], [a, dict(b, status=[]), None], [a, dict(b, findings=[None])]):
        valid, errors = _planning_review_rows(rows, requests)
        test.assertEqual({'a'}, set(valid))
        test.assertTrue({'b', 'c'} <= set(errors))
    with test.assertRaises(ValueError):
        _planning_review_rows({}, requests)
    for status in ('supported', 'inconclusive', 'contradiction'):
        row = dict(key='a', status=status, reason='Original reason', resolution='retry_review')
        valid, _ = _planning_review_rows([row], requests)
        test.assertEqual({**row, 'findings': []}, valid['a'])
    valid, errors = _planning_review_rows([dict(a, findings=None)], requests)
    test.assertFalse(valid)
    test.assertIn('a', errors)


def _verify_observation_cache(test, finding):
    from core.visual_semantics import observe_child_sources
    from core.io import read_json
    valid = {'source_id': 'source_00', 'role_guess': 'scene',
        'has_dimension_lines': False, 'has_callouts_or_panels': False, 'visible_numbers_or_units': [],
        'confidence': .95, 'evidence': [], 'measurements': [], 'text_observations': [],
        'objects': [{'object_id': 'frame', 'kind': 'frame', 'state': 'visible', 'sale_membership': 'unknown',
                     'visibility': 'visible', 'membership_evidence': []}], 'product_features': [current_product_feature()], 'product_extent': 'whole_view',
        'reference_purposes': ['appearance', 'feature'],
        'evidence_gaps': [], 'text_gaps': [],
        'variant_identity': {'status': 'unknown', 'observed_color': '', 'reason': 'Not identifiable', 'conflicts': []}}
    sibling = dict(valid, source_id='source_01')
    with TemporaryDirectory() as tmp:
        job = Path(tmp)
        sources = [{'source_id': row['source_id'], 'sha256': 'a'*64, 'ocr': [], 'path': job / (row['source_id']+'.png')}
                   for row in (valid, sibling)]
        from tests.current_image_contract_fixture import write_observation_images
        write_observation_images(sources)
        def canonical_response(prompt, images, **kwargs):
            request = json.loads(prompt.split('Input evidence, not response fields:\n', 1)[1])
            test.assertNotIn('fact_texts', request)
            test.assertEqual('White Frame', request['facts']['product.title'])
            observed = deepcopy(valid)
            observed['objects'][0].update(sale_membership='product', membership_evidence=[
                {'fact_id': key, 'quote': value} for key, value in request['facts'].items() if key == 'product.title'])
            observed['text_observations'] = [{'text': text, 'kind': kind} for text, kind in (
                ('8 Robust Plywood Slats', 'product_fact'), ('Embedded Design', 'product_fact'), ('High Quality', 'marketing'))]
            raw = json.dumps({'sources': [observed]})
            kwargs['response_validator'](raw)
            kwargs['attempt_observer']({'status': 'success', 'response_text': raw})
            return raw
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=canonical_response) as remote:
            result = observe_child_sources(job/'canonical_case', {'asin': 'canonical', 'title': 'White Frame'}, sources[:1])
        test.assertEqual(1, remote.call_count)
        test.assertEqual('success', result['source_00']['status'])
        from core.final_source_intents import _authored_claims
        test.assertEqual(['8 Robust Plywood Slats', 'Embedded Design'], [r['text'] for r in _authored_claims(result['source_00'])])
        events = [event for path in (job/'canonical_case/reports/source_observations').glob('*.attempts.json') for event in read_json(path)]
        test.assertEqual(1, events[0]['semantic_valid_rows'])
        test.assertEqual(0, events[0]['semantic_failed_rows'])
        injected = dict(valid, planning_correction={'source_revision': 'model-invented-control'}, correction_revision='model-claim')
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [injected, sibling]})):
            initial = observe_child_sources(job, {'asin': 'B1'}, sources)
            test.assertNotIn('planning_correction', initial['source_00'])
            test.assertEqual('', initial['source_00']['correction_revision'])
        correction = {'source_00': {'revision': '', 'planning_correction': finding, 'reason': finding}}
        corrected = deepcopy(valid)
        corrected['objects'][0]['state'] = 'The frame support and its joints are visible'
        corrected['product_features'][0]['physical_facts'].append(corrected['objects'][0]['state'])
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [corrected]})) as remote:
            result = observe_child_sources(job, {'asin': 'B1'}, sources, corrections=correction)
            test.assertEqual([sources[0]['path']], remote.call_args.args[1])
            test.assertEqual(corrected['objects'], result['source_00']['objects'])
            test.assertEqual(corrected['product_features'], result['source_00']['product_features'])
            test.assertEqual(finding, result['source_00']['planning_correction'])
            observe_child_sources(job, {'asin': 'B1'}, sources, corrections=correction)
            observe_child_sources(job, {'asin': 'B1'}, sources)
            test.assertEqual(1, remote.call_count)
        cache = next(path for path in (job / 'reports/source_observations').glob('*.json') if 'sources' in read_json(path))
        test.assertTrue(any(row.get('planning_correction') for row in read_json(cache).get('sources', [])))
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [valid, sibling]})):
            observe_child_sources(job, {'asin': 'B2'}, sources)
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=TimeoutError('offline fixture')) as remote:
            result = observe_child_sources(job, {'asin': 'B2'}, sources, corrections=correction)
            test.assertEqual('failed', result['source_00']['status'])
            test.assertEqual(2, remote.call_count)
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [corrected]})) as remote:
            result = observe_child_sources(job, {'asin': 'B2'}, sources, corrections=correction)
            test.assertEqual(1, remote.call_count)
            test.assertEqual('success', result['source_00']['status'])
            observe_child_sources(job, {'asin': 'B2'}, sources, corrections=correction)
            test.assertEqual(1, remote.call_count)
        def paid_success(*args, **kwargs):
            kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
            return json.dumps({'sources': [valid]})
        def paid_timeout(*args, **kwargs):
            kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
            raise TimeoutError('single-source submitted timeout')
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=paid_success):
            observe_child_sources(job, {'asin': 'B3'}, sources[:1])
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=paid_timeout) as remote:
            result = observe_child_sources(job, {'asin': 'B3'}, sources[:1], corrections=correction)
            test.assertEqual('failed', result['source_00']['status'])
            test.assertEqual(finding, result['source_00']['planning_correction'])
            observe_child_sources(job, {'asin': 'B3'}, sources[:1], corrections=correction)
            test.assertEqual(3, remote.call_count)
        from core.vision_errors import VisionRequestError
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=VisionRequestError(
                'visual_planning', 'queue_unavailable', 'not submitted', metadata={'physical_request_count': 0})):
            for _ in range(3):
                observe_child_sources(job, {'asin': 'B4'}, sources[:1])
        with patch('core.visual_semantics.gemini_stream_generate', side_effect=paid_success) as available:
            test.assertEqual('success', observe_child_sources(job, {'asin': 'B4'}, sources[:1])['source_00']['status'])
            test.assertEqual(1, available.call_count)
            observe_child_sources(job, {'asin': 'B3'}, sources[:1], corrections=correction)
            test.assertEqual(3, remote.call_count)


def _verify_feedback_stage(test, kit, corrections):
    from core import production
    with TemporaryDirectory() as tmp:
        request = production.JobRunRequest(job_dir=Path(tmp), plugin=type('Plugin', (), {'category_id': 'bed_frame'})(),
                                           deadline_monotonic=time.monotonic()+10)
        calls = []
        with patch.object(production, 'assert_family_matches_plugin'), patch(
                'core.visual_design_kit.visual_design_kits_current', return_value=False), patch(
                'core.visual_design_kit.build_visual_design_kits', side_effect=lambda **kw: calls.append('plan') or kit), patch(
                'core.final_source_intents.build_final_source_intents', side_effect=lambda **kw: calls.append(kw) or {'corrected_children': ['B1']}), patch(
                'core.image_tasks.image_tasks_current', return_value=False), patch(
                'core.image_tasks.build_image_tasks', side_effect=lambda **kw: calls.append('tasks') or {'tasks': []}), patch(
                'core.image_prompt_compiler.image_prompts_current', return_value=False), patch(
                'core.image_prompt_compiler.build_image_prompts', return_value={'prompts': []}):
            production._run_stage('brief', request=request)
        test.assertEqual(['plan', 'plan', 'tasks'], [row for row in calls if isinstance(row, str)])
        correction_calls = [row for row in calls if isinstance(row, dict)]
        test.assertEqual(1, len(correction_calls))  # Still pending after re-review cannot create a loop.
        test.assertEqual(corrections, correction_calls[0]['observation_corrections'])
        test.assertEqual(request.deadline_monotonic, correction_calls[0]['deadline_monotonic'])


def _verify_correction_scope(test, corrections):
    from contextlib import ExitStack
    from core import final_source_intents as intents
    from core.io import read_jsonl
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        job = Path(tmp)
        previous = [{'child': child, 'source_index': index, 'source_id': f'source_{index:02d}',
                     'source_sha256': 'a'*64, 'input_revision_id': 'evidence-1', 'visual_evidence': {}, 'status': 'success'}
                    for child, index in (('B1', 0), ('B1', 1), ('B2', 0))]
        downloads = [dict(row, status='ok', index=row['source_index'], raw_path=f"{row['child']}-{row['source_index']}.png") for row in previous]
        for name, value in {'ensure_run_scope': None, 'download_artifacts_current': (True, []),
            'read_download_manifest': {'rows': downloads}, 'row_in_scope': True, '_current_source_intent_reviews': {},
            'read_product_family': {'family': {'children': [{'asin': 'B1'}, {'asin': 'B2'}]}},
            'read_final_source_intents': previous, 'file_sha256': 'a'*64, '_validate_row': None}.items():
            stack.enter_context(patch.object(intents, name, return_value=value))
        ocr = stack.enter_context(patch.object(intents, 'ocr_evidence_for_image', side_effect=AssertionError('No observed text gap')))
        def observe(job, child, sources, **kwargs):
            test.assertEqual('B1', child['asin'])
            test.assertEqual({'source_00'}, set(kwargs['corrections']))
            test.assertTrue(all(row['ocr'] == [] for row in sources))
            return {row['source_id']: {'status': 'success', 'text_gaps': [], **({'planning_correction': corrections['B1']['source_00']}
                    if row['source_id'] == 'source_00' else {})} for row in sources}
        remote = stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=observe))
        stack.enter_context(patch.object(intents, '_prepare_source', side_effect=lambda job, plugin, row, evidence, child:
            dict(row, status='success', visual_evidence=evidence['visual_evidence'])))
        stack.enter_context(patch.object(intents, '_finalize_child', side_effect=lambda rows: rows))
        result = intents.build_final_source_intents(job_dir=job, plugin=object(), observation_corrections=corrections)
        test.assertEqual(1, remote.call_count)
        test.assertEqual(['B1'], result['corrected_children'])
        written = read_jsonl(job / 'reports' / intents.FINAL_SOURCE_INTENT_ARTIFACT)
        test.assertEqual(previous[-1], next(row for row in written if row['child'] == 'B2'))
        previous[0]['visual_evidence'] = written[0]['visual_evidence']
        intents.build_final_source_intents(job_dir=job, plugin=object(), observation_corrections=corrections)
        test.assertEqual(1, remote.call_count)
        ocr.assert_not_called()


def _verify_bound_artifact_repair(test):
    """Run real classify/kit/task/prompt writers with only outside services substituted."""
    from contextlib import ExitStack
    from core import production, final_source_intents as intents, visual_design_kit as design
    from core.io import write_json, file_sha256
    from core.image_tasks import read_image_tasks
    from tests.test_image_branch_v1 import (
        ImageBranchCurrentBehaviorTests, _Plugin, _family, _scope, _planner_payload, _fixture_observation, _fixture_reviews,
    )
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        job = Path(tmp)
        rows, _ = ImageBranchCurrentBehaviorTests()._source_fixture(job)
        for module, fields in ((intents, {'ensure_run_scope': None, 'download_artifacts_current': (True, []),
                'read_download_manifest': {'rows': rows}, 'read_product_family': _family(), 'row_in_scope': True}),
                (design, {'read_product_family': _family(), 'read_run_scope': _scope(), 'load_job': {}, 'load_env': {},
                          'gemini_scope_identity': [{'provider': 'fixture', 'model': 'fixture'}]})):
            for key, value in fields.items():
                stack.enter_context(patch.object(module, key, return_value=value))
        stack.enter_context(patch('core.run_scope.read_run_scope', return_value=_scope()))
        stack.enter_context(patch('core.image_tasks.read_product_family', return_value=_family()))
        stack.enter_context(patch('core.image_tasks.read_run_scope', return_value=_scope()))
        stack.enter_context(patch.object(production, 'assert_family_matches_plugin'))
        ocr = stack.enter_context(patch.object(intents, 'ocr_evidence_for_image', side_effect=AssertionError('No observed text gap')))
        corrected = False
        observations = []
        def observe(job, child, sources, **kwargs):
            nonlocal corrected
            result = _fixture_observation(job, child, sources)
            if not corrected and not kwargs.get('corrections'):
                result['source_02']['objects'][0].update(sale_membership='unknown', membership_evidence=[])
            if kwargs.get('corrections'):
                test.assertEqual({'source_02'}, set(kwargs['corrections']))
                corrected = True
                observations.append(kwargs['corrections'])
                result['source_02'].update(planning_correction=kwargs['corrections']['source_02']['planning_correction'],
                    correction_revision='')
                result['source_02']['product_features'][0]['physical_facts'].append('The supported shelf joint is visible')
            return result
        stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=observe))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        before = intents.read_final_source_intents(job, plugin=_Plugin())
        raw = _planner_payload(before)
        plans = []
        def planner(prompt, paths, **kwargs):
            plans.append(prompt)
            if kwargs.get('attempt_observer'):
                kwargs['attempt_observer']({'provider': 'fixture', 'model': 'fixture', 'attempt': 1, 'status': 'success', 'elapsed_ms': 1})
            test.assertFalse(prompt.startswith('Repair the listed'))
            return json.dumps(raw)
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=planner))
        def review(requests, **kwargs):
            result = _fixture_reviews(requests, **kwargs)
            for request in requests:
                if not corrected and request.get('kind') == 'design_binding' and request['source_id'] == 'source_02':
                    result[request['key']]['findings'].append({'operation': 'source_product:source_02',
                        'status': 'contradiction', 'reason': 'The visible shelf joint is missing from product evidence'})
            path = Path(next(iter(result.values()))['response_path'])
            write_json(path, {'reviews': [{**{key: row[key] for key in ('key', 'status', 'reason')},
                'findings': [{key: finding[key] for key in ('operation', 'status', 'reason')} for finding in row['findings']]}
                for row in result.values()]})
            for row in result.values():
                row['response_sha256'] = file_sha256(path)
                for finding in row['findings']:
                    finding.update({key: row[key] for key in ('policy', 'response_path', 'response_sha256')})
            return result
        stack.enter_context(patch.object(design, 'review_planning_bindings', side_effect=review))
        request = production.JobRunRequest(job_dir=job, plugin=_Plugin(), workers=1, deadline_monotonic=time.monotonic()+20)
        result = production._run_stage('brief', request=request)
        test.assertEqual([], result['failures'])
        test.assertEqual(1, len(observations))
        test.assertEqual(1, len(plans))  # Corrected product evidence reuses the still-valid design.
        kit = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
        test.assertEqual(raw['family_art_direction'], kit['family_art_direction'])
        test.assertTrue(all(row['status'] == 'ready' for row in kit['image_briefs']))
        after = intents.read_final_source_intents(job, plugin=_Plugin())
        test.assertEqual([row for row in before if row['source_index'] != 2], [row for row in after if row['source_index'] != 2])
        expected_roles = {spec['role'] for spec in task_specs({}, kit['source_references'], inventory=initial_output_inventory(kit['source_references']), include_optional=True)}
        test.assertEqual(expected_roles, {row['role'] for row in read_image_tasks(job, category_id=_Plugin.category_id)['tasks']})
        production._run_stage('brief', request=request)
        test.assertEqual(1, len(observations))
        test.assertEqual(1, len(plans))
        ocr.assert_not_called()
        from core.vision_errors import VisionRequestError
        def not_submitted(*args, **kwargs):
            for count in (1, 0):
                kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': count})
            raise VisionRequestError('visual_planning', 'queue_unavailable', 'offline queue full', metadata={'physical_request_count': 0})
        def submitted_timeout(*args, **kwargs):
            kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
            raise TimeoutError('Submitted request outcome unavailable')
        with patch.object(design, '_read_previous', return_value={}):
            with patch.object(design, 'gemini_stream_generate', side_effect=not_submitted) as queued:
                for _ in range(3):
                    design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
                test.assertEqual(3, queued.call_count)
            budgets = list((job / 'reports/visual_design_kit_traces').glob('*/*/attempt_budget.json'))
            test.assertTrue(budgets)
            test.assertTrue(all(json.loads(path.read_text()).get('plan', 0) == 0 for path in budgets))
            with patch.object(design, 'gemini_stream_generate', side_effect=submitted_timeout) as paid:
                for index in range(5):
                    exhausted = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
                    if index >= 3:
                        test.assertEqual('blocked', exhausted['failures'][0]['task_status'])
                test.assertEqual(4, paid.call_count)
                test.assertEqual('blocked', exhausted['failures'][0]['task_status'])


def verify_output_capacity_and_raw_trace(test):
    from core import vision_gemini_client as client
    from core.visual_semantics import observe_child_sources, _attempt_trace
    from contextlib import ExitStack
    calls = []
    endpoints = [{'name': name, 'model': 'offline', 'protocol': 'openai', 'api_key': 'fixture',
                  'base_url': 'https://' + name + '.invalid/v1', 'max_output_tokens': 8192} for name in ('primary', 'reserve')]
    limited = json.dumps({'choices': [{'message': {'content': '{"sources": ['}, 'finish_reason': 'length'}]})
    def post(config, url, payload, **kwargs):
        calls.append((config['name'], config['max_output_tokens']))
        return limited
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        for name, value in {'gemini_clients': endpoints, '_record_vision_model_event': None,
                            'provider_run_circuit_open': False, 'model_provider_cooldown_active': False,
                            'admit_provider_probe': True}.items():
            stack.enter_context(patch.object(client, name, return_value=value))
        stack.enter_context(patch.object(client, 'ordered_gemini_clients', side_effect=lambda rows, *a, **kw: rows))
        stack.enter_context(patch.object(client, '_post_vision_request', side_effect=post))
        job = Path(tmp)
        sources = [{'source_id': 'source_00', 'sha256': 'a'*64, 'ocr': [], 'path': job/'source.png'}]
        result = observe_child_sources(job, {'asin': 'B_CAP'}, sources)
        test.assertEqual([('primary', 8192), ('reserve', 8192)], calls)
        test.assertEqual('output_limit', result['source_00']['request_failure']['kind'])
        observe_child_sources(job, {'asin': 'B_CAP'}, sources)
        test.assertEqual(2, len(calls))  # Same capped inputs are not resubmitted on resume.
        endpoints[1]['max_output_tokens'] = 16384
        observe_child_sources(job, {'asin': 'B_CAP'}, sources)
        test.assertEqual(('reserve', 16384), calls[-1])
        test.assertEqual(3, len(calls))

        from core.visual_design_kit import _finish_image_briefs
        source = _source(role='scene')
        raw = _plan([source])
        calls.clear()
        review_dir = job / 'review'
        review_dir.mkdir()
        with patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
            ordinary = _finish_image_briefs(raw, output_inventory=initial_output_inventory([source]), job=job, child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[], trace_dir=review_dir, deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual('ready', _brief(ordinary, 'scene')['status'])
        test.assertEqual([], calls)
        source['observation']['objects'] = _source(disputed=True)['observation']['objects']
        from PIL import Image
        original = job / 'source.png'
        with Image.new('RGB', (32, 32), 'white') as pixels:
            pixels.save(original)
        from core.io import file_sha256
        source.update(source_path='source.png', source_sha256=file_sha256(original))
        for _ in range(3):
            _finish_image_briefs(raw, output_inventory=initial_output_inventory([source]), job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[original],
                source_originals=[original], trace_dir=review_dir,
                deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual([('primary', 8192), ('reserve', 16384)], calls)
        test.assertEqual(2, json.loads((review_dir/'attempt_budget.json').read_text())['review'])
        review_request = json.loads((review_dir/'initial/planning_review_request.txt').read_text().split('\n', 1)[1])
        test.assertEqual(['source_00'], [row['source_id'] for row in review_request['source_views']])
        test.assertTrue(all([review_request['execution_catalog'][ref['reference_id']]['source_id'] for ref in row['attachments']] == ['source_00']
                         for row in review_request['execution_inputs']))
        test.assertTrue(all('sold_membership:source_00' in row['physical_operations']
                            for row in review_request['bindings']))
        calls.clear()
        source['observation']['objects'] = []
        _brief(raw, 'scene')['image_direction']['environment_mode'] = None
        repair_dir = job / 'repair'
        repair_dir.mkdir()
        with patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
            for _ in range(3):
                pending = _finish_image_briefs(raw, output_inventory=initial_output_inventory([source]), job=job, child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                    source_originals=[], trace_dir=repair_dir, deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual([('primary', 8192), ('reserve', 16384)], calls)
        test.assertEqual('pending', _brief(pending, 'scene')['status'])
        repair_events = json.loads((repair_dir/'brief_repair_attempts.json').read_text())
        test.assertEqual(2, len(repair_events))
        test.assertTrue(all((repair_dir/row['raw_response_path']).is_file() for row in repair_events))

        body = '{"choices": [{"message": {"content": "incomplete-envelope'
        text, _, candidates, error = client._select_response_candidate(client._parse_openai_chat_candidates(body),
            lambda value: True, response_body=body)
        events, record = _attempt_trace(job/'raw_attempts.json')
        client._emit_attempt(record, request_id='offline', client={'name': 'fixture'}, model='offline', protocol='openai',
            attempt=1, status=client._response_failure_kind(body, error), started=time.monotonic(),
            response_text=text, response_body=body, response_candidates=candidates, error=error)
        test.assertEqual('json_syntax', events[0]['status'])
        test.assertEqual(0, events[0]['response_char_count'])
        test.assertEqual(body, (job/events[0]['raw_response_path']).read_text())

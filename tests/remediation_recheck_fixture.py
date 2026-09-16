"""Boundary counterexamples exercised by the existing production test cases."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from core.visual_design_kit_compiler import (
    compile_visual_design_kit_response, design_binding_request, validate_compiled_visual_design_kit,
)
from tests.current_image_contract_fixture import (
    current_art_direction, current_image_direction, current_physical_view,
    supported_design_reviews, supported_review_results,
)


def _source(key='source_00'):
    return {'source_id': key, 'source_sha256': 'a' * 64, 'input_revision_id': 'evidence-1',
            'role': 'func', 'measurements': [], 'claims': [{'evidence_id': 'shelf', 'text': 'Adjustable Shelf'}],
            'observation': {'physical_views': [current_physical_view()], 'objects': []}}


def _draft(key='source_00'):
    return {'source_id': key, 'image_direction': current_image_direction(source_id=key),
            'display_copy': {'title': None, 'labels': [{'evidence_ids': ['shelf'], 'text': 'Adjustable Shelf'}]}}


def verify_review_projection(test):
    source, draft = _source(), _draft()
    placement = {'text_ref': 'label:0', 'target_region': [0, 0, 1, .1], 'backing': 'none'}
    draft['image_direction']['text_placement'] = [dict(placement, text_ref=key)
                                               for key in ('title', 'measurements', 'label:0')]
    raw = {'family_art_direction': current_art_direction(), 'source_briefs': [draft]}
    reviews = supported_design_reviews(raw, [source])
    compiled = compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=reviews)
    test.assertEqual('ready', compiled['source_briefs'][0]['status'])
    test.assertEqual([placement], compiled['source_briefs'][0]['image_direction']['text_placement'])
    test.assertEqual(3, len(draft['image_direction']['text_placement']))
    for field, value in (('backing', 'local'), ('target_region', [0, .2, 1, .3])):
        changed = deepcopy(compiled)
        changed['source_briefs'][0]['image_direction']['text_placement'][0][field] = value
        with test.assertRaisesRegex(ValueError, 'no longer matches'):
            validate_compiled_visual_design_kit(changed, source_manifest=[source])
    source['measurements'] = [{'view_id': 'view_01', 'source_region': dict(left=.1, top=.05, right=.3, bottom=.1)}]
    request = design_binding_request(draft, raw['family_art_direction'], source=source)
    test.assertEqual([source['measurements'][0]['source_region']], request['selected_evidence'][0]['required_annotation_regions'])
    test.assertNotEqual(next(iter(reviews)), request['key'])
    from core.visual_design_kit import _finish_source_briefs
    for field, invalid in (('text_placement', ['not a placement']),
                           ('text_placement', [{'target_region': [0, 0, 1, .1]}]), ('scene_objects', None)):
        malformed = deepcopy(raw)
        malformed['source_briefs'][0]['image_direction'][field] = invalid
        sibling = dict(_source('source_01'), role='scene', claims=[])
        malformed['source_briefs'].append({'source_id': 'source_01', 'image_direction': current_image_direction(source_id='source_01')})
        with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate', return_value=json.dumps({'source_briefs': raw['source_briefs']})), patch(
                'core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
            result = _finish_source_briefs(malformed, source_manifest=[_source(), sibling], category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual(['ready', 'ready'], [row['status'] for row in result['source_briefs']])


def verify_shared_repair(test):
    from core.visual_design_kit import _finish_source_briefs
    sources = [_source(), _source('source_01')]
    raw = {'family_art_direction': current_art_direction(), 'source_briefs': [_draft(), _draft('source_01')]}
    raw['family_art_direction']['graphic_direction']['component_style'] = 'Use pill backings behind all labels'
    for brief in raw['source_briefs']:
        brief['image_direction']['text_placement'] = [
            {'text_ref': 'label:0', 'target_region': [0, 0, 1, .1], 'backing': 'none'}]
    calls = []
    def review(requests, **kwargs):
        calls.append(requests)
        results = supported_review_results(requests)
        if len(calls) == 1:
            item = results[requests[0]['key']]
            item['findings'].append({'operation': 'shared_prose:graphic_direction.component_style',
                'status': 'contradiction', 'reason': 'Shared pill instruction contradicts role backing none'})
        return results
    def repair(prompt, paths, **kwargs):
        test.assertIn('"allowed_shared_fields": ["graphic_direction.component_style"]', prompt)
        return json.dumps({'source_briefs': [raw['source_briefs'][0]],
            'shared_prose': {'graphic_direction.component_style': 'Fine uniform strokes and sparse outline icons'}})
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review), patch(
            'core.visual_design_kit.gemini_stream_generate', side_effect=repair) as remote:
        result = _finish_source_briefs(raw, source_manifest=sources, category_id='bed_frame', source_paths=[],
            source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
    test.assertEqual(1, remote.call_count)
    test.assertEqual(['ready', 'ready'], [row['status'] for row in result['source_briefs']])
    test.assertEqual(2, len(calls[1]))  # Also rebind the previously ready sibling.
    test.assertTrue({row['key'] for row in calls[0]}.isdisjoint({row['key'] for row in calls[1]}))
    for key in ('palette_direction', 'typography_direction'):
        test.assertEqual(raw['family_art_direction'][key], result['family_art_direction'][key])
    for key, value in raw['family_art_direction']['graphic_direction'].items():
        if key != 'component_style':
            test.assertEqual(value, result['family_art_direction']['graphic_direction'][key])
    calls.clear()
    unauthorized = {'source_briefs': [raw['source_briefs'][0]], 'shared_prose': {'graphic_direction.text_color': '#000000'}}
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review), patch(
            'core.visual_design_kit.gemini_stream_generate', return_value=json.dumps(unauthorized)):
        result = _finish_source_briefs(raw, source_manifest=sources, category_id='bed_frame', source_paths=[],
            source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertIn('change shared design assignments', (Path(tmp) / 'brief_repair_error.txt').read_text())
    test.assertEqual(raw['family_art_direction'], result['family_art_direction'])


def verify_observation_feedback(test):
    from core.visual_design_kit import observation_corrections
    source, draft = _source(), _draft()
    raw = {'family_art_direction': current_art_direction(), 'source_briefs': [draft]}
    reviews = supported_design_reviews(raw, [source])
    review = next(iter(reviews.values()))
    review['findings'] = [{'operation': 'source_product:source_00/view_01', 'status': 'contradiction',
                          'reason': 'A sold frame support is clipped in the evidence crop'}]
    compiled = compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=reviews)
    kit = {'children': {'B1': {**compiled, 'source_references': [source], 'input_revision_id': 'kit-1'}}}
    corrections = observation_corrections(kit)
    test.assertEqual({'B1'}, set(corrections))
    test.assertEqual({'source_00'}, set(corrections['B1']))
    test.assertEqual(source['source_sha256'], corrections['B1']['source_00']['source_sha256'])
    test.assertEqual(review['key'], corrections['B1']['source_00']['findings'][0]['review_key'])
    changed = deepcopy(kit)
    changed['children']['B1']['source_references'][0]['input_revision_id'] = 'changed'
    test.assertEqual({}, observation_corrections(changed))
    _verify_observation_cache(test, corrections['B1']['source_00'])
    _verify_feedback_stage(test, kit, corrections)
    _verify_correction_scope(test, corrections)
    _verify_bound_artifact_repair(test)


def _verify_observation_cache(test, finding):
    from core.visual_semantics import observe_child_sources
    from core.io import read_json
    valid = {'source_id': 'source_00', 'role_guess': 'scene', 'view_coverage': 'complete',
        'has_dimension_lines': False, 'has_callouts_or_panels': False, 'visible_numbers_or_units': [],
        'confidence': .95, 'evidence': [], 'measurements': [], 'text_observations': [],
        'objects': [{'object_id': 'frame', 'kind': 'frame', 'state': 'visible', 'sale_membership': 'unknown',
                     'visibility': 'visible', 'relations': []}], 'physical_views': [current_physical_view()],
        'variant_identity': {'status': 'unknown', 'observed_color': '', 'reason': 'Not identifiable', 'conflicts': []}}
    sibling = dict(valid, source_id='source_01')
    with TemporaryDirectory() as tmp:
        job = Path(tmp)
        sources = [{'source_id': row['source_id'], 'sha256': 'a'*64, 'ocr': [], 'path': job / (row['source_id']+'.png')}
                   for row in (valid, sibling)]
        injected = dict(valid, planning_correction={'source_revision': 'model-invented-control'}, correction_revision='model-claim')
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [injected, sibling]})):
            initial = observe_child_sources(job, {'asin': 'B1'}, sources)
            test.assertNotIn('planning_correction', initial['source_00'])
            test.assertEqual('', initial['source_00']['correction_revision'])
        correction = {'source_00': {'revision': '', 'planning_correction': finding, 'reason': finding}}
        corrected = deepcopy(valid)
        corrected['objects'].append({'object_id': 'bedding', 'kind': 'bedding ensemble', 'state': 'covers support',
            'sale_membership': 'staging', 'visibility': 'visible', 'relations': [{'predicate': 'occludes', 'target_id': 'frame'}]})
        with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [corrected]})) as remote:
            result = observe_child_sources(job, {'asin': 'B1'}, sources, corrections=correction)
            test.assertEqual([sources[0]['path']], remote.call_args.args[1])
            test.assertEqual('bedding', result['source_00']['objects'][-1]['object_id'])
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
            'read_final_source_intents': previous, '_collect_evidence_by_sha': {'a'*64: {}}, '_validate_row': None}.items():
            stack.enter_context(patch.object(intents, name, return_value=value))
        def observe(job, child, sources, **kwargs):
            test.assertEqual('B1', child['asin'])
            test.assertEqual({'source_00'}, set(kwargs['corrections']))
            return {row['source_id']: {'status': 'success', **({'planning_correction': corrections['B1']['source_00']}
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
        rows, evidence = ImageBranchCurrentBehaviorTests()._source_fixture(job)
        for module, fields in ((intents, {'ensure_run_scope': None, 'download_artifacts_current': (True, []),
                'read_download_manifest': {'rows': rows}, 'read_product_family': _family(), 'row_in_scope': True,
                '_collect_evidence_by_sha': evidence}),
                (design, {'read_product_family': _family(), 'read_run_scope': _scope(), 'load_job': {}, 'load_env': {},
                          'gemini_scope_identity': [{'provider': 'fixture', 'model': 'fixture'}]})):
            for key, value in fields.items():
                stack.enter_context(patch.object(module, key, return_value=value))
        stack.enter_context(patch('core.run_scope.read_run_scope', return_value=_scope()))
        stack.enter_context(patch('core.image_tasks.read_product_family', return_value=_family()))
        stack.enter_context(patch('core.image_tasks.read_run_scope', return_value=_scope()))
        stack.enter_context(patch.object(production, 'assert_family_matches_plugin'))
        corrected = False
        observations = []
        def observe(job, child, sources, **kwargs):
            nonlocal corrected
            result = _fixture_observation(job, child, sources)
            if kwargs.get('corrections'):
                test.assertEqual({'source_02'}, set(kwargs['corrections']))
                corrected = True
                observations.append(kwargs['corrections'])
                result['source_02'].update(planning_correction=kwargs['corrections']['source_02']['planning_correction'],
                    correction_revision='')
                result['source_02']['physical_views'][0]['evidence'][0]['physical_facts'].append('The supported shelf joint is visible')
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
            if prompt.startswith('Repair the listed'):
                brief = deepcopy(raw['source_briefs'][2])
                brief['image_direction']['scene_objects'] = ['bath.towels']
                return json.dumps({'source_briefs': [brief]})
            return json.dumps(raw)
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=planner))
        def review(requests, **kwargs):
            result = _fixture_reviews(requests, **kwargs)
            for request in requests:
                if not corrected and request.get('kind') == 'design_binding' and request['source_id'] == 'source_02':
                    result[request['key']]['findings'].append({'operation': 'source_product:source_02/view_01',
                        'status': 'contradiction', 'reason': 'The visible shelf joint is missing from product evidence'})
            path = Path(next(iter(result.values()))['response_path'])
            write_json(path, {'reviews': [{key: row[key] for key in ('key', 'status', 'reason', 'findings')}
                                         for row in result.values()]})
            return {key: dict(row, response_sha256=file_sha256(path)) for key, row in result.items()}
        stack.enter_context(patch.object(design, 'review_planning_bindings', side_effect=review))
        request = production.JobRunRequest(job_dir=job, plugin=_Plugin(), workers=1, deadline_monotonic=time.monotonic()+20)
        result = production._run_stage('brief', request=request)
        test.assertEqual([], result['failures'])
        test.assertEqual(1, len(observations))
        test.assertEqual(1, len(plans))  # Corrected product evidence reuses the still-valid design.
        kit = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
        test.assertEqual(raw['family_art_direction'], kit['family_art_direction'])
        test.assertTrue(all(row['status'] == 'ready' for row in kit['source_briefs']))
        after = intents.read_final_source_intents(job, plugin=_Plugin())
        test.assertEqual([row for row in before if row['source_index'] != 2], [row for row in after if row['source_index'] != 2])
        test.assertEqual(4, len(read_image_tasks(job, category_id=_Plugin.category_id)['tasks']))
        production._run_stage('brief', request=request)
        test.assertEqual(1, len(observations))
        test.assertEqual(1, len(plans))
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

        from core.visual_design_kit import _finish_source_briefs
        source = dict(_source(), role='scene', claims=[])
        draft = {'source_id': 'source_00', 'image_direction': current_image_direction()}
        raw = {'family_art_direction': current_art_direction(), 'source_briefs': [draft]}
        calls.clear()
        review_dir = job / 'review'
        review_dir.mkdir()
        for _ in range(3):
            _finish_source_briefs(raw, source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[job/'unused.png'], trace_dir=review_dir,
                deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual([('primary', 8192), ('reserve', 16384)], calls)
        test.assertEqual(2, json.loads((review_dir/'attempt_budget.json').read_text())['review'])
        review_request = json.loads((review_dir/'initial/planning_review_request.txt').read_text().split('\n', 1)[1].split('\nPalette', 1)[0])
        test.assertEqual([], review_request['source_views'])
        test.assertEqual([], review_request['actual_crop_attachments'])
        calls.clear()
        draft['image_direction']['scene_objects'] = None
        repair_dir = job / 'repair'
        repair_dir.mkdir()
        for _ in range(3):
            pending = _finish_source_briefs(raw, source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[], trace_dir=repair_dir, deadline_monotonic=time.monotonic()+10, cached=None)
        test.assertEqual([('primary', 8192), ('reserve', 16384)], calls)
        test.assertEqual('pending', pending['source_briefs'][0]['status'])
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

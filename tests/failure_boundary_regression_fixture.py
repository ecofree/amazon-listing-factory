"""Current failure-chain tests, invoked by the existing production suite."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from core import image_tasks
from core.final_source_intents import _observed_measurements, _measurement_rows
from core.image_prompt_compiler import build_image_prompts, read_image_prompts, compile_task_prompt
from core.image_task_inputs import build_renderable_text_contract
from core.io import write_jsonl, write_json, file_sha256
from core.plugin import load_plugin
from core.status import record_task_failures, task_record, input_revision_id
from core.visual_design_kit import _finish_image_briefs, _planner_trace_current
from core.visual_design_kit_compiler import compile_visual_design_kit_response, design_binding_request
from core.visual_semantics import _validate_observations, _planning_review_rows, observe_child_sources, CLAIM_REVIEW_POLICY
from core.vision_errors import VisionRequestError
from tests.test_status_revision_contract import _job
from tests.current_image_contract_fixture import (
    current_image_task, current_art_direction, current_image_direction, current_physical_view,
    current_observed_measurement, supported_review_results,
)


def verify_failure_boundaries(test):
    _task_roundtrip(test)
    _measurement_roundtrip(test)
    _review_recovery(test)


def _task_roundtrip(test):
    plugin = load_plugin('bathroom_cabinet')
    ready = current_image_task('main')
    unresolved = current_image_task('func', blocked_reason='Review has not completed', retryable=True)
    source_pending = current_image_task('size', blocked_reason='A required measurement needs evidence',
                                        reason_code='source_observation_unresolved')
    source_pending['formation_failure_owner'] = 'observation'
    source_pending['task_fingerprint'] = image_tasks._task_fingerprint(source_pending)
    source_pending['input_revision_id'] = source_pending['task_fingerprint']
    tasks = [ready, unresolved, source_pending]
    for role in ('main', 'scene', 'func', 'size'):
        task = current_image_task(role)
        persisted = json.loads(json.dumps(task, sort_keys=True))
        image_tasks.validate_image_task(persisted)
        test.assertEqual(compile_task_prompt(task=task), compile_task_prompt(task=persisted))
    with TemporaryDirectory() as tmp, patch('core.image_tasks._expected_rows', return_value=tasks), patch(
            'core.image_tasks.read_run_scope', return_value={'selected_children': ['B1']}), patch(
            'core.image_tasks.planning_source_intents', return_value=[]):
        _job(Path(tmp))
        fresh = image_tasks.build_image_tasks(job_dir=tmp, plugin=plugin)
        reused = image_tasks.read_image_tasks(tmp)
        test.assertEqual(fresh['failures'], reused['failures'])
        compiled = build_image_prompts(job_dir=tmp, plugin=plugin)
        test.assertEqual(['ready', 'blocked', 'blocked'], [row['status'] for row in compiled['prompts']])
        test.assertEqual(compiled['prompts'], read_image_prompts(tmp)['prompts'])
        test.assertEqual([], compiled['failures'])
        for run, failures in (('fresh', fresh['failures']), ('resume', reused['failures'])):
            record_task_failures(tmp, owner_stage='brief', attempt_id=run, failures=failures)
            for failure in failures:
                state = task_record(tmp, failure['task']['logical_task_id'])
                test.assertEqual(failure['failure_owner'], state['failure_owner'])
                test.assertEqual(failure['task_status'], state['status'])
        invalid = deepcopy(unresolved)
        invalid['obsolete_failure_flag'] = True
        write_jsonl(Path(tmp)/'reports'/image_tasks.IMAGE_TASK_ARTIFACT, [ready, invalid])
        with test.assertRaisesRegex(image_tasks.ImageTaskError, 'obsolete_failure_flag'):
            image_tasks.read_image_tasks(tmp)


def _observation():
    measurements = []
    for i, text in enumerate(('36.5 in', '79 in', '58 in', '12 in', '75 in', '54 in', '600 lbs')):
        row = current_observed_measurement(text, 'bed frame', 'capacity' if i == 6 else 'length',
                                          key=f'm_{i}', kind='capacity' if i == 6 else 'dimension')
        row['region'] = dict(left=.1+i*.1, top=.05, right=.15+i*.1, bottom=.1)
        measurements.append(row)
    thickness = current_observed_measurement('<= 6 in', 'recommended mattress', 'thickness',
                                             key='thickness', evidence_type='text_spec')
    thickness['region'] = dict(left=.765, top=.908, right=.818, bottom=.938)
    measurements.append(thickness)
    return dict(source_id='source_00', role_guess='size', has_dimension_lines=True,
        has_callouts_or_panels=True, visible_numbers_or_units=[], evidence_gaps=[], text_gaps=[], confidence=.99,
        reference_views=[dict(view_id='view_01', purposes=['appearance', 'measurement'])],
        physical_views=[current_physical_view()], evidence=['Dimension diagram'],
        variant_identity=dict(status='consistent', observed_color='White', reason='White frame', conflicts=[]),
        text_observations=[dict(kind='measurement', text=row['text']) for row in measurements], measurements=measurements,
        objects=[dict(object_id='frame', kind='bed frame', sale_membership='product',
                      membership_evidence=[dict(fact_id='product.title', quote='White wood bed frame')],
                      visibility='visible', state='Assembled frame, no mattress')])


def _measurement_roundtrip(test):
    facts = {'product.title': 'White wood bed frame'}
    raw = _observation()
    observed = _validate_observations([raw], ['source_00'], facts)['source_00']
    test.assertEqual('success', observed['status'])
    test.assertEqual([], observed['measurement_issues'])
    test.assertEqual(8, len(observed['measurements']))
    source = dict(source_id='source_00', source_index=0, role='size', source_sha256='a'*64,
                  input_revision_id='source-current', observation=observed, claims=[],
                  measurements=_measurement_rows(_observed_measurements(observed), {}))
    authority = image_tasks._measurement_authority('size', source, [(source, observed['physical_views'][0])])
    test.assertEqual('text_spec', authority['measurement_groups'][-1]['evidence_type'])
    test.assertIsNone(authority['measurement_groups'][-1]['source_endpoints'])
    test.assertIn('<=', authority['render_text'][-1])
    task = current_image_task('size')
    task['measurement_authority'] = authority
    task['generation_references'][0]['original_region'] = dict(left=0, top=0, right=1, bottom=1)
    task['renderable_text_contract'] = build_renderable_text_contract('size', authority, display_copy=task['display_copy_contract'])
    prompt = compile_task_prompt(task=task)
    test.assertIn('text_spec binds a written property', prompt)
    test.assertIn('<= 6 in', prompt)
    test.assertNotIn('Null endpoints identify capacity/weight', prompt)

    malformed = deepcopy(raw)
    malformed['measurements'][-1]['evidence_type'] = 'dimension_line'
    partial = _validate_observations([malformed], ['source_00'], facts)['source_00']
    test.assertEqual('success', partial['status'])
    test.assertEqual(7, len(partial['measurements']))
    test.assertEqual(1, len(partial['measurement_issues']))
    test.assertEqual(partial, _validate_observations([partial], ['source_00'], facts)['source_00'])
    source.update(observation=partial, measurements=_measurement_rows(_observed_measurements(partial), {}))
    planned = dict(family_art_direction=current_art_direction(), image_briefs=[
        dict(role='main', source_id='source_00', image_direction=current_image_direction()),
        dict(role='size', source_id='source_00', image_direction=current_image_direction(), display_copy=dict(title=None, labels=[]))])
    compiled = compile_visual_design_kit_response(planned, source_manifest=[source])
    by_role = {row['role']: row for row in compiled['image_briefs']}
    test.assertEqual('ready', by_role['main']['status'])
    test.assertEqual('observation', by_role['size']['failure_owner'])
    duplicate = deepcopy(raw)
    duplicate['measurements'].append(deepcopy(duplicate['measurements'][0]))
    test.assertEqual('failed', _validate_observations([duplicate], ['source_00'], facts)['source_00']['status'])
    calls = []
    def observe(*args, **kwargs):
        calls.append(args)
        kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
        if len(calls) == 1:
            return json.dumps({'sources': [malformed]})
        raise TimeoutError('offline unresolved observation')
    with TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate', side_effect=observe):
        for _ in range(3):
            resumed = observe_child_sources(Path(tmp), {'asin': 'B1', 'title': facts['product.title']},
                [dict(source_id='source_00', sha256='a'*64, ocr=[], path=Path(tmp)/'source.png')])['source_00']
            test.assertEqual(7, len(resumed['measurements']))
            test.assertEqual(1, len(resumed['measurement_issues']))
        test.assertEqual(4, len(calls))


def _review_recovery(test):
    source = dict(source_id='source_00', source_index=0, role='func', source_sha256='a'*64,
        input_revision_id='source-current', claims=[], measurements=[], observation=dict(
            physical_views=[current_physical_view(), current_physical_view('detail', feature='joint')],
            reference_views=[dict(view_id='view_01', purposes=['appearance'])], text_gaps=[], evidence_gaps=[],
            objects=[dict(object_id='frame', kind='frame', visibility='visible', sale_membership='product', state='Frame assembled')]))
    direction = current_image_direction()
    direction['evidence_usage'].append(dict(source_id='source_00', view_id='detail', usage='integrated', covered_by=['source_00/view_01']))
    raw = dict(family_art_direction=current_art_direction(), image_briefs=[
        dict(role='main', source_id='source_00', image_direction=current_image_direction()),
        dict(role='func', source_id='source_00', image_direction=direction, display_copy=dict(title=None, labels=[]))])
    args = dict(source_manifest=[source], category_id='bed_frame', child='B1', source_paths=[], source_originals=[])
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings') as reviewer, patch(
            'core.visual_design_kit.gemini_stream_generate') as redesign:
        _finish_image_briefs(raw, **args, job=Path(tmp), trace_dir=Path(tmp), cached=None,
                              deadline_monotonic=time.monotonic()-1)
        reviewer.assert_not_called()
        redesign.assert_not_called()
        reviewer.side_effect = ValueError('internal invariant failure')
        with test.assertRaisesRegex(ValueError, 'internal invariant failure'):
            _finish_image_briefs(raw, **args, job=Path(tmp), trace_dir=Path(tmp), cached=None,
                                  deadline_monotonic=time.monotonic()+5)
    for error, expected in ((TimeoutError('offline timeout'), 2),
                           (VisionRequestError('visual_planning', 'rate_limit_failure', 'offline limited'), 2),
                           (VisionRequestError('visual_planning', 'auth_failure', 'offline denied'), 1)):
        with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate') as redesign:
            count = [0]
            def reviewer(requests, **kwargs):
                count[0] += 1
                kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
                if count[0] == 1:
                    raise error
                return supported_review_results(requests)
            with patch('core.visual_design_kit.review_planning_bindings', side_effect=reviewer):
                result = _finish_image_briefs(raw, **args, job=Path(tmp), trace_dir=Path(tmp), cached=None,
                                              deadline_monotonic=time.monotonic()+5)
            test.assertEqual(expected, count[0])
            roles = {row['role']: row for row in result['image_briefs']}
            test.assertEqual('ready', roles['main']['status'])
            test.assertEqual('ready' if expected == 2 else 'pending', roles['func']['status'])
            redesign.assert_not_called()

    calls = []
    def unsure(requests, **kwargs):
        calls.append(requests)
        kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
        results = supported_review_results(requests)
        for value in results.values():
            value['status'] = 'inconclusive'
            for finding in value['findings']:
                finding.update(status='inconclusive', resolution='retry_review')
        return results
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate') as redesign, patch(
            'core.visual_design_kit.review_planning_bindings', side_effect=unsure):
        result = None
        for _ in range(3):
            result = _finish_image_briefs(raw, **args, job=Path(tmp), trace_dir=Path(tmp), cached=result,
                                          deadline_monotonic=time.monotonic()+5)
        test.assertEqual(4, len(calls))
        test.assertEqual('review', next(row for row in result['image_briefs'] if row['role'] == 'func')['failure_owner'])
        redesign.assert_not_called()
    for target in ('Frame assembled with fresh bedding', 'Complete frame, bright new bedroom', 'Assembled frame'):
        main = deepcopy(raw['image_briefs'][0])
        main['image_direction']['presentation']['state'] = target
        test.assertEqual([], design_binding_request(main, raw['family_art_direction'], source=source)['physical_operations'])
    source['observation']['physical_views'][1]['extent'] = 'detail'
    detail_only_evidence = deepcopy(raw['image_briefs'][0])
    detail_only_evidence['image_direction']['evidence_usage'][0]['view_id'] = 'detail'
    test.assertIn('whole_product_transfer:main', design_binding_request(detail_only_evidence, raw['family_art_direction'], source=source)['physical_operations'])
    source['observation']['objects'][0]['sale_membership'] = 'unknown'
    requests = [design_binding_request(raw['image_briefs'][1], raw['family_art_direction'], source=source)]
    test.assertEqual(3, len(requests[0]['physical_operations']))
    first = supported_review_results(requests)[requests[0]['key']]
    first['reason'] = 'Only one operation evaluated'
    first['findings'].pop()
    checked, errors = _planning_review_rows([first], requests)
    test.assertEqual(2, len(checked[first['key']]['findings']))
    test.assertIn(first['key'], errors)
    seen = []
    def partial_review(items, **kwargs):
        seen.append(items)
        values = supported_review_results(items)
        for request in items:
            values[request['key']]['reason'] = 'Fixture evidence checked'
            if request['role_design']['role'] == 'func' and len(seen) == 1:
                values[request['key']] = deepcopy(first)
        records = [{key: value[key] for key in ('key', 'status', 'reason', 'findings')} for value in values.values()]
        path = kwargs['trace_dir']/'review.json'
        write_json(path, dict(reviews=records))
        values, _ = _planning_review_rows(records, items)
        provenance = dict(policy=CLAIM_REVIEW_POLICY, response_path=str(path), response_sha256=file_sha256(path))
        return {key: {**value, **provenance, 'findings': [{**finding, **provenance} for finding in value['findings']]}
                for key, value in values.items()}
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=partial_review), patch(
            'core.visual_design_kit.gemini_stream_generate') as redesign:
        completed = _finish_image_briefs(raw, **args, job=Path(tmp), trace_dir=Path(tmp), cached=None,
                                         deadline_monotonic=time.monotonic()+5)
        func = next(row for row in completed['image_briefs'] if row['role'] == 'func')
        test.assertEqual('ready', func['status'])
        test.assertEqual(3, len(func['design_review']['findings']))
        test.assertEqual(1, len(seen[1]))
        test.assertEqual(1, len(seen[1][0]['physical_operations']))
        redesign.assert_not_called()
        job = Path(tmp)
        for brief in completed['image_briefs']:
            review = brief['design_review']
            if not review:
                continue
            for evidence in [review, *review['findings']]:
                evidence['response_path'] = Path(evidence['response_path']).relative_to(job).as_posix()
        write_json(job/'prompt.json', raw)
        write_json(job/'planned.json', completed)
        saved = dict(completed, planner=dict(prompt_path='prompt.json', request_fingerprint=file_sha256(job/'prompt.json'),
            response_path='planned.json', response_fingerprint=input_revision_id(completed)))
        test.assertTrue(_planner_trace_current(job, saved))
        import shutil
        with TemporaryDirectory() as relocated:
            moved = Path(relocated)/'copy'
            shutil.copytree(job, moved)
            test.assertTrue(_planner_trace_current(moved, saved))
        old_proof = func['design_review']['findings'][0]['response_path']
        write_json(job/old_proof, dict(reviews=[]))
        test.assertFalse(_planner_trace_current(job, saved))

"""Current failure-chain tests, invoked by the existing production suite."""
from core.image_task_inputs import initial_output_inventory
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
    current_image_task, current_art_direction, current_image_direction, current_product_feature,
    current_observed_measurement, supported_review_results,
)


def verify_failure_boundaries(test):
    _task_roundtrip(test)
    _frozen_output_isolation(test)
    _output_measurements(test)
    _latest_repair(test)
    from tests.visual_recovery_regression_fixture import verify_visual_recovery
    verify_visual_recovery(test)


def _frozen_output_isolation(test):
    from tests.remediation_recheck_fixture import _source, _plan
    from core.image_task_inputs import task_specs
    sources = [_source('source_00', 'main'), _source('source_01', 'func'), _source('source_02', 'func')]
    inventory = initial_output_inventory(sources)
    test.assertEqual('source_00', next(row['source_id'] for row in inventory if row['role'] == 'scene'))
    plan = _plan(sources)
    baseline = compile_visual_design_kit_response(plan, source_manifest=sources, output_inventory=inventory)
    for path in (('environment_mode',), ('presentation', 'scope'), ('product_sources',),
                 ('presentation', 'components'), ('visual_goal',), ('design_transfer',)):
        for value in ([], {}, None, 7):
            if value == [] and path in {('presentation', 'components'), ('design_transfer',)}:
                continue
            changed = deepcopy(plan)
            target = next(row for row in changed['image_briefs'] if row['role'] == 'func')['image_direction']
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            actual = compile_visual_design_kit_response(changed, source_manifest=sources, output_inventory=inventory)
            test.assertEqual('pending', next(row['status'] for row in actual['image_briefs'] if row['role'] == 'func'))
            test.assertEqual([row for row in baseline['image_briefs'] if row['role'] != 'func'],
                             [row for row in actual['image_briefs'] if row['role'] != 'func'])
    for extra in ([{'role': 'unexpected', 'source_id': 'source_00'}], [deepcopy(plan['image_briefs'][2])], ['invalid row'], [{'role': ['func']} ]):
        changed = dict(plan, image_briefs=[*reversed(plan['image_briefs']), *extra])
        actual = compile_visual_design_kit_response(changed, source_manifest=sources, output_inventory=inventory)
        duplicated = extra[0].get('role') if isinstance(extra[0], dict) else None
        for expected, row in zip(baseline['image_briefs'], actual['image_briefs']):
            if row['role'] == duplicated:
                test.assertEqual('pending', row['status'])
                test.assertIn('Duplicate', row['error'])
            elif row['status'] == 'pending':
                test.assertEqual(expected['failure_owner'], row['failure_owner'])
                test.assertTrue(row['error'].startswith(expected['error']))
            else:
                test.assertEqual(expected, row)
    before = task_specs({}, sources, inventory=inventory, include_optional=True)
    sources[0]['role'] = 'func'
    sources.reverse()
    after = task_specs({}, sources, inventory=inventory, include_optional=True)
    test.assertEqual([(r['role'], (r['source'] or {}).get('source_id')) for r in before],
                     [(r['role'], (r['source'] or {}).get('source_id')) for r in after])
    alternate = task_specs({}, [r for r in sources if r['source_id'] != 'source_00'], inventory=inventory, include_optional=True)
    test.assertEqual([r['role'] for r in before], [r['role'] for r in alternate])
    test.assertEqual('source_01', alternate[0]['source']['source_id'])
    broken = dict(plan, image_briefs=[*plan['image_briefs'], deepcopy(plan['image_briefs'][2]), 'bad', {'role': []}])
    with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate',
            return_value=json.dumps({'image_briefs': [plan['image_briefs'][2]]})) as repair, patch(
            'core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
        result = _finish_image_briefs(broken, output_inventory=inventory, job=Path(tmp), child='B1', source_manifest=sources,
            category_id='bed_frame', source_paths=[], source_originals=[], trace_dir=Path(tmp),
            deadline_monotonic=time.monotonic()+5, cached=None)
        test.assertEqual(1, repair.call_count)
        test.assertEqual('ready', next(row['status'] for row in result['image_briefs'] if row['role'] == 'func'))


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


def _output_measurements(test):
    from core.image_task_inputs import measurement_authority
    from core.image_reference_context import resolve_edit_references, measurement_attachment
    from tests.test_visual_design_remediation import _evidence_source
    from tests.current_image_contract_fixture import current_measurement_rows
    from PIL import Image
    appearance = _evidence_source('main')
    dimensions = _evidence_source('size', source_id='source_02')
    dimensions['measurements'] = current_measurement_rows()
    func = dict(role='func', source_id='source_00', image_direction=current_image_direction(),
                display_copy={'title': None, 'labels': []})
    # A source can contain dimensions without obliging a nonnumeric feature image to repeat them.
    appearance['measurements'] = deepcopy(dimensions['measurements'])
    test.assertEqual('none', measurement_authority('func', func['image_direction'], [appearance, dimensions])['mode'])
    size = dict(role='size', source_id='source_02', image_direction=current_image_direction(measurement_ids=['source_02:width']),
                display_copy={'title': None, 'labels': []})
    raw = {'family_art_direction': current_art_direction(), 'image_briefs': [size]}
    compiled = compile_visual_design_kit_response(raw, source_manifest=[appearance, dimensions],
                output_inventory=initial_output_inventory([appearance, dimensions]))
    test.assertEqual('ready', next(r for r in compiled['image_briefs'] if r['role'] == 'size')['status'])
    with TemporaryDirectory() as tmp:
        job = Path(tmp)
        for i, source in enumerate((appearance, dimensions)):
            source['source_path'] = str(i) + '.png'
            with Image.new('RGB', (1200, 960), ('white', 'gray')[i]) as image:
                image.save(job / source['source_path'])
            source['source_sha256'] = file_sha256(job / source['source_path'])
        refs = resolve_edit_references(size, [appearance, dimensions], job=job, child='B1')
        test.assertEqual(['edit_base', 'measurement_evidence'], [r['kind'] for r in refs])
        group = measurement_authority('size', size['image_direction'], [appearance, dimensions])['measurement_groups'][0]
        test.assertEqual(2, measurement_attachment(group, refs))
        test.assertEqual('Cabinet', group['measured_part'])
        test.assertEqual('17 in', group['render_text'])
        test.assertEqual(dimensions['source_sha256'], refs[1]['sha256'])
    for invalid in ([], ['source_02:missing']):
        size['image_direction']['measurement_ids'] = invalid
        blocked = compile_visual_design_kit_response(raw, source_manifest=[appearance, dimensions],
                    output_inventory=initial_output_inventory([appearance, dimensions]))
        test.assertEqual('pending', next(r for r in blocked['image_briefs'] if r['role'] == 'size')['status'])
    # Genuine source ambiguity remains local; no guessed coordinates or quantities.
    observed = _validate_observations([dict(source_id='source_00', role_guess='scene')], ['source_00'], {})
    test.assertEqual('failed', observed['source_00']['status'])


def _latest_repair(test):
    from tests.remediation_recheck_fixture import _source, _plan, _brief
    sources = [_source(), _source('source_01', 'scene')]
    raw = _plan(sources)
    _brief(raw, 'func')['image_direction']['product_sources'] = ['initial_unknown']
    for mode in ('bad_new_reference', 'missing', 'duplicate'):
        replacement = deepcopy(_brief(raw, 'func'))
        replacement['image_direction']['product_sources'] = ['latest_unknown']
        rows = [] if mode == 'missing' else [replacement] * (2 if mode == 'duplicate' else 1)
        with TemporaryDirectory() as tmp, patch('core.visual_design_kit.gemini_stream_generate',
                return_value=json.dumps({'image_briefs': rows})), patch(
                'core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
            result = _finish_image_briefs(raw, output_inventory=initial_output_inventory(sources),
                job=Path(tmp), child='B1', source_manifest=sources, category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp),
                deadline_monotonic=time.monotonic()+5, cached=None)
        failed = _brief(result, 'func')
        test.assertEqual('pending', failed['status'])
        test.assertNotIn('initial_unknown', json.dumps(failed))
        if mode == 'bad_new_reference':
            test.assertIn('latest_unknown', json.dumps(failed['draft']))
        test.assertEqual('ready', _brief(result, 'scene')['status'])

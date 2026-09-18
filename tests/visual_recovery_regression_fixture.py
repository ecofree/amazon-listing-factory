"""Exercise current writers and recovery with only remote services substituted."""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core import final_source_intents as intents, visual_design_kit as design, production
from core.image_tasks import build_image_tasks
from core.image_task_inputs import initial_output_inventory
from tests.test_image_branch_v1 import (
    ImageBranchCurrentBehaviorTests, _Plugin, _family, _scope, _planner_payload,
    _fixture_observation, _fixture_reviews, _evidence,
)


@contextmanager
def _workspace(*, siblings=False):
    with TemporaryDirectory() as tmp, ExitStack() as stack:
        job = Path(tmp)
        rows, _ = ImageBranchCurrentBehaviorTests()._source_fixture(job)
        family, scope = _family(), _scope()
        if siblings:
            other = dict(family['family']['children'][0], asin='B000000002')
            family['family']['children'].append(other)
            scope['selected_children'].append(other['asin'])
            scope['selected_sources'][other['asin']] = [0, 1, 2, 3]
            rows += [dict(row, child=other['asin']) for row in rows]
        for module, values in ((intents, {'ensure_run_scope': None, 'download_artifacts_current': (True, []),
                'read_download_manifest': {'rows': rows}, 'read_product_family': family, 'row_in_scope': True}),
                (design, {'read_product_family': family, 'read_run_scope': scope, 'load_job': {}, 'load_env': {},
                          'gemini_scope_identity': [{'provider': 'fixture', 'model': 'fixture'}]})):
            for name, value in values.items():
                stack.enter_context(patch.object(module, name, return_value=value))
        stack.enter_context(patch('core.run_scope.read_run_scope', return_value=scope))
        stack.enter_context(patch('core.image_tasks.read_product_family', return_value=family))
        stack.enter_context(patch('core.image_tasks.read_run_scope', return_value=scope))
        stack.enter_context(patch.object(production, 'assert_family_matches_plugin'))
        stack.enter_context(patch.object(intents, 'ocr_evidence_for_image', return_value={'available': False}))
        stack.enter_context(patch.object(design, 'review_planning_bindings', side_effect=_fixture_reviews))
        yield job, stack, scope


def _planner(job, calls):
    def respond(prompt, paths, **kwargs):
        calls.append(prompt)
        raw = _planner_payload(intents.read_final_source_intents(job, plugin=_Plugin()))
        if prompt.startswith('Repair the listed'):
            context = json.loads(prompt[prompt.index('{"shared_design":'):])
            replacements = []
            for pending in context['pending']:
                draft = next(row for row in raw['image_briefs'] if row['source_id'] == pending['source_id']
                             and row['role'].split('_')[0] == pending['role'].split('_')[0])
                replacements.append(dict(draft, role=pending['role']))
            raw = {'image_briefs': replacements}
        observer = kwargs.get('attempt_observer')
        if observer:
            observer({'event': 'request_budget', 'physical_request_count': 1})
            observer({'provider': 'fixture', 'model': 'fixture', 'status': 'success', 'elapsed_ms': 1})
        return json.dumps(raw)
    return respond


def verify_visual_recovery(test):
    _text_gap_roundtrip(test)
    _text_gap_budget(test)
    _checkpoint_roundtrip(test)
    _repair_checkpoint(test)
    _sibling_interruption(test)
    _recovered_inventory(test)


def _text_gap_roundtrip(test):
    with _workspace() as (job, stack, scope):
        observation_calls = []
        def observe(prompt, paths, **kwargs):
            context = json.loads(prompt.split('Input evidence, not response fields:\n', 1)[1])
            sources = context['attachments']
            observation_calls.append([row['source_id'] for row in sources])
            rows = _fixture_observation(job, _family()['family']['children'][0], sources)
            if not context['correction_requests']:
                rows['source_02']['text_gaps'] = [dict(text='Unreadable necessary shelf note', kind='product_fact')]
            kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
            return json.dumps({'sources': list(rows.values())})
        stack.enter_context(patch('core.visual_semantics.gemini_stream_generate', side_effect=observe))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        before = intents.read_final_source_intents(job, plugin=_Plugin())
        plans = []
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=_planner(job, plans)))
        request = production.JobRunRequest(job_dir=job, plugin=_Plugin(), workers=1)
        result = production._run_stage('brief', request=request)
        test.assertEqual([], result['failures'])
        test.assertEqual([['source_00', 'source_01', 'source_02', 'source_03'], ['source_02']], observation_calls)
        after = intents.read_final_source_intents(job, plugin=_Plugin())
        test.assertEqual([row for row in before if row['source_index'] != 2], [row for row in after if row['source_index'] != 2])
        test.assertEqual(1, len(plans))
        saved = design.read_visual_design_kits(job, plugin=_Plugin())
        test.assertTrue(all(row['status'] == 'ready' for row in saved['tasks'][0]['image_briefs']))
        test.assertEqual({}, design.observation_corrections(saved))
        production._run_stage('brief', request=request)
        test.assertEqual(2, len(observation_calls))
        test.assertEqual(1, len(plans))


def _checkpoint_roundtrip(test):
    for phase in ('before_review', 'partial_review'):
        with test.subTest(interruption=phase), _workspace() as (job, stack, scope):
            stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=_fixture_observation))
            intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
            plans, accepted = [], set()
            stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=_planner(job, plans)))
            count = 0
            def review(requests, **kwargs):
                nonlocal count
                count += 1
                if phase == 'before_review' or count > 1:
                    raise KeyboardInterrupt('offline interruption during review')
                accepted.add(requests[0]['key'])
                kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
                return _fixture_reviews(requests[:1], **kwargs)
            with patch.object(design, 'review_planning_bindings', side_effect=review), test.assertRaises(KeyboardInterrupt):
                design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
            saved = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
            test.assertTrue(design._planner_trace_current(job, saved))
            test.assertEqual(1, len(plans))
            initial = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
            fingerprints = {row['role']: row['task_fingerprint'] for row in initial['tasks'] if row['formation_status'] == 'ready'}
            retried = []
            def resume(requests, **kwargs):
                retried.extend(row['key'] for row in requests)
                return _fixture_reviews(requests, **kwargs)
            with patch.object(design, 'review_planning_bindings', side_effect=resume):
                complete = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
            test.assertEqual([], complete['failures'])
            test.assertTrue(all(row['status'] == 'ready' for row in complete['tasks'][0]['image_briefs']))
            test.assertFalse(accepted.intersection(retried))
            test.assertEqual(saved['family_design_id'], complete['tasks'][0]['family_design_id'])
            test.assertEqual(1, len(plans))
            final = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
            test.assertTrue(all(row['task_fingerprint'] == fingerprints[row['role']]
                                for row in final['tasks'] if row['role'] in fingerprints))
            test.assertTrue(design._planner_trace_current(job, saved))  # Earlier immutable checkpoint still verifies.


def _text_gap_budget(test):
    with _workspace() as (job, stack, scope):
        calls = []
        def observe(prompt, paths, **kwargs):
            context = json.loads(prompt.split('Input evidence, not response fields:\n', 1)[1])
            calls.append([row['source_id'] for row in context['attachments']])
            rows = _fixture_observation(job, _family()['family']['children'][0], context['attachments'])
            rows['source_02']['text_gaps'] = [dict(text='Unreadable necessary shelf note', kind='product_fact')]
            kwargs['attempt_observer']({'event': 'request_budget', 'physical_request_count': 1})
            return json.dumps({'sources': list(rows.values())})
        stack.enter_context(patch('core.visual_semantics.gemini_stream_generate', side_effect=observe))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        plans = []
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=_planner(job, plans)))
        request = production.JobRunRequest(job_dir=job, plugin=_Plugin(), workers=1)
        production._run_stage('brief', request=request)
        first = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
        before = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
        for _ in range(5):
            production._run_stage('brief', request=request)
        final = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
        test.assertEqual(4, len(calls))
        test.assertTrue(all(keys == ['source_02'] for keys in calls[1:]))
        test.assertEqual(1, len(plans))
        test.assertEqual(first['family_design_id'], final['family_design_id'])
        test.assertEqual(['func'], [row['role'] for row in final['image_briefs'] if row['status'] != 'ready'])
        after = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
        fingerprints = {row['role']: row['task_fingerprint'] for row in after['tasks']}
        test.assertTrue(all(fingerprints[row['role']] == row['task_fingerprint'] for row in before['tasks']
                            if row['formation_status'] == 'ready'))


def _repair_checkpoint(test):
    with _workspace() as (job, stack, scope):
        stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=_fixture_observation))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        plans = []
        respond = _planner(job, plans)
        def planner(prompt, paths, **kwargs):
            raw = json.loads(respond(prompt, paths, **kwargs))
            if not prompt.startswith('Repair the listed'):
                next(row for row in raw['image_briefs'] if row['role'] == 'func')['image_direction']['environment_mode'] = []
            return json.dumps(raw)
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=planner))
        with patch.object(design, 'review_planning_bindings', side_effect=KeyboardInterrupt('after local repair')), test.assertRaises(KeyboardInterrupt):
            design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        kit = design.read_visual_design_kits(job, plugin=_Plugin())['tasks'][0]
        pending = next(row for row in kit['image_briefs'] if row['role'] == 'func')
        test.assertEqual('review', pending['failure_owner'])
        test.assertIsInstance(pending['draft']['image_direction']['environment_mode'], str)
        test.assertEqual(2, len(plans))
        completed = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        test.assertEqual(2, len(plans))
        test.assertTrue(all(row['status'] == 'ready' for row in completed['tasks'][0]['image_briefs']))


def _sibling_interruption(test):
    with _workspace(siblings=True) as (job, stack, scope):
        stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=_fixture_observation))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        calls = []
        respond = _planner(job, calls)
        def planner(prompt, paths, **kwargs):
            if 'B000000002' in kwargs['request_id']:
                raise KeyboardInterrupt('second child interrupted')
            return respond(prompt, paths, **kwargs)
        with patch.object(design, 'gemini_stream_generate', side_effect=planner), test.assertRaises(KeyboardInterrupt):
            design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        saved = design.read_visual_design_kits(job, plugin=_Plugin())['children']
        test.assertEqual({'B000000001'}, set(saved))
        with patch.object(design, 'gemini_stream_generate', side_effect=respond):
            complete = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        test.assertEqual(2, len(calls))
        test.assertEqual(set(scope['selected_children']), set(complete['children']))
        test.assertEqual(saved['B000000001'], complete['children']['B000000001'])
    with _workspace(siblings=True) as (job, stack, scope):
        stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=_fixture_observation))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        calls = []
        with patch.object(design, 'gemini_stream_generate', side_effect=_planner(job, calls)):
            design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=2)
        saved = design.read_visual_design_kits(job, plugin=_Plugin())
        test.assertEqual(set(scope['selected_children']), set(saved['children']))
        test.assertTrue(all(row['status'] == 'ready' for kit in saved['tasks'] for row in kit['image_briefs']))


def _recovered_inventory(test):
    with _workspace() as (job, stack, scope):
        recovered = False
        def observe(job, child, sources, **kwargs):
            result = _fixture_observation(job, child, sources)
            if recovered:
                result['source_01'] = dict(_evidence('func')['visual_evidence'], source_id='source_01')
            else:
                result['source_01'] = dict(source_id='source_01', status='failed', error='temporary observation failure')
            return result
        stack.enter_context(patch.object(intents, 'observe_child_sources', side_effect=observe))
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        plans = []
        stack.enter_context(patch.object(design, 'gemini_stream_generate', side_effect=_planner(job, plans)))
        first = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)['tasks'][0]
        before = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
        recovered = True
        intents.build_final_source_intents(job_dir=job, plugin=_Plugin())
        complete = design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        test.assertEqual([], complete['failures'])
        kit = complete['tasks'][0]
        test.assertEqual(first['family_art_direction'], kit['family_art_direction'])
        test.assertEqual(first['output_inventory'], kit['output_inventory'][:len(first['output_inventory'])])
        test.assertEqual({'role': 'func_02', 'source_id': 'source_01'}, kit['output_inventory'][-1])
        test.assertTrue(all(row['status'] == 'ready' for row in kit['image_briefs']))
        test.assertEqual(1, sum(not prompt.startswith('Repair the listed') for prompt in plans))
        test.assertEqual(1, sum(prompt.startswith('Repair the listed') for prompt in plans))
        after = build_image_tasks(job_dir=job, plugin=_Plugin(), include_optional=True)
        fingerprints = {row['role']: row['task_fingerprint'] for row in after['tasks']}
        test.assertTrue(all(fingerprints[row['role']] == row['task_fingerprint'] for row in before['tasks']))
        design.build_visual_design_kits(job_dir=job, plugin=_Plugin(), workers=1)
        test.assertEqual(2, len(plans))
        reordered = list(reversed(kit['source_references']))
        test.assertEqual(kit['output_inventory'], initial_output_inventory(reordered, previous=kit))

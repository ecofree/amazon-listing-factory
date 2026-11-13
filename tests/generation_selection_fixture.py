"""Generation selection is invocation permission, never a replacement output inventory."""
from contextlib import contextmanager, ExitStack
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import tempfile
from unittest.mock import patch


def _identity(task):
    return {k:task[k] for k in ('child','role','task_fingerprint')}


def _snapshot(job):
    return {p.relative_to(job).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in job.rglob('*') if p.is_file() and '.lock' not in p.name}


@contextmanager
def _workspace():
    from core import production, image_generation as generation, image_resources
    from core.candidate_state import current_candidate
    from core.job import create_job
    from core.io import file_sha256, write_jsonl
    from core.plugin import load_plugin
    from tests.current_image_contract_fixture import current_image_task, current_prompt_artifact
    from tests.image_boundary_fixture import native_bytes
    plugin=load_plugin('bed_frame')
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
        job=create_job(plugin=plugin,seed_asin='B000000001',brand='Test',sku_prefix='TEST',out_root=tmp)
        # Invocation-selection tests use publication-sized pixels, not GPU inference.
        source=job/'images/source.png';source.write_bytes(native_bytes((1600,1600)))
        tasks=[current_image_task(role,source_sha256=file_sha256(source),category_id=plugin.category_id) for role in ('main','scene')]
        write_jsonl(job/'reports/image_tasks_v13.jsonl',tasks)
        prompts=[current_prompt_artifact(job,t)['prompts'][0] for t in tasks]
        write_jsonl(job/'reports/image_prompts_v2.jsonl',prompts)
        scope=dict(selected_children=['B1'],selected_sources={'B1':[0]},mode='debug')
        stack.enter_context(patch.object(production,'load_env',return_value={}))
        stack.enter_context(patch.object(production,'assert_family_matches_plugin'))
        stack.enter_context(patch.object(production,'_run_environment',side_effect=lambda r,s:{'stages':s,'scope':{'generation_tasks':r.generation_tasks}}))
        stack.enter_context(patch.object(production,'_source_scope_counts',return_value={'source_unresolved_count':0}))
        stack.enter_context(patch('core.run_scope.scope_input_revision',return_value='e'*64))
        stack.enter_context(patch('core.run_scope.read_run_scope',return_value=scope))
        stack.enter_context(patch('core.image_tasks.image_tasks_current',return_value=True))
        stack.enter_context(patch('core.image_prompt_compiler.image_prompts_current',return_value=True))
        stack.enter_context(patch.object(generation,'scoped_child_set',return_value={'B1'}))
        stack.enter_context(patch.object(generation,'require_current_image_branch'))
        stack.enter_context(patch.object(generation,'_load_generation_env'))
        stack.enter_context(patch.object(generation,'provider_order',return_value=['copy']))
        stack.enter_context(patch.object(generation,'apply_role_provider_policy',side_effect=lambda task,_plugin:task.update(providers=['copy'])))
        stack.enter_context(patch.object(generation,'eligible_imagegen_providers',side_effect=lambda _p,providers:providers))
        stack.enter_context(patch.dict('os.environ',{'AMAZON_FACTORY_IMAGEGEN_MODE':'copy',
            'AMAZON_FACTORY_PRODUCTION_IMAGEGEN':'0'}))
        stack.enter_context(patch.object(image_resources,'_LEDGER',job/'runtime/resources.json'))
        stack.enter_context(patch.object(image_resources,'_system_memory_bytes',return_value=(32*1024**3,24*1024**3)))
        stack.enter_context(patch('core.image_generation_executor.generate_with_provider_retries',side_effect=AssertionError('No remote generation in this fixture')))
        # Selection tests own invocation permissions and real candidate commits,
        # not subprocess/memory isolation (covered by the finalizer deadline test).
        # A spawned worker cannot inherit this fixture's memory reservations.
        from core.image_generation_executor import _finalize_local
        stack.enter_context(patch.object(generation, 'finalize_candidate', side_effect=_finalize_local))
        stack.enter_context(patch('core.image_upscale._realesrgan_resize',side_effect=AssertionError('No GPU inference in selection tests')))
        def release(_request):
            rows=[]
            for task in tasks:
                candidate=current_candidate(job,task)
                rows.append(dict(child=task['child'],role=task['role'],formation_status=task['formation_status'],
                    candidate_sha256=candidate.get('candidate_sha256',''),automatic_decision='not_run',
                    final_decision='awaiting_qa' if candidate else 'awaiting_generation'))
            return {'status':'awaiting_review','rows':rows}
        stack.enter_context(patch.object(production,'_release_if_available',side_effect=release))
        yield job,plugin,tasks


def verify_execution_selection(test):
    from core.image_generation import select_generation_tasks
    tasks=[dict(child='B1',role=role,task_fingerprint=digit*64,formation_status='ready') for role,digit in [('main','a'),('scene','b')]]
    selected=[_identity(tasks[0])]
    test.assertEqual(tasks,select_generation_tasks(tasks,{'B1'},None))
    for empty in ([],(),'',False):
        with test.assertRaises(ValueError):select_generation_tasks(tasks,{'B1'},empty)
    test.assertEqual(tasks[:1],select_generation_tasks(tasks,{'B1'},selected))
    for bad in ([dict(selected[0],task_fingerprint='c'*64)],selected*2,[dict(selected[0],child='B2')],
                [dict(selected[0],prompt='injected')]):
        with test.assertRaises(ValueError):select_generation_tasks(tasks,{'B1'},bad)
    with test.assertRaises(ValueError):select_generation_tasks([dict(tasks[0],formation_status='blocked')],{'B1'},selected)
    _controller_boundaries(test)
    _cli_boundaries(test)


def _controller_boundaries(test):
    from core import production, image_generation as generation, status
    from core.io import read_json, write_json
    with _workspace() as (job,plugin,tasks):
        inventory,additional,_=generation.preflight_generation_tasks(job,plugin,work_children=('B1',),work_roles=('scene',))
        test.assertEqual(2,len(inventory),'Additional execution must preserve the complete role inventory')
        test.assertEqual(['scene'],[t['role'] for t in additional],'An additional pass cannot retry the required main image')
        selected=tuple([_identity(tasks[0])])
        request=production.JobRunRequest(job_dir=job,plugin=plugin,generation_tasks=selected,workers=1,template_mode='draft')
        old_snapshot=_snapshot(job)
        bad=replace(request,generation_tasks=selected+(dict(_identity(tasks[1]),task_fingerprint='f'*64),))
        # Both real and dry-run preflight must reject without stage/task/receipt mutation.
        for candidate in (bad,replace(bad,dry_run=True),replace(request,generation_tasks=()),
                          replace(request,brand_brief_path='must-not-be-imported.json'),
                          replace(request,child_ids=('B2',),dry_run=True),
                          replace(request,generation_tasks=None,all_generation_tasks='false')):
            with patch.object(production,'begin_run') as begin,patch.object(production,'start_stage') as start,patch.object(
                    production,'add_error') as error,patch('core.design_reference_library.update_brand_design_brief') as brand:
                with test.assertRaises((ValueError,production.ProductionPipelineError)):
                    production.run_job(candidate,stages=['generate'])
                begin.assert_not_called();start.assert_not_called();error.assert_not_called();brand.assert_not_called()
            test.assertEqual(old_snapshot,_snapshot(job))
        from core.image_prompt_compiler import ImagePromptError
        for dry_run in (False,True):
            with patch.object(generation,'read_image_prompts',return_value={'prompts':[]}),patch.object(production,'begin_run') as begin:
                with test.assertRaises(ImagePromptError):production.run_job(replace(request,dry_run=dry_run),stages=['generate'])
                begin.assert_not_called()
            test.assertEqual(old_snapshot,_snapshot(job))
        with patch.object(generation,'current_candidate',side_effect=AssertionError('Dry run must not recover a candidate')),patch.object(
                generation,'recover_response',side_effect=AssertionError('Dry run must not reconcile paid receipts')):
            preview=production.run_job(replace(request,dry_run=True),stages=['generate'])
        test.assertEqual('dry_run',preview['workflow_status'])
        test.assertEqual(1,preview['generation_invocation']['requested_count'])
        test.assertEqual('validated_tasks_and_prompts',preview['generation_invocation']['validation'])
        test.assertEqual(old_snapshot,_snapshot(job))
        with patch.object(generation,'generation_artifacts_current') as recover,patch('core.image_provider_routing.provider_order',return_value=[]):
            production._assert_production_entry_requirements(replace(request,generation_tasks=None,production=True,resume=True,dry_run=True),['generate'])
            recover.assert_not_called()
        test.assertEqual(old_snapshot,_snapshot(job))
        full=replace(request,generation_tasks=None,all_generation_tasks=True)
        limited_revision=production._stage_input_revision('generate',request)
        full_revision=production._stage_input_revision('generate',full)
        test.assertNotEqual(limited_revision,full_revision)
        with patch.object(generation,'generate_one',wraps=generation.generate_one) as generated:
            first=production.run_job(request,stages=['generate'])
            test.assertEqual(1,generated.call_count)
            test.assertEqual('success',first['generation_invocation']['status'], status.load_status(job)['errors'])
            test.assertEqual((1,1,0,1),tuple(first['generation_invocation'][k] for k in ('requested_count','completed_count','failed_count','not_run_count')))
            test.assertEqual('partial_success',first['workflow_status'])
            test.assertEqual('selected_generation_completed_whole_job_incomplete',first['workflow_reason'])
            test.assertEqual('incomplete',first['planned_image_completion_status'])
            test.assertEqual('success',status.load_status(job)['stages']['generate']['status'])
            state=status.load_status(job)
            test.assertEqual('selected',state['generation_execution_scope']['mode'])
            test.assertNotIn(tasks[1]['logical_task_id'],state['tasks'])
            before=_snapshot(job)
            all_preview=production.run_job(replace(full,dry_run=True),stages=['generate'])
            test.assertEqual('all',all_preview['generation_invocation']['mode'])
            test.assertEqual(before,_snapshot(job))
            for retry in (replace(request,generation_tasks=None,resume=True),replace(request,generation_tasks=None),
                          replace(request,generation_tasks=None,resume=True,dry_run=True)):
                with test.assertRaisesRegex(ValueError,'all-generation-tasks'):
                    production.run_job(retry,stages=['generate'])
                test.assertEqual(before,_snapshot(job))
            # A nongeneration invocation cannot forget the last accepted limited scope.
            production.run_job(replace(request,generation_tasks=None,dry_run=True),stages=['copy'])
            with test.assertRaisesRegex(ValueError,'all-generation-tasks'):
                production.run_job(replace(request,generation_tasks=None),stages=['generate'])
            final=production.run_job(replace(full,resume=True),stages=['generate'])
            test.assertEqual(2,generated.call_count)  # Reuse main; generate only previously omitted scene.
            test.assertEqual(2,final['generation_invocation']['completed_count'])
            test.assertEqual('success',final['planned_image_completion_status'])
            test.assertEqual('all',status.load_status(job)['generation_execution_scope']['mode'])
            test.assertEqual('success',status.load_status(job)['stages']['generate']['status'])
            production.run_job(replace(request,generation_tasks=None,resume=True),stages=['generate'])
            test.assertEqual(2,generated.call_count)
            again=production.run_job(request,stages=['generate'])
            test.assertEqual('success',again['generation_invocation']['status'])
            test.assertEqual('success',again['planned_image_completion_status'])
            test.assertEqual('success',status.load_status(job)['stages']['generate']['status'])
            test.assertEqual(2,generated.call_count)
        # Current-job invocation evidence also guards earlier limited runs without a state marker.
        state=status.load_status(job);state.pop('generation_execution_scope');write_json(job/'job_state.json',state)
        from core.progress_trace import record_progress
        record_progress(job,'run_environment_recorded',environment={'stages':['generate'],'scope':{'generation_tasks':list(selected)}})
        record_progress(job,'run_environment_recorded',environment={'stages':['copy'],'scope':{'generation_tasks':None}})
        before=_snapshot(job)
        with test.assertRaisesRegex(ValueError,'all-generation-tasks'):
            production.run_job(replace(request,generation_tasks=None),stages=['generate'])
        test.assertEqual(before,_snapshot(job))
        # Content task fingerprints were never changed by execution selection.
        test.assertEqual([t['task_fingerprint'] for t in tasks],
            [r['task_fingerprint'] for r in generation.read_image_tasks(job)['tasks']])
    # Accepted scope survives execution failure and later non-generation stage bookkeeping.
    with _workspace() as (job,plugin,tasks):
        request=production.JobRunRequest(job_dir=job,plugin=plugin,generation_tasks=tuple([_identity(tasks[0])]),template_mode='draft')
        with patch.object(generation,'run_image_generation',side_effect=OSError('Fixture runtime failure after admission')):
            with test.assertRaises(OSError):production.run_job(request,stages=['generate'])
        test.assertEqual('selected',status.load_status(job)['generation_execution_scope']['mode'])
        test.assertEqual('failed',read_json(job/'reports/production_summary_v3.json')['generation_invocation']['status'])
        status.mark_stage(job,'copy',attempt_id='copy-attempt',input_revision='c'*64)
        before=_snapshot(job)
        with test.assertRaisesRegex(ValueError,'all-generation-tasks'):
            production.run_job(replace(request,generation_tasks=None),stages=['generate'])
        test.assertEqual(before,_snapshot(job))
    # A full-scope acknowledgement is not an authorization to repeat an unknown paid request.
    with _workspace() as (job,plugin,tasks):
        from core.image_response import begin_response, submit_response, response_binding, response_directory
        prompts=generation.read_image_prompts(job)['prompts']
        runtime={**tasks[0],'job_dir':str(job),'candidate_revision':0,'prompt':prompts[0]['prompt']}
        audit=dict(response_binding=response_binding(runtime),logical_task_id=tasks[0]['logical_task_id'],provider='fixture',request_id='unknown-once')
        receipt=begin_response(response_directory(runtime),provider='fixture',audit=audit);submit_response(receipt,audit)
        original=receipt.read_bytes()
        request=production.JobRunRequest(job_dir=job,plugin=plugin,generation_tasks=tuple([_identity(tasks[1])]),workers=1,template_mode='draft')
        production.run_job(request,stages=['generate'])
        test.assertEqual(original,receipt.read_bytes())
        result=production.run_job(replace(request,generation_tasks=None,all_generation_tasks=True),stages=['generate'])
        test.assertEqual((1,1),tuple(result['generation_invocation'][k] for k in ('completed_count','failed_count')))
        test.assertEqual(original,receipt.read_bytes())
        test.assertEqual('review',status.load_status(job)['tasks'][tasks[0]['logical_task_id']]['status'])


def _cli_boundaries(test):
    from scripts.factory import build_parser,cmd_run
    from core import production
    parser=build_parser()
    with _workspace() as (job,plugin,tasks):
        file=job/'selection.json';file.write_text(json.dumps([_identity(tasks[0])]),encoding='utf-8')
        base=['run','--job',str(job),'--stages','generate']
        with patch('scripts.factory._assert_runtime_dependencies'),patch.object(production,'run_job',return_value={'workflow_status':'dry_run'}) as run,patch('builtins.print'):
            cmd_run(parser.parse_args(base+['--dry-run']))
            test.assertIsNone(run.call_args.args[0].generation_tasks)
            cmd_run(parser.parse_args(base+['--generation-tasks',str(file),'--dry-run']))
            test.assertEqual(tuple([_identity(tasks[0])]),run.call_args.args[0].generation_tasks)
            run.return_value={'workflow_status':'partial_success','generation_invocation':{'status':'success'}}
            test.assertEqual(0,cmd_run(parser.parse_args(base+['--generation-tasks',str(file)])))
            run.return_value['generation_invocation']['status']='failed'
            test.assertNotEqual(0,cmd_run(parser.parse_args(base+['--generation-tasks',str(file)])))
            cmd_run(parser.parse_args(base+['--all-generation-tasks','--dry-run']))
            test.assertTrue(run.call_args.args[0].all_generation_tasks)
            run.reset_mock();file.write_text('[]',encoding='utf-8')
            with test.assertRaises(ValueError):cmd_run(parser.parse_args(base+['--generation-tasks',str(file)]))
            with test.assertRaises(ValueError):cmd_run(parser.parse_args(base+['--generation-tasks','']))
            run.assert_not_called()

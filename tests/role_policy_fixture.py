"""Role-local policy revisions on the real plan/task/prompt chain."""
from copy import deepcopy
import json
from unittest.mock import patch


def verify_role_policy_scope(test):
    from tests.test_image_branch_v1 import classified_workspace,_Plugin,_planner_payload
    from tests.current_image_contract_fixture import planner_wire
    from tests.test_visual_flow_contract import feedback_payload,accept_response,protect
    from tests.role_restore_fixture import _candidate,_infer
    from core import visual_design_kit as kits
    from core.image_tasks import build_image_tasks
    from core.image_prompt_compiler import build_image_prompts
    from core.candidate_state import current_candidate
    from core.plugin import ProductPlugin,load_plugin
    from core.planning_journal import PlanningJournal,journal_path
    from core.io import file_sha256
    config=deepcopy(load_plugin('bathroom_cabinet').merged_config());original_config=ProductPlugin.merged_config
    with classified_workspace() as (job,intents):
        raw=_planner_payload(intents)
        next(b for b in raw['image_briefs'] if b['role']=='func')['region_intent']=protect()
        def initial(prompt,images,**kw):
            text=json.dumps(planner_wire(raw));observe=kw['attempt_observer']
            observe({'event':'request_budget','physical_request_count':1})
            observe({'status':'success','provider':'fixture','model':'fixture','response_text':text});return text
        with (patch.object(kits,'gemini_stream_generate',side_effect=initial),
              patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),
              patch('core.product_region.ProductRegions._backend',return_value={'fixture':'cpu'}),
              patch('core.product_region.ProductRegions._infer',side_effect=_infer)):
            result=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
        test.assertFalse(result['failures'],result['failures']);old=result['tasks'][0];child=old['child']
        tasks=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
        prompts=build_image_prompts(job_dir=job,plugin=_Plugin())['prompts']
        old_tasks={t['role']:t for t in tasks};old_prompts={p['role']:p for p in prompts}
        manifest_ref,manifest=_candidate(job,old_tasks['main'],old_prompts['main'])
        old_origin=deepcopy(old['planner']['role_origins']);old_art=deepcopy(old['family_art_direction'])
        origin_paths=[r['path'] if r['kind']=='initial' else r['packet']['response_path'] for r in old_origin.values()]
        frozen={path:file_sha256(job/path) for path in origin_paths}
        journal=PlanningJournal(journal_path(job,child),child=child,scope_key='fixture-owned-scope',initialize=False)
        unknown=journal.reserve('tool_calls',context={'roles':['scene']});journal.physical(unknown,1);journal.settle(unknown)
        before=journal.read();requests=[]
        config['image_generation']['role_specific_rules']['func'].append('ROLE_SCOPE_SENTINEL preserve source-visible mounting screws.')
        config['image_generation'].setdefault('role_visual_direction',{})['func']='ROLE_DIRECTION_SENTINEL explain only this source-supported function.'
        def effective(plugin):return config if plugin.category_id=='bathroom_cabinet' else original_config(plugin)
        def confirm(prompt,images,**kw):
            data=feedback_payload(prompt);requests.append(data)
            test.assertEqual(['func'],data['required_roles'])
            test.assertEqual('confirm_policy',data['roles'][0]['work_kind'])
            policy=data['design_inputs_read_only']['policy']
            test.assertEqual({'func'},set(policy['role_specific_rules']))
            test.assertEqual({'func'},set(policy['role_visual_direction']))
            test.assertIn('ROLE_SCOPE_SENTINEL',json.dumps(policy))
            return accept_response(prompt,images,**kw)
        with patch.object(ProductPlugin,'merged_config',effective):
            updated=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
            test.assertEqual(['func'],[t['role'] for t in updated if t['formation_status']=='blocked'])
            policy_status={r['role']:r for r in kits.planning_status(job,_Plugin(),child=child)['roles']}
            test.assertFalse(policy_status['func']['accepted_role_policy_current'])
            test.assertTrue(policy_status['main']['accepted_role_policy_current'])
            # Updating only the mutable row context cannot manufacture policy acceptance.
            from core.required_role_policy import compiled_image_policy
            from core.planning_identity import design_context
            forged=deepcopy(old);forged['design_context']=design_context(compiled_image_policy(_Plugin()),{})
            test.assertNotIn('func',kits.current_visual_role_bases(job,_Plugin(),child,forged))
            for task in updated:
                if task['role']!='func':test.assertEqual(old_tasks[task['role']]['task_fingerprint'],task['task_fingerprint'])
            ready=next(t for t in updated if t['role']=='main')
            test.assertEqual(manifest['candidate_sha256'],current_candidate(job,ready)['candidate_sha256'])
            test.assertEqual(manifest_ref['sha256'],file_sha256(job/manifest_ref['path']))
            selection=[{'child':child,'role':'func','visual_design_kit_id':old['visual_design_kit_id']}]
            with (patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('A role rule cannot repurchase the shared plan')),
                  patch('core.planning_feedback.gemini_stream_generate',side_effect=confirm),
                  patch('core.product_region.ProductRegions._infer',side_effect=AssertionError('Policy-only change cannot repeat SAM inference'))):
                result=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),work_children=(child,),work_roles=('func',),workers=1)
            test.assertFalse(result['failures'],result['failures']);test.assertEqual(1,len(requests))
            current=kits.read_visual_design_kits(job,plugin=_Plugin())['children'][child]
            test.assertEqual(old_art,current['family_art_direction'])
            test.assertNotEqual(old_origin['func'],current['planner']['role_origins']['func'])
            for role in ('main','scene','size'):
                test.assertEqual(old_origin[role],current['planner']['role_origins'][role])
                test.assertEqual(before['roles'][role],journal.read()['roles'][role])
            for name,digest in frozen.items():test.assertEqual(digest,file_sha256(job/name))
            test.assertEqual(before['plan'],journal.read()['plan']);test.assertEqual(before['tool_calls']+1,journal.read()['tool_calls'])
            for key in ('limits','carry','grants'):test.assertEqual(before[key],journal.read()[key])
            test.assertEqual(before['requests'][unknown],journal.read()['requests'][unknown])
            restored=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
            new_prompts={p['role']:p for p in build_image_prompts(job_dir=job,plugin=_Plugin())['prompts']}
            test.assertTrue(all(t['formation_status']=='ready' for t in restored))
            for role in ('main','scene','size'):test.assertEqual(old_prompts[role]['prompt_sha256'],new_prompts[role]['prompt_sha256'])
            test.assertNotEqual(old_prompts['func']['prompt_sha256'],new_prompts['func']['prompt_sha256'])
            current_before=journal.path.read_bytes()
            with patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('No shared replan')),patch(
                    'core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No duplicate policy confirmation')):
                again=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
            test.assertFalse(again['failures']);test.assertEqual(current_before,journal.path.read_bytes())
            # A declined func revision cannot reopen just because a size rule changed later.
            config['image_generation']['role_specific_rules']['func'].append('A second func-only policy revision')
            current=kits.read_visual_design_kits(job,plugin=_Plugin())['children'][child]
            selection=[{'child':child,'role':'func','visual_design_kit_id':current['visual_design_kit_id']}]
            def decline(prompt,images,**kw):
                payload=feedback_payload(prompt);test.assertEqual(['func'],payload['required_roles'])
                return json.dumps({'decisions':[{'role':'func','action':'blocked','reason':'This rule needs source clarification',
                    'issue_type':'unsupported_goal','source_ids':['source_02']}]})
            with patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('No shared replan')),patch(
                    'core.planning_feedback.gemini_stream_generate',side_effect=decline) as declined:
                kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),planning_tasks=selection,workers=1)
            test.assertEqual(1,declined.call_count)
            stopped=deepcopy(journal.read()['roles']['func']);test.assertEqual('blocked_evidence',stopped['phase'])
            config['image_generation']['role_specific_rules']['size'].append('A size-only policy revision')
            def size_only(prompt,images,**kw):
                payload=feedback_payload(prompt);test.assertEqual(['size'],payload['required_roles'])
                test.assertEqual({'size'},set(payload['design_inputs_read_only']['policy']['role_specific_rules']))
                return accept_response(prompt,images,**kw)
            with patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('No shared replan')),patch(
                    'core.planning_feedback.gemini_stream_generate',side_effect=size_only) as size_call:
                kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
            test.assertEqual(1,size_call.call_count);test.assertEqual(stopped,journal.read()['roles']['func'])
            current_before=journal.path.read_bytes()
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No progress history cannot reset')):
                kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
            test.assertEqual(current_before,journal.path.read_bytes())
            config['image_generation']['structure_invariants'].append('A changed shared physical constraint')
            all_blocked=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
            test.assertTrue(all(t['formation_status']=='blocked' for t in all_blocked))

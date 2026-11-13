"""Reliability invariants folded into the existing production cases."""
from copy import deepcopy


def verify_partial_protocol(test):
    from core.planning_feedback import parse_decisions
    from core.planning_contract import work_capabilities
    contexts=[dict(role=role,key=key*64,capabilities=work_capabilities('decide_region',0,0),work_kind='decide_region')
              for role,key in [('main','a'),('scene','b')]]
    received=parse_decisions({'decisions':[dict(role='main',action='accept',reason='Current region supports the plan')]},contexts)
    test.assertEqual('accept',received['main']['action'])
    test.assertNotIn('action',received['scene'],'A missing response is not a model blocked decision')
    test.assertEqual('protocol',received['scene']['issue']['kind'])
    test.assertEqual('missing_role',received['scene']['issue']['code'])
    without_reason=parse_decisions({'decisions':[dict(role='main',action='accept')]},contexts[:1])
    test.assertEqual('accept',without_reason['main']['action'])
    from core.planning_feedback import parse_object
    partial=parse_object('{"decisions":[{"role":"main","action":"accept"},{"role":"scene","action":"accept","action":"blocked"}]}')
    checked=parse_decisions(partial,contexts)
    test.assertEqual('accept',checked['main']['action']);test.assertIn('issue',checked['scene'])


def verify_scoped_identity(test):
    from tests.test_visual_flow_contract import source,draft
    from tests.current_image_contract_fixture import current_art_direction
    from core.visual_design_kit_compiler import plan_key
    sources=[source('main','source_00'),source('func','source_01')]
    plan=draft('main');art=current_art_direction()
    before=plan_key(plan,art,sources)
    altered=deepcopy(sources);altered[1]['source_path']='elsewhere/same-bytes.png'
    test.assertEqual(before,plan_key(plan,art,altered),'Unconsumed source locations cannot revoke a role')
    altered[0]['source_sha256']='b'*64
    test.assertNotEqual(before,plan_key(plan,art,altered))
    metadata={'evidence_id':'shipping','field_path':'product.specs.shipping_box_code','type':'source_fact','text':'box A'}
    test.assertEqual(before,plan_key(plan,art,sources,[metadata]))
    physical={**metadata,'evidence_id':'load','field_path':'product.specs.weight_capacity','text':'300 lb'}
    test.assertNotEqual(before,plan_key(plan,art,sources,[physical]))
    from core.visual_design_kit_compiler import compile_visual_design_kit_response
    from core.image_task_inputs import initial_output_inventory
    functional=draft();claim={'evidence_id':'bullet','field_path':'product.bullets.0','text':'Four compartments','type':'source_product_statement'}
    functional['display_copy']['labels'][0]['evidence_ids']=['bullet']
    compiled=compile_visual_design_kit_response({'family_art_direction':art,'image_briefs':[functional]},source_manifest=sources,
        output_inventory=initial_output_inventory(sources),product_claims=[claim])
    ready=next(r for r in compiled['image_briefs'] if r['role']=='func')
    # Compare the same anchor after binding the fixture's real func source.
    functional['source_id']=ready['source_id']
    compiled=compile_visual_design_kit_response({'family_art_direction':art,'image_briefs':[functional]},source_manifest=sources,
        output_inventory=initial_output_inventory(sources),product_claims=[claim])
    ready=next(r for r in compiled['image_briefs'] if r['role']=='func')
    test.assertEqual('ready',ready['status'],ready.get('error'))
    test.assertEqual(plan_key(functional,art,sources,[claim]),plan_key(ready,art,sources,[claim]))


def verify_field_transactions(test):
    from tests.feedback_fix_fixture import verify_nested_patch
    verify_nested_patch(test)
    import json
    from unittest.mock import patch
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,role_row,draft,protect
    from core.io import read_json
    from core.planning_provenance import verify_role_origin
    from core.planning_feedback import verified_tool_decision
    with workspace() as (job,sources,raw,regions):
        raw['image_briefs'][0]['region_intent']=protect()
        raw['image_briefs']=[r for r in raw['image_briefs'] if r['role']!='scene']
        raw['image_briefs'][-1]['image_direction']['presentation']['components']=['wall']
        batches=[]
        def answer(prompt,images,**kwargs):
            payload=feedback_payload(prompt);batches.append(payload)
            if len(batches)==1:
                roles={r['role']:r for r in payload['roles']}
                test.assertEqual('create_draft',roles['scene']['work_kind'])
                test.assertEqual('repair_contract',roles['func']['work_kind'])
                test.assertIn('current_region',roles['func'],'A style ID must not suppress valid SAM preparation')
                test.assertEqual(['presentation_components'],roles['func']['writable_fields'])
                return json.dumps({'decisions':[{'role':'main','action':'accept'}]})
            test.assertEqual({'scene','func'},{r['role'] for r in payload['roles']})
            created=draft('scene');created.pop('source_id')
            return json.dumps({'decisions':[{'role':'scene','action':'supply_plan','image_brief':created},
                {'role':'func','action':'patch_plan','field_updates':{'presentation_components':[]},'accept_current_region':True}]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer) as remote:
            result=finish(job,sources,raw,regions)
        test.assertEqual(2,remote.call_count)
        for role in ('main','scene','func'):test.assertEqual('ready',role_row(result,role)['status'],role_row(result,role).get('error'))
        journal=read_json(job/'attempt_budget.json')
        for role in ('main','scene','func'):
            verify_role_origin(job,role_row(result,role),journal['roles'][role]['origin'],child='B1')
        # A dependency-hash rule change cannot invalidate the sealed statement;
        # current execution still checks today's key, and payload tampering fails.
        accepted=role_row(result,'main');origin=journal['roles']['main']['origin']
        with patch('core.planning_provenance.plan_key',return_value='f'*64):
            with test.assertRaisesRegex(ValueError,'Consumed planner context'):
                verify_role_origin(job,accepted,origin,child='B1')
            verify_role_origin(job,accepted,origin,child='B1',for_replanning=True)
            changed=deepcopy(accepted);changed['image_direction']['visual_goal']='Replace the sold product'
            with test.assertRaisesRegex(ValueError,'Ready brief differs'):
                verify_role_origin(job,changed,origin,child='B1',for_replanning=True)
        packet=journal['roles']['main']['origin']['packet']
        with patch('core.planning_feedback.parse_decisions',side_effect=AssertionError('No whole-batch reinterpretation')):
            verified_tool_decision(job,packet,role='main',key=packet['key'])
        before=deepcopy(journal['roles']['func']['draft'])
        # A current-mask accept cannot authorize a new product state.
        from core.planning_provenance import effective_decision
        from core.planning_contract import field_specs
        context={'role':'func','draft':before,'writable_fields':['product_state'],
            'field_specs':field_specs('func',sources,result['family_art_direction'])}
        with test.assertRaisesRegex(ValueError,'changed physical'):
            effective_decision(context,{'action':'patch_plan','field_updates':{'product_state':'Expose an unseen side'},'accept_current_region':True},{'sources':sources})
        test.assertEqual(before,journal['roles']['func']['draft'])


def verify_planning_outcomes(test):
    from tempfile import TemporaryDirectory
    from pathlib import Path
    import hashlib
    from core.io import write_json
    from core.planning_journal import PlanningJournal
    for classification,status,complete,code,expected in (
        ('transport_failure',402,True,'insufficient_balance','rejected'),
        ('configuration_failure',402,True,'insufficient_balance','rejected'),
        ('transport_failure',503,True,'internal_error','unknown'),
        ('configuration_failure',402,False,'insufficient_balance','unknown'),
        ('content_failure',200,True,'','received')):
        with test.subTest(outcome=(classification,status,complete)),TemporaryDirectory() as tmp:
            root=Path(tmp);journal=PlanningJournal(root/'journal.json',child='B1',scope_key='scope')
            trace=root/'trace';trace.mkdir();raw=trace/'response.txt';raw.write_text('{"error":{"type":"'+code+'"}}',encoding='utf-8')
            event=dict(status=classification,raw_response_path=raw.name,response_body_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                transport=dict(http_status=status,response_complete=complete,
                    request_outcome='rejected' if status==402 and complete and code else 'unknown',error_code=code),
                error='HTTP Error 402: insufficient_balance')
            write_json(trace/'attempts.json',[event])
            identity=journal.reserve('tool_calls',context={'trace':'trace','roles':['main']});journal.physical(identity,1)
            journal.settle_attempt(identity,job=root,trace=trace)
            test.assertEqual(expected,journal.read()['requests'][identity]['status'])
            test.assertEqual(1,journal.read()['tool_calls'])
            # A stale exception cannot downgrade a known received/rejected response.
            journal.settle(identity)
            test.assertEqual(expected,journal.read()['requests'][identity]['status'])
    with TemporaryDirectory() as tmp:
        root=Path(tmp);trace=root/'trace';trace.mkdir()
        journal=PlanningJournal(root/'journal.json',child='B1',scope_key='scope')
        identity=journal.reserve('tool_calls');journal.physical(identity,1)
        write_json(trace/'attempts.json',[dict(status='configuration_failure',error='HTTP Error 402: insufficient_balance')])
        journal.settle_attempt(identity,job=root,trace=trace)
        test.assertEqual('unknown',journal.read()['requests'][identity]['status'],'Error prose without bound response evidence cannot authorize another POST')
        from core.visual_semantics import _attempt_trace
        from core.vision_gemini_client import _emit_attempt
        import time
        _,record=_attempt_trace(trace/'attempts.json')
        body='{\r\n"invalid_model_reply": true\r\n}'
        _emit_attempt(record,request_id=identity,client={'_transport':{'response_complete':True,'http_status':200}},
            model='fixture',protocol='test',attempt=1,status='content_failure',started=time.monotonic(),response_body=body)
        test.assertTrue(journal.settle_attempt(identity,job=root,trace=trace))
        test.assertEqual('received',journal.read()['requests'][identity]['status'])
        saved=journal.read()['requests'][identity]
        test.assertEqual(hashlib.sha256(body.encode()).hexdigest(),saved['result_sha256'])
        (root/saved['result_path']).write_bytes(b'tampered')
        with test.assertRaisesRegex(ValueError,'trace changed'):journal.settle_attempt(identity,job=root,trace=trace)


def verify_journal(test):
    verify_planning_outcomes(test)
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from core.planning_journal import PlanningJournal,PlanningBudgetError
    from core.planning_identity import journal_scope
    from core.io import write_json
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'allowance.json';journal=PlanningJournal(path,child='B1',scope_key='scope')
        identity=journal.reserve('tool_calls',request_id='request-1',roles={'main':{'phase':'dispatched'}},records=[])
        test.assertEqual('dispatched',journal.read()['roles']['main']['phase'])
        journal.physical(identity,1);journal.settle(identity)
        with test.assertRaises(PlanningBudgetError):journal.reserve('tool_calls',request_id=identity)
        same=PlanningJournal(path,child='B1',scope_key='scope');test.assertEqual(3,same.remaining('tool_calls'))
        with test.assertRaises(PlanningBudgetError):same.settle(identity,known_unsent=True)
        with test.assertRaisesRegex(PlanningBudgetError,'pending/unknown'):same.reserve('tool_calls')
        import hashlib
        trace=Path(tmp)/'trace';trace.mkdir();raw=trace/'raw.txt';raw.write_text('{"cut":',encoding='utf-8')
        write_json(trace/'attempts.json',[dict(status='output_limit',raw_response_path='raw.txt',
            response_body_sha256=hashlib.sha256(raw.read_bytes()).hexdigest())])
        test.assertTrue(same.settle_attempt(identity,job=Path(tmp),trace=trace))
        test.assertEqual('received',same.read()['requests'][identity]['status'])
        test.assertEqual(1,same.read()['tool_calls'],'A received truncated result is not refunded')
        unsent=same.reserve('tool_calls');same.physical(unsent,0);same.settle(unsent,known_unsent=True);same.settle(unsent,known_unsent=True)
        test.assertEqual(3,same.remaining('tool_calls'))
        for _ in range(3):same.settle(same.reserve('tool_calls'),result_path='fixture-received.json')
        with test.assertRaises(PlanningBudgetError):same.reserve('tool_calls')
        same.grant(kind='tool_calls',additional=1,reason='Explicit test authorization',grant_id='operator-1')
        same.grant(kind='tool_calls',additional=1,reason='Explicit test authorization',grant_id='operator-1')
        test.assertEqual(1,same.remaining('tool_calls'))
        damaged=same.read();damaged['tool_calls']=0;write_json(path,damaged)
        with test.assertRaises(PlanningBudgetError):same.read()
        isolated=PlanningJournal(Path(tmp)/'risk'/'journal.json',child='B1',scope_key='scope')
        lost=isolated.reserve('plan');isolated.physical(lost,1);isolated.settle(lost)
        isolated.accept_retry_risk(lost,reason='Explicit test acceptance of duplicate cost risk')
        isolated.accept_retry_risk(lost,reason='Idempotent operator repeat')
        test.assertEqual(3,isolated.remaining('plan'))
        test.assertEqual('unknown',isolated.read()['requests'][lost]['resolution']['original_outcome'])
        isolated.reserve('plan');test.assertEqual(2,isolated.remaining('plan'))
        scoped=PlanningJournal(Path(tmp)/'scoped.json',child='B1',scope_key='scope')
        pending=scoped.reserve('tool_calls',context={'roles':['func']});scoped.physical(pending,1);scoped.settle(pending)
        with test.assertRaisesRegex(PlanningBudgetError,'pending/unknown'):
            scoped.reserve('tool_calls',context={'roles':['func','scene']})
        other=scoped.reserve('tool_calls',context={'roles':['main']});scoped.settle(other,result_path='main.json')
        test.assertEqual(2,scoped.remaining('tool_calls'))
        test.assertEqual('unknown',scoped.read()['requests'][pending]['status'])
        from core.visual_design_kit import brief_recovery
        scoped.save_roles({'func':{'phase':'needs_confirmation'}},[])
        with patch('core.visual_design_kit.journal_path',return_value=scoped.path):
            diagnosis=brief_recovery(Path(tmp),'B1','func','tool')
        test.assertEqual('blocked',diagnosis['task_status'])
        test.assertEqual('recover_planning_receipt',diagnosis['next_action'])
        test.assertFalse(diagnosis['remote_request_allowed'])
        shared=PlanningJournal(Path(tmp)/'shared.json',child='B1',scope_key='scope')
        shared.settle(shared.reserve('plan'))
        with test.assertRaisesRegex(PlanningBudgetError,'pending/unknown'):
            shared.reserve('tool_calls',context={'roles':['main']})
        scope={'selected_children':['B1'],'selected_sources':{'B1':[0]},'scope_fingerprint':'scope'}
        config={'created_at':'fixed','seed_asin':'B1','category_id':'bed_frame','marketplace':'US'}
        with patch('core.run_scope.read_run_scope',return_value=scope),patch('core.job.load_job',return_value=config):
            test.assertEqual(journal_scope(Path('one'), 'B1'),journal_scope(Path('relocated'), 'B1'))
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,draft
    import json
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        lost=journal.reserve('tool_calls',context={'roles':['func']});journal.physical(lost,1);journal.settle(lost)
        raw['image_briefs']=[r for r in raw['image_briefs'] if r['role']!='main']
        seen=[]
        def answer(prompt,images,**kwargs):
            roles=feedback_payload(prompt)['required_roles'];seen.extend(roles)
            return json.dumps({'decisions':[dict(role=r,action='supply_plan',image_brief={k:v for k,v in draft(r).items() if k!='source_id'}) for r in roles]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer):result=finish(job,sources,raw,regions)
        test.assertEqual(['main'],seen)
        test.assertEqual('ready',next(b for b in result['image_briefs'] if b['role']=='main')['status'])
        test.assertEqual('unknown',journal.read()['requests'][lost]['status'])


def verify_source_and_geometry(test):
    import tempfile
    from pathlib import Path
    from tests.test_visual_flow_contract import source,draft
    from core.image_reference_context import source_usability
    from core.image_task_inputs import initial_output_inventory,task_specs
    from core.visual_design_kit_compiler import collect_brief_issues
    from tests.current_image_contract_fixture import current_art_direction
    from core.sam_diagnostics import geometry_revision
    sources=[source('main'),source('scene','source_01')]
    inventory=initial_output_inventory(sources);sources[1]['observation'].update(objects=[],product_features=[])
    test.assertEqual('needs_source',source_usability(sources[1]['observation'])['status'])
    sources[1]['role']='review_required'
    test.assertEqual(inventory,initial_output_inventory(sources,previous={'output_inventory':inventory}))
    test.assertEqual(len(inventory),len(task_specs({},sources,inventory=inventory,include_optional=True)))
    for bad in (None,[],False,'wrong'):
        planned=draft();planned['image_direction']['presentation']=bad
        test.assertTrue(collect_brief_issues(planned,sources[0],current_art_direction(),sources))
    root=Path(__file__).resolve().parents[1];region=root/'core/product_region.py';worker=root/'scripts/sam31_region_worker.py'
    original=geometry_revision(region,worker)
    with tempfile.TemporaryDirectory() as tmp:
        copy=Path(tmp)/'worker.py';text=worker.read_text(encoding='utf-8')
        copy.write_text(text.replace("_stage('weights_loaded')","_stage('weights_loaded_reworded')")+'\n# logging-only comment\n',encoding='utf-8')
        test.assertEqual(original,geometry_revision(region,copy))
        copy.write_text(text.replace('probs > .45','probs > .46'),encoding='utf-8')
        test.assertNotEqual(original,geometry_revision(region,copy))

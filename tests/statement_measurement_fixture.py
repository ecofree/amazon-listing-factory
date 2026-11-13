"""Explicit text-only size declarations; no real model, original job, or quality claim."""
from contextlib import ExitStack,redirect_stdout
from copy import deepcopy
import importlib.util,json
from unittest.mock import patch
from io import StringIO


def verify_statement_measurements(test,*,annotation_mode='text_only'):
    test.assertIsNotNone(importlib.util.find_spec('core.measurement_sources'),'A typed statement source needs the existing measurement authority, not fake image measurements')
    from core.measurement_sources import configure_statement_measurements,measurement_authority
    from tests.test_image_branch_v1 import classified_workspace,_Plugin,_family,_planner_payload,_fixture_observation
    from tests.current_image_contract_fixture import planner_wire
    from tests.test_visual_flow_contract import draft,protect
    from core import visual_design_kit as kits
    from core.final_source_intents import build_final_source_intents,read_final_source_intents
    from core.image_tasks import build_image_tasks
    from core.image_prompt_compiler import build_image_prompts
    from core.visual_semantics import source_fact_records
    from core.io import write_json,read_json,file_sha256
    from core.status import input_revision_id
    from core import image_qa
    with classified_workspace() as (job,_),ExitStack() as stack:
        family=_family();child=family['family']['children'][0];asin=child['asin']
        child['specs']['item_depth']='8 in'
        raw={'asin':asin,'title':child['title'],'productDetails':{'Item Depth':'8 inches','Color':'White','Material':'Painted engineered wood'}}
        raw_path=job/'source/apify_raw/US'/f'{asin}.json';write_json(raw_path,raw)
        family.update(category_id='bathroom_cabinet',source={'raw_dir':f'jobs/{job.name}/source/apify_raw/US','raw_sha256':{asin:file_sha256(raw_path)}})
        write_json(job/'job.json',{'protocol_version':'6.0','category_id':'bathroom_cabinet','product_type':'BATHROOM_CABINET',
            'seed_asin':asin,'brand':'Fixture','sku_prefix':'FIX','marketplace':'US','created_at':'fixture',
            'image_root':str(job/'images'),'r2_prefix':'fixture','design_inputs':{'brand_brief':{},'references':[]}})
        for module in ('core.product_family','core.final_source_intents','core.visual_design_kit','core.image_tasks'):
            stack.enter_context(patch(module+'.read_product_family',return_value=family))
        def observe(job,child,sources,**kwargs):
            rows=_fixture_observation(job,child,sources,**kwargs)
            for row in rows.values():row['child_facts_revision_id']=input_revision_id(source_fact_records(child))
            size=rows.get('source_03')
            if size:size.update(role_guess='scene',has_dimension_lines=False,measurements=[],visible_numbers_or_units=[],text_observations=[],reference_purposes=['feature'])
            return rows
        with patch('core.final_source_intents.observe_child_sources',side_effect=observe):
            test.assertFalse(build_final_source_intents(job_dir=job,plugin=_Plugin())['failures'])
        intents=read_final_source_intents(job,plugin=_Plugin())
        test.assertTrue(all(not row['measurements'] for row in intents))
        with test.assertRaises(ValueError):measurement_authority('size',{'measurement_ids':[]},kits._source_manifest(intents,job=job))
        initial_plan=_planner_payload(intents)
        def initial_pending(prompt,images,**kw):
            test.assertIn('Follow their annotation_mode',prompt)
            test.assertNotIn('no calibrated endpoints, dimension arrows',prompt)
            text=json.dumps(planner_wire(initial_plan));observer=kw['attempt_observer']
            observer({'event':'request_budget','physical_request_count':1});observer({'status':'success','provider':'fixture','model':'fixture','response_text':text});return text
        with patch.object(kits,'gemini_stream_generate',side_effect=initial_pending),patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Missing evidence cannot buy a retry')):
            first=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)['tasks'][0]
        test.assertEqual('pending',next(b for b in first['image_briefs'] if b['role']=='size')['status'])
        request={'child':asin,'role':'size','action':'authorize','source_id':'source_00','fields':['item_depth']}
        if annotation_mode=='declared_diagram':request.update(annotation_mode=annotation_mode,labels={'item_depth':'8"'})
        def files():return {p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
        before=files();preview=configure_statement_measurements(job,_Plugin(),request)
        test.assertEqual('preview',preview['status']);test.assertEqual(before,files())
        from scripts.factory import build_parser,cmd_measurement_source
        input_path=job/'measurement-request.json';write_json(input_path,request)
        args=build_parser().parse_args(['configure-measurement-source','--job',str(job),'--input',str(input_path)])
        test.assertFalse(args.apply)
        cli_before=files()
        with redirect_stdout(StringIO()) as output:test.assertEqual(0,cmd_measurement_source(args))
        test.assertEqual(preview['proposal_sha256'],json.loads(output.getvalue())['proposal_sha256']);test.assertEqual(cli_before,files())
        original_raw=raw_path.read_bytes();original_sha=family['source']['raw_sha256'][asin]
        original_specs=deepcopy(child['specs'])
        try:
            tuple_value='8"D x 30"W x 36"H'
            tuple_raw={**raw,'productDetails':{},'attributes':[{'key':'Item Dimensions D x W x H','value':tuple_value}],
                'productOverview':[{'key':'Product Dimensions','value':tuple_value}]}
            write_json(raw_path,tuple_raw);family['source']['raw_sha256'][asin]=file_sha256(raw_path)
            from core.measurement_sources import _raw_statement
            declaration=_Plugin().merged_config()['image_generation']['statement_measurements']['item_depth']
            _,proofs=_raw_statement(tuple_raw,declaration,'item_depth',{'product.specs.item_depth':'8','product.specs.dimensions':tuple_value})
            test.assertEqual('8 in',proofs[0]['projected']);test.assertEqual(2,len(proofs))
            conflict={**tuple_raw,'productOverview':[{'key':'Product Dimensions','value':'9"D x 30"W x 36"H'}]}
            with test.assertRaises(ValueError):_raw_statement(conflict,declaration,'item_depth',{'product.specs.item_depth':'8 in'})
            diagram_request={**request,'annotation_mode':'declared_diagram','labels':{'item_depth':'8"'}}
            diagram=configure_statement_measurements(job,_Plugin(),diagram_request)['permission']
            evidence=diagram['statements'][0]
            test.assertEqual(tuple_value,evidence['source_attribute_value'])
            test.assertEqual('8 in',evidence['source_value'])
            test.assertEqual('declared_diagram',diagram['annotation_mode']);test.assertEqual('8"',evidence['render_text'])
            with test.assertRaises(ValueError):configure_statement_measurements(job,_Plugin(),{**diagram_request,'labels':{'item_depth':'9"'}})
            from core.measurement_sources import statement_evidence
            typed={**evidence,'id':'statement:fixture','role':'size','origin_kind':'product_statement','annotation_mode':'declared_diagram'}
            authority=measurement_authority('size',{'measurement_ids':['statement:fixture']},[],[{'measurement_statements':[typed]}])
            test.assertEqual('declared_diagram',authority['annotation_mode'])
            from core.image_prompt_compiler import _measurement_content
            wording=_measurement_content(authority,[])
            test.assertIn('schematic',wording);test.assertIn('not calibrated',wording)
            test.assertNotIn('no dimension arrows',wording)
            test.assertEqual({'statement:fixture':typed},statement_evidence({'child':asin,'role':'size','measurement_authority':authority}))
            for value in ('8 x 30 x 36 inches','approximately 8"D x 30"W x 36"H','8"H x 30"W x 36"D'):
                invalid={**raw,'productDetails':{'Product Dimensions':value}}
                write_json(raw_path,invalid);family['source']['raw_sha256'][asin]=file_sha256(raw_path)
                with test.assertRaises(ValueError):configure_statement_measurements(job,_Plugin(),diagram_request)
        finally:
            child['specs']=original_specs;raw_path.write_bytes(original_raw);family['source']['raw_sha256'][asin]=original_sha
        try:
            for invalid in ({**raw,'asin':'B999999999'},
                            {**raw,'productDetails':{'Package Depth':'8 inches'}},
                            {**raw,'productDetails':{},'title':child['title']+' Depth 8 inches'},
                            {**raw,'productDetails':{'Item Depth':'approximately 8 inches'}}):
                write_json(raw_path,invalid);family['source']['raw_sha256'][asin]=file_sha256(raw_path)
                with test.assertRaises(ValueError):configure_statement_measurements(job,_Plugin(),request)
        finally:raw_path.write_bytes(original_raw);family['source']['raw_sha256'][asin]=original_sha
        for bad in ({**request,'fields':['size']},{**request,'child':'B999999999'},{**request,'role':'main'}):
            with test.assertRaises(ValueError):configure_statement_measurements(job,_Plugin(),bad)
        with test.assertRaises(ValueError):configure_statement_measurements(job,_Plugin(),request,apply=True,
            proposal_sha256='0'*64,decision_id='spec-1',reason='Explicit text-only specification')
        from core.planning_journal import journal_path
        budget_before=file_sha256(journal_path(job,asin))
        applied=configure_statement_measurements(job,_Plugin(),request,apply=True,
            proposal_sha256=preview['proposal_sha256'],decision_id='spec-1',reason='Explicit text-only specification')
        test.assertEqual(0,applied['requests_sent']);test.assertEqual(budget_before,file_sha256(journal_path(job,asin)))
        recorded=files()
        configure_statement_measurements(job,_Plugin(),request,apply=True,
            proposal_sha256=preview['proposal_sha256'],decision_id='spec-1',reason='Explicit text-only specification')
        test.assertEqual(recorded,files())
        claims=kits.compact_product_claims(child,job=job,category_id='bathroom_cabinet')
        selected=[s for c in claims for s in c.get('measurement_statements',[]) if s['role']=='size']
        test.assertEqual(1,len(selected));statement=selected[0];test.assertTrue(statement['id'].startswith('statement:'))
        with test.assertRaises(ValueError):measurement_authority('size_02',{'measurement_ids':[statement['id']]},[],claims)
        image_measure={'source_id':'source_03','measurements':[{'source_occurrence':'width'}]}
        with test.assertRaises(ValueError):measurement_authority('size',{'measurement_ids':[statement['id'],'source_03:width']},[image_measure],claims)
        from core.measurement_sources import _statement_quantity,statement_render_text
        test.assertEqual('Declared depth: 9.06 in',statement_render_text({'label':'Declared depth'},'23 cm','text_only'))
        test.assertEqual('9.06"',statement_render_text({'label':'Declared depth'},'23 cm','declared_diagram','9.06"'))
        for label in ('9 inches','23 cm'):
            with test.assertRaises(ValueError):statement_render_text({'label':'Declared depth'},'23 cm','declared_diagram',label)
        from core.plugin import load_plugin
        tree_rules=load_plugin('artificial_tree').merged_config()['image_generation']['statement_measurements']
        tree_value='52.8"D x 52.8"W x 96"H';tree_raw={'attributes':[{'key':'Item Dimensions D x W x H','value':tree_value}]}
        for field,value in (('height','96'),('width','52.8')):
            row,_=_raw_statement(tree_raw,tree_rules[field],field,{'product.specs.'+field:value,'product.specs.dimensions':tree_value})
            test.assertEqual(value+' in',row['projected'])
        fractional='8"D x 30"W x 7 1/2"H';fraction_raw={'attributes':[{'key':'Item Dimensions D x W x H','value':fractional}]}
        with test.assertRaises(ValueError):_raw_statement(fraction_raw,tree_rules['height'],'height',{'product.specs.height':'7','product.specs.dimensions':fractional})
        fraction_row,_=_raw_statement(fraction_raw,tree_rules['height'],'height',{'product.specs.height':'7.5','product.specs.dimensions':fractional})
        test.assertEqual(_statement_quantity('7.5 in')['canonical_pair'],fraction_row['amount']['canonical_pair'])
        test.assertEqual('7 1/2 in',fraction_row['projected'])
        for invalid in ('0 inches','-8 inches','8 x 30 inches','approximately 8 inches','8 inches per shelf'):
            with test.assertRaises(ValueError):_statement_quantity(invalid)
        size=draft('size');size['image_direction'].update(product_sources=['source_00'],measurement_ids=[statement['id']],environment_mode='graphic_canvas',
            visual_goal='Show the declared cabinet depth as standalone text beside the unchanged product photograph.')
        size['display_copy']={'title':None,'labels':[]};size['region_intent']['targets']=protect()['targets']
        def supply(prompt,images,**kw):
            from tests.test_visual_flow_contract import feedback_payload
            payload=feedback_payload(prompt);test.assertEqual(['size'],payload['required_roles'])
            test.assertIn('product_statement',prompt);test.assertIn(statement['id'],prompt)
            test.assertIn('Follow their annotation_mode',prompt)
            test.assertNotIn('or create dimension arrows',prompt)
            wire=deepcopy(size);wire.pop('source_id')
            return json.dumps({'decisions':[{'role':'size','action':'supply_plan','image_brief':wire}]})
        selection=[{'child':asin,'role':'size','visual_design_kit_id':first['visual_design_kit_id']}]
        with patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('Do not repurchase shared planning')),patch('core.planning_feedback.gemini_stream_generate',side_effect=supply) as planner:
            made=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),planning_tasks=selection,workers=1)
        test.assertEqual(1,planner.call_count)
        test.assertEqual([b for b in first['image_briefs'] if b['role']!='size'],[b for b in made['tasks'][0]['image_briefs'] if b['role']!='size'])
        test.assertFalse(made['failures'],made['failures'])
        tasks=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks'];task=next(t for t in tasks if t['role']=='size')
        test.assertEqual('ready',task['formation_status'],task.get('formation_reason'))
        test.assertEqual('product_statement',task['measurement_authority']['mode'])
        test.assertEqual('statement_size_visual_restyle',task['execution_profile'])
        test.assertEqual(['source_00'],[r['source_id'] for r in task['generation_references']])
        test.assertTrue(all(r['kind']!='measurement_evidence' for r in task['generation_references']))
        group=task['measurement_authority']['measurement_groups'][0]
        test.assertEqual('depth',group['axis']);test.assertEqual(annotation_mode,group['annotation_mode'])
        test.assertEqual('8 inches',group['source_text'])
        prompts=build_image_prompts(job_dir=job,plugin=_Plugin())['prompts'];prompt=next(p['prompt'] for p in prompts if p['role']=='size')
        if annotation_mode=='text_only':
            test.assertIn('text-only product statements',prompt);test.assertIn('no dimension arrows',prompt)
        else:
            test.assertIn('schematic dimension arrows',prompt);test.assertIn('not calibrated',prompt)
            test.assertEqual('8"',group['render_text'])
        test.assertNotIn('Place each label and arrow on its measured object',prompt)
        test.assertIn(group['render_text'],task['renderable_text_contract']['strings'])
        required=image_qa._factual_checks(task,{'revision_mode':'initial'})
        test.assertIn('dimension_accuracy',required)
        rows=[{'check':name,'status':'pass','candidate_observation':'Synthetic candidate observation for this check.',
               'reference_observation':'Synthetic same-child reference comparison for this check.',
               'source_ids':['source_00'],'reason':'Synthetic factual fixture only, not real image acceptance.'} for name in required]
        with test.assertRaises(ValueError):image_qa._parse_factual_gates(json.dumps({'checks':rows}),required,{'source_00'},statement_ids={statement['id']})
        next(r for r in rows if r['check']=='dimension_accuracy')['source_ids']=[statement['id']]
        image_qa._parse_factual_gates(json.dumps({'checks':rows}),required,{'source_00'},statement_ids={statement['id']})
        from tests.role_restore_fixture import _candidate
        _,manifest=_candidate(job,task,next(p for p in prompts if p['role']=='size'))
        candidate={'candidate_path':manifest['candidate_path'],'candidate_sha256':manifest['candidate_sha256'],'candidate_revision':0,'revision_mode':'initial'}
        def qa(prompt,images,**kw):
            test.assertEqual(2,len(images),'Raw statement JSON must not become an image attachment')
            test.assertTrue(all(p.suffix=='.png' for p in images))
            test.assertIn('NOT image measurements',prompt)
            return json.dumps({'checks':rows})
        with patch('core.vision_gemini_client.gemini_stream_generate',side_effect=qa) as model:
            gates,_=image_qa._factual_gates(job,task,candidate)
        test.assertEqual(1,model.call_count);test.assertTrue(all(g['status']=='pass' for g in gates),gates)
        from core.measurement_sources import statement_evidence
        from core.release_manifest import _validate_resolutions,ReleaseManifestError
        target={'candidate_sha256':candidate['candidate_sha256'],'source_sha256':task['source_sha256'],
                'unresolved_checks':['dimension_accuracy'],'statement_evidence':statement_evidence(task)}
        resolution={'check':'dimension_accuracy','candidate_sha256':candidate['candidate_sha256'],'source_sha256':task['source_sha256'],
                    'conclusion':'confirmed','evidence':'Synthetic operator checked the declared source values.'}
        with test.assertRaises(ReleaseManifestError):_validate_resolutions([resolution],target)
        resolution['statement_sources']={statement['id']:statement['raw_source']['sha256']};_validate_resolutions([resolution],target)
        original=raw_path.read_bytes();raw_path.write_bytes(original+b' ')
        with patch('core.vision_gemini_client.gemini_stream_generate',side_effect=AssertionError('Changed raw evidence must stop before QA')) as model:
            invalid,_=image_qa._factual_gates(job,task,candidate)
        model.assert_not_called();test.assertTrue(all(g['status']=='inconclusive' for g in invalid))
        test.assertFalse(any(c.get('measurement_statements') for c in kits.compact_product_claims(child,job=job,category_id='bathroom_cabinet')))
        raw_path.write_bytes(original)
        from core.template_contract import template_input_fingerprint
        workbook=job/'fixture.xlsm';workbook.write_bytes(b'synthetic workbook identity only')
        def template_identity():return template_input_fingerprint(job_path=job,template_path=workbook,output_path=workbook,
            mode='submit_ready',write_excel=True,job=read_json(job/'job.json'),plugin_config=_Plugin().merged_config(),image_bindings={})
        template_before=template_identity()
        revoked={'child':asin,'role':'size','action':'revoke'};proposal=configure_statement_measurements(job,_Plugin(),revoked)
        configure_statement_measurements(job,_Plugin(),revoked,apply=True,proposal_sha256=proposal['proposal_sha256'],decision_id='spec-revoke',reason='Withdraw only text-source permission')
        test.assertNotEqual(template_before,template_identity(),'Revocation must invalidate an otherwise unchanged workbook contract')
        current=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
        test.assertEqual('blocked',next(t for t in current if t['role']=='size')['formation_status'])
        for role in ('main','scene','func'):
            test.assertEqual(next(t for t in tasks if t['role']==role)['task_fingerprint'],next(t for t in current if t['role']==role)['task_fingerprint'])

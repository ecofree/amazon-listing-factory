"""Current source, transport, style and QA boundaries after planner-loop replacement."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from core.io import read_json,file_sha256,write_json
from tests.current_image_contract_fixture import (current_art_direction,current_image_task,current_product_feature,
    current_measurement_rows,current_observed_measurement,observation_wire,write_observation_images)


class VisualDesignRemediationTests(unittest.TestCase):
    def test_source_observation_unknown_stops_across_revisions(self):
        from core.visual_semantics import observe_child_sources
        from core.vision_errors import VisionRequestError
        from tests.test_image_branch_v1 import _child
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);sources=[dict(source_id='source_00',sha256='a'*64,ocr=[],path=job/'source.png')]
            write_observation_images(sources)
            def lost(*args,**kwargs):
                kwargs['attempt_observer']({'event':'request_budget','physical_request_count':1})
                raise VisionRequestError('visual_planning','timeout_failure','Reply lost after submission',metadata={'physical_request_count':1})
            with patch('core.visual_semantics.gemini_stream_generate',side_effect=lost) as model:
                first=observe_child_sources(job,_child(),sources)
                self.assertEqual(1,model.call_count)
                self.assertEqual('failed',first['source_00']['status'])
                observe_child_sources(job,_child(),sources)
                changed=deepcopy(_child());changed['specs']['Color']='Black'
                observe_child_sources(job,changed,sources,corrections={'source_00':{'revision':'new','reason':'New evidence'}})
                self.assertEqual(1,model.call_count,'A revision is not permission to repeat an unknown POST')
                receipts=list((job/'reports/source_observations/requests').glob('*.json'))
                self.assertEqual(1,len(receipts));self.assertEqual('unknown',read_json(receipts[0])['status'])
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);sources=[dict(source_id='source_00',sha256='a'*64,ocr=[],path=job/'source.png')]
            write_observation_images(sources)
            write_json(job/'reports/source_observations'/('c'*64+'.json'),{
                'child':'different-child','request_attempts':1,'sources':[{'source_id':'source_00','status':'failed'}]})
            def rejected(*args,**kwargs):
                kwargs['attempt_observer']({'event':'request_budget','physical_request_count':1})
                kwargs['attempt_observer']({'status':'configuration_failure','response_body':'{"error":"insufficient_balance"}',
                    'transport':{'response_complete':True,'request_outcome':'rejected'}})
                raise VisionRequestError('visual_planning','configuration_failure','Complete HTTP 402 rejection',metadata={'physical_request_count':1})
            with patch('core.visual_semantics.gemini_stream_generate',side_effect=rejected) as model:
                for _ in range(2):
                    result=observe_child_sources(job,_child(),sources)
                    self.assertEqual('configuration_failure',result['source_00']['request_failure']['kind'])
                self.assertEqual(1,model.call_count,'A known account rejection is not a schema-repair request')
            receipts=list((job/'reports/source_observations/requests').glob('*.json'))
            self.assertEqual(1,len(receipts));self.assertEqual('received',read_json(receipts[0])['status'])

    def test_original_references_and_execution_permissions_remain_bound(self):
        from tests.convergence_fixture import verify_gateway_admission,verify_recovery_and_binding
        from tests.generation_selection_fixture import verify_execution_selection
        from tests.sam_worker_fixture import verify_sam_worker_lifecycle
        verify_gateway_admission(self);verify_recovery_and_binding(self);verify_execution_selection(self);verify_sam_worker_lifecycle(self)
        from tests.generation_selection_fixture import _workspace,_snapshot
        from core import production
        from core.visual_design_kit import VisualDesignKitError
        with _workspace() as (job,plugin,tasks):
            (job/'reports/visual_design_kits_v16.jsonl').write_text('{}\n',encoding='utf-8')
            before=_snapshot(job)
            with patch.object(production,'begin_run') as begin,patch.object(production,'_run_stage') as execute:
                with self.assertRaisesRegex(VisualDesignKitError,'Retired visual-plan'):
                    production.run_job(production.JobRunRequest(job_dir=job,plugin=plugin),stages=['classify','brief','generate'])
                begin.assert_not_called();execute.assert_not_called()
            self.assertEqual(before,_snapshot(job))
        from PIL import Image
        from core.image_reference_context import prepare_planning_references
        from tests.test_visual_flow_contract import source
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);Image.new('RGB',(1000,1500),'white').save(job/'source.png')
            row=source();row['source_sha256']=file_sha256(job/'source.png')
            self.assertEqual([job/'source.png'],prepare_planning_references(job,[row],job/'trace'))
            other=deepcopy(row);other['source_id']='source_01'
            with self.assertRaisesRegex(ValueError,'one reliable'):
                prepare_planning_references(job,[row,other],job/'ambiguous')
            row['observation']['reference_purposes']=['feature']
            self.assertEqual([job/'source.png'],prepare_planning_references(job,[row,other],job/'selected'))
            self.assertEqual([1,1],[r['attachment_number'] for r in read_json(job/'selected/manifest.json')['attachments']])
            row['source_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'Source changed'):
                prepare_planning_references(job,[row,other],job/'stale')

    def test_observed_measurements_and_post_generation_hard_gates_remain_independent(self):
        from core.final_source_intents import _observed_measurements,_measurement_rows
        from core.measurement_sources import measurement_authority
        from core.visual_semantics import OBSERVATION_POLICY,_validate_source_measurements
        from core.image_prompt_compiler import _measurement_content
        visual=dict(status='success',policy_version=OBSERVATION_POLICY,measurements=[current_observed_measurement(),
            current_observed_measurement('300 lbs','Bed capacity','capacity',key='load',kind='capacity')])
        source=dict(source_id='source_00',role='size',measurements=_measurement_rows(_observed_measurements(visual),{}))
        authority=measurement_authority('size',{'measurement_ids':['source_00:width','source_00:load']},[source])
        self.assertEqual(['17 in','300 lbs'],authority['render_text']);self.assertEqual('load_capacity',authority['measurement_groups'][1]['measurement_role'])
        repeated=[visual['measurements'][0],{**visual['measurements'][0],'text':'17 ft'}]
        with self.assertRaisesRegex(ValueError,'competing readings'):_validate_source_measurements(repeated)
        for text in ('\u2264 6"','6-8 in','6 in to 8 in'):
            visual['measurements']=[current_observed_measurement(text,'Recommended mattress thickness',key='mattress')]
            _validate_source_measurements(visual['measurements'])
            source['measurements']=_measurement_rows(_observed_measurements(visual),{})
            selected=measurement_authority('func',{'measurement_ids':['source_00:mattress']},[source])
            self.assertEqual(text,selected['render_text'][0]);self.assertIn('Recommended mattress thickness',_measurement_content(selected,[{'kind':'measurement_evidence','source_id':'source_00'}]))
        same=current_measurement_rows()[0]
        source['measurements']=[dict(same,source_occurrence='upper'),dict(same,source_occurrence='lower')]
        selected=measurement_authority('func',{'measurement_ids':['source_00:upper','source_00:lower']},[source])
        self.assertEqual(2,len(selected['measurement_groups']));self.assertEqual(1,len(selected['render_text']))

    def test_native_json_trace_and_complete_copy_repair_are_preserved(self):
        from core.vision_gemini_client import (_gemini_native_payload,_parse_sse_text_candidates,_parse_generate_content_candidates,
            _response_finish_reasons,_select_response_candidate,_response_failure_kind,_response_retry_prompt,_response_usage)
        from core.visual_semantics import _attempt_trace
        payload={'candidates':[{'content':{'parts':[{'thought':True,'text':'{"draft":1}'},{'text':'{"sources":[]}'}]},'finishReason':'STOP'}]}
        body=json.dumps(payload)
        self.assertEqual(['STOP'],_response_finish_reasons(body));self.assertEqual(['length'],_response_finish_reasons('data: {"choices":[{"finish_reason":"length"}]}'))
        self.assertEqual(['{"sources":[]}'],_parse_generate_content_candidates(body));self.assertEqual(['{"sources":[]}'],_parse_sse_text_candidates('data: '+body))
        config=_gemini_native_payload([],{'protocol':'google_gemini','max_output_tokens':'12000'})
        self.assertEqual('application/json',config['generationConfig']['responseMimeType']);self.assertEqual(12000,config['generationConfig']['maxOutputTokens'])
        limited=json.dumps({'candidates':[{'finishReason':'MAX_TOKENS'}],'usageMetadata':{'candidatesTokenCount':8192}})
        self.assertIsNone(_select_response_candidate(['{}'],lambda text:True,response_body=limited)[1])
        self.assertEqual('output_limit',_response_failure_kind(limited,'JSONDecodeError'))
        endpoint={'max_output_tokens':8192};self.assertEqual('original',_response_retry_prompt(endpoint,'original','cut','partial','output_limit'))
        self.assertEqual(16384,endpoint['max_output_tokens']);self.assertEqual({'candidatesTokenCount':8192},_response_usage(limited))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'attempts.json';_,record=_attempt_trace(path)
            record(dict(status='validation_failure',response_text='{"sources":[',response_candidates=[{'validation_error':'incomplete object'}]))
            event=read_json(path)[0];self.assertEqual('{"sources":[',(path.parent/event['response_path']).read_text())
            self.assertEqual(['incomplete object'],event['validation_errors'])
            _,record=_attempt_trace(path);record(dict(status='success',response_text='{}'))
            self.assertEqual(2,len(read_json(path)));self.assertNotEqual(read_json(path)[0]['response_path'],read_json(path)[1]['response_path'])
        from core.planning_contract import compact_schema,obj,array,text
        from jsonschema import Draft202012Validator
        part=obj({'value':text(200),'fixed':{'const':{'nested':{'type':'literal data'}}},'tags':array({'enum':['one','two']},1,3)})
        schema=obj({'a':part,'b':part,'c':part});compressed=compact_schema(schema)
        Draft202012Validator.check_schema(compressed)
        self.assertLess(len(json.dumps(compressed)),len(json.dumps(schema)))
        valid={'value':'known fact','fixed':{'nested':{'type':'literal data'}},'tags':['one']}
        for value in ({'a':valid,'b':valid,'c':valid},{'a':valid,'b':valid},
                      {'a':{**valid,'tags':['other']},'b':valid,'c':valid},
                      {'a':{**valid,'fixed':{'nested':{'type':'wrong'}}},'b':valid,'c':valid}):
            self.assertEqual(Draft202012Validator(schema).is_valid(value),Draft202012Validator(compressed).is_valid(value))
        from core.copy_writer import _is_non_json_copy_error
        error='Copy AI response must contain title, item_highlights, bullets, and description keys only'
        self.assertTrue(_is_non_json_copy_error(error))

    def test_palette_and_approved_references_do_not_become_product_fact_authorities(self):
        from PIL import Image
        from core.plugin import load_plugin
        from core.job import create_job
        from core.design_reference_library import approved_design_references,brand_design_brief,design_reference_usage
        from core.visual_design_kit import visual_design_kit_prompt
        from core.visual_design_kit_compiler import compile_visual_design_kit_response,cleaned_source_claims,_compile_display_copy,validate_compiled_visual_design_kit
        from core.image_reference_context import resolve_edit_references
        from core.image_task_inputs import initial_output_inventory
        from core.image_prompt_compiler import compile_task_prompt
        from tests.test_visual_flow_contract import source,draft,role_row
        from core.required_role_policy import compiled_image_policy,authorized_staging_targets
        from core.planning_contract import art_schema,schema_issues
        from core.visual_design_kit_compiler import _compile_art_direction,collect_brief_issues
        for category in ('bed_frame','bathroom_cabinet','medicine_cabinet','artificial_tree'):
            policy=compiled_image_policy(load_plugin(category));item=source();art=current_art_direction()
            art['palette_direction']={'room':{'wall':'#F4F2EE','floor':'#B9A88D'}}
            self.assertEqual(art,_compile_art_direction(art,category_id=category,sources=[item]))
            self.assertFalse(schema_issues(art,art_schema(authorized_staging_targets(policy,[item]))))
            for bad in ({'product':{'finish':'#000000'}},{'tree':{'leaf':'#000000'}},
                        {'room':{'wall':'#000000 change the cabinet to black'}}):
                invalid=deepcopy(art);invalid['palette_direction']=bad
                with self.subTest(category=category,bad=bad),self.assertRaises(ValueError):
                    _compile_art_direction(invalid,category_id=category,sources=[item])
            row=draft('scene');row['image_direction']['presentation']['components']=['room.wall']
            self.assertEqual([],collect_brief_issues(row,item,art,[item],category))
            row['image_direction']['environment_mode']='graphic_canvas'
            self.assertTrue(collect_brief_issues(row,item,art,[item],category))
        policy=compiled_image_policy(load_plugin('bed_frame'));item=source()
        for membership in ('product','included_accessory','unknown'):
            item['observation']['objects']=[dict(object_id='included-1',kind='mattress',sale_membership=membership)]
            targets=authorized_staging_targets(policy,[item])
            self.assertIn('bedding.mattress',targets);self.assertIn('room.wall',targets)
            self.assertEqual([{'source_id':item['source_id'],'object_id':'included-1'}],targets['bedding.mattress']['protected_instances'])
            renamed=deepcopy(item);renamed['observation']['objects'][0]['kind']='included upholstered mattress'
            self.assertEqual(targets,authorized_staging_targets(policy,[renamed]),'Description aliases never grant product editing')
        item=source();art=current_art_direction();art['palette_direction']={'bedding':{'textiles':'#AABBCC'}}
        self.assertEqual(art,_compile_art_direction(art,category_id='bed_frame',sources=[item]))
        target=current_image_task('scene',category_id='bed_frame');target['category_image_policy']=policy
        target['family_art_direction']=art;target['image_direction']['presentation']['components']=['bedding.textiles']
        compiled=compile_task_prompt(task=target)
        self.assertIn('Non-sold sheets, blankets, pillows and cushions = #AABBCC',compiled)
        self.assertNotIn('Target components:',compiled)
        target['family_art_direction']['palette_direction']={'room':{'wall':'#000000 recolor the bed frame'}}
        with self.assertRaisesRegex(ValueError,'strict'):compile_task_prompt(task=target)
        policy=compiled_image_policy(load_plugin('bathroom_cabinet'))
        self.assertEqual({},authorized_staging_targets(policy,role='main',environment_mode='designed_environment'))
        words=source();words['claims']=[dict(evidence_id=str(i),text=text) for i,text in enumerate(('Pathway','Wedding','Q','T o','\ufffd'))]
        self.assertEqual(['Pathway','Wedding'],[r['text'] for r in cleaned_source_claims(words)])
        self.assertEqual(['Pathway'],_compile_display_copy([words],dict(title=None,labels=[dict(text='Pathway',evidence_ids=['0'],target=None)]))['labels'])
        plugin=load_plugin('bed_frame')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=Image.new('RGB',(32,32),'magenta');image.paste('white',(8,8,24,24));image.save(root/'owned.png')
            approval=dict(status='approved',approved_by='fixture',approved_at='2026-09-11',allowed_uses=['image_generation_reference'],license_evidence='Test-generated pixels')
            visual={**approval,'product_clarity':'Clear field','information_hierarchy':'Test hierarchy','evidence_fit':'No new product geometry',
                'series_cohesion':'Shared typography','transfer_scope':'Only the central blank area'}
            asset=dict(asset_id='owned-layout',roles=['func'],children=['B1'],local_path='owned.png',sha256=file_sha256(root/'owned.png'),
                author='test',source_url='local-fixture',asset_license='test-owned',rights_review=approval,visual_review=visual,
                reference_region=[.25,.25,.75,.75],purpose='Asymmetric hierarchy and breathing room')
            write_json(root/'pack.json',dict(schema_version='design-pack-v4',pack_id='fixture',version='1',approval_scope='production',
                status='approved',production_ready=True,design_system='Test visual hierarchy',compatibility={'categories':['bed_frame']},assets=[asset]))
            write_json(root/'brief.json',{'positioning':'quiet modern residential'})
            job=create_job(plugin=plugin,seed_asin='B000000001',brand='safeplus',sku_prefix='test',out_root=root/'jobs',
                design_pack_path=str(root/'pack.json'),brand_brief_path=str(root/'brief.json'))
            refs=approved_design_references(job,'B1');self.assertEqual([],approved_design_references(job,'B2'))
            with Image.open(job/refs[0]['path']) as cropped:self.assertEqual((16,16),cropped.size);self.assertEqual({(255,255,255)},set(cropped.getdata()))
            item=source();Image.new('RGB',(100,100),'white').save(job/'source.png');item['source_sha256']=file_sha256(job/'source.png')
            row=draft();row['image_direction']['design_transfer']=[dict(reference_id='owned-layout',inherit='Use the approved hierarchy',adapt='Keep the existing product view')]
            kit=compile_visual_design_kit_response(dict(family_art_direction=current_art_direction(),image_briefs=[row]),source_manifest=[item],
                output_inventory=initial_output_inventory([item]),design_references=refs)
            brief=role_row(kit);self.assertEqual('ready',brief['status'],brief.get('error'))
            changed=deepcopy(refs);changed[0]['roles']=['scene']
            with self.assertRaisesRegex(ValueError,'not approved'):validate_compiled_visual_design_kit(kit,source_manifest=[item],design_references=changed)
            prompt=visual_design_kit_prompt(plugin,{},dict(main_image_policy='product_first_lifestyle'),[item],refs,brand_design_brief(job),output_inventory=initial_output_inventory([item]))
            self.assertIn('quiet modern residential',prompt);self.assertNotIn('license_evidence',prompt)
            self.assertIn('Prefer no people or human reflections',prompt)
            self.assertIn('ONE child-wide typography and graphic ink system',prompt)
            from core.image_tasks import _edit_contract
            for category in ('bed_frame','bathroom_cabinet','medicine_cabinet','artificial_tree'):
                policy=compiled_image_policy(load_plugin(category))
                for role in ('scene','func','size'):
                    task=current_image_task(role,category_id=category)
                    task['edit_contract']=_edit_contract(role,task['measurement_authority'],policy)
                    sent=compile_task_prompt(task=task)
                    self.assertIn('visibly different person, appearance and clothing',sent)
                    self.assertIn('remove incidental source families',sent)
                    if role in ('func','size'):
                        self.assertIn('text_color = #303634',sent)
                        self.assertIn('shared child-wide graphic colors',sent)
                white=_edit_contract('main',{},compiled_image_policy(load_plugin('artificial_tree')))
                self.assertIn('remove people and reflected people',str(white))
            references=resolve_edit_references(brief,[item],job=job,child='B1',design_references=refs)
            self.assertEqual(['edit_base','design_reference'],[r['kind'] for r in references])
            task=current_image_task('func');task['generation_references']=references;task['image_direction']['design_transfer']=row['image_direction']['design_transfer']
            compiled=compile_task_prompt(task=task);self.assertIn(visual['transfer_scope'],compiled)
            self.assertEqual(1,compiled.count('Use the approved hierarchy'))
            self.assertEqual('external_reference_selected',design_reference_usage(job,refs,[brief])['roles'][0]['status'])

    def test_vision_admission_and_source_failure_isolation(self):
        from tests.audit_delivery_fixture import verify_safe_redirects
        verify_safe_redirects(self)
        _verify_transport_deadline(self)
        from core import vision_gemini_client as client
        from core.image_provider_common import ProviderQueueUnavailable
        from core.visual_semantics import _validate_observations,observe_child_sources
        from tests.test_image_branch_v1 import _evidence,_child
        events=[]
        @contextmanager
        def slot(*args,**kwargs):events.append('admitted');yield
        def payload():events.append('encoded');return {'text':'fixture'}
        endpoint=dict(name='primary',base_url='https://fixture.invalid/v1',api_key='fixture')
        with patch.object(client,'provider_concurrency_slot',side_effect=slot),patch.object(client,'_post_json_preserve_redirects',return_value='ok'), \
             patch('core.batch_ledger.admit_paid_request',return_value='mock-network-admission'):
            self.assertEqual('ok',client._post_vision_request(endpoint,'https://fixture.invalid',payload,headers={},timeout_seconds=5,deadline=time.monotonic()+10,on_submit=lambda:events.append('submitted')))
        self.assertEqual(['admitted','encoded','submitted'],events)
        with patch.object(client,'provider_concurrency_slot',side_effect=ProviderQueueUnavailable('fixture','busy')),patch.object(client,'_post_json_preserve_redirects') as network:
            with self.assertRaises(ProviderQueueUnavailable):client._post_vision_request(endpoint,'https://fixture.invalid',payload,headers={},timeout_seconds=5,deadline=time.monotonic()+1,on_submit=lambda:events.append('submitted'))
            network.assert_not_called()
        self.assertEqual(['admitted','encoded','submitted'],events)
        with patch.object(client,'MAX_VISION_REQUEST_BYTES',8,create=True), \
             patch.object(client,'provider_concurrency_slot',side_effect=slot), \
             patch('core.batch_ledger.admit_paid_request') as paid, \
             patch.object(client,'_post_json_preserve_redirects') as network:
            with self.assertRaises(client.VisionRequestError) as rejected:
                client._post_vision_request(endpoint,'https://fixture.invalid',lambda:{'text':'x'*50},
                    headers={},timeout_seconds=5,deadline=time.monotonic()+10,on_submit=lambda:events.append('submitted'))
            self.assertEqual(0,rejected.exception.metadata['physical_request_count'])
            network.assert_not_called();paid.assert_not_called()
        with patch.object(client,'provider_concurrency_slot',side_effect=slot), \
             patch('core.batch_ledger.admit_paid_request',return_value='bounded-large-mock'), \
             patch.object(client,'_post_json_preserve_redirects',return_value='ok') as network:
            self.assertEqual('ok',client._post_vision_request(endpoint,'https://fixture.invalid',
                lambda:{'text':'x'*4_300_000},headers={},timeout_seconds=5,
                deadline=time.monotonic()+10,on_submit=lambda:None))
            self.assertGreater(network.call_args.args[1].__len__(),4*1024*1024)
        valid={**_evidence('main')['visual_evidence'],'source_id':'source_00'}
        bad=deepcopy(valid);bad.update(source_id='source_01',evidence_gaps='not a list',visible_numbers_or_units=[{}])
        from core.visual_semantics import source_fact_records
        checked=_validate_observations([valid,bad],['source_00','source_01'],source_fact_records(_child()))
        self.assertEqual(['success','failed'],[checked[k]['status'] for k in ('source_00','source_01')])
        for fields,value in ((('objects',0,'membership_evidence'),[{'fact_id':'product.title','quote':17}]),
                (('objects',0,'sale_membership'),[]),(('role_guess',),[]),(('variant_identity','status'),[]),
                (('text_observations',),17),(('product_extent',),[]),(('product_features',0,'feature_id'),[]),
                (('reference_purposes',),[[]]),(('text_gaps',),[dict(text='Unreadable width',kind=[])])):
            malformed=deepcopy(valid);malformed['source_id']='source_01';target=malformed
            for field in fields[:-1]:target=target[field]
            target[fields[-1]]=value
            checked=_validate_observations([valid,malformed],['source_00','source_01'],source_fact_records(_child()))
            self.assertEqual(['success','failed'],[checked[k]['status'] for k in ('source_00','source_01')])
        repaired={**deepcopy(valid),'source_id':'source_01','reference_purposes':['feature']}
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);sources=[dict(source_id=f'source_0{i}',sha256=str(i)*64,ocr=[],path=job/f'{i}.png') for i in range(2)]
            write_observation_images(sources)
            clock=[1000.0];responses=[observation_wire([valid,bad]),observation_wire([repaired])]
            def slow_observation(*args,**kwargs):
                self.assertGreaterEqual(kwargs['deadline_monotonic']-clock[0],120)
                clock[0]+=84  # Real first response left only 16 seconds under the retired 100-second cap.
                return json.dumps(responses.pop(0))
            with patch('core.visual_semantics.time.monotonic',side_effect=lambda:clock[0]), \
                 patch('core.visual_semantics.gemini_stream_generate',side_effect=slow_observation) as model:
                result=observe_child_sources(job,_child(),sources)
                self.assertTrue(all(r['status']=='success' for r in result.values()))
                self.assertEqual([sources[1]['path']],model.call_args.args[1])
                observe_child_sources(job,_child(),sources);self.assertEqual(2,model.call_count)
            cache=next(path for path in (job/'reports/source_observations').glob('*.json') if len(path.stem)==64)
            saved=read_json(cache);saved.update(request_attempts=4,attempts_used={'source_00':4,'source_01':4});write_json(cache,saved)
            corrections={'source_00':dict(revision='operator-1',reason='Correct the source observation')}
            def correction(*args,**kwargs):
                kwargs['attempt_observer']({'event':'request_budget','physical_request_count':1})
                return json.dumps(observation_wire([valid]))
            with patch('core.visual_semantics.gemini_stream_generate',side_effect=correction) as model:
                parent_deadline=time.monotonic()+7
                result=observe_child_sources(job,_child(),sources,corrections=corrections,deadline_monotonic=parent_deadline)
                self.assertEqual(parent_deadline,model.call_args.kwargs['deadline_monotonic'])
                self.assertEqual('operator-1',result['source_00']['correction_revision'])
                observe_child_sources(job,_child(),sources,corrections=corrections);self.assertEqual(1,model.call_count)
                self.assertEqual(5,read_json(cache)['request_attempts'])
                self.assertEqual(6,read_json(cache)['correction_allowances']['operator-1']['request_ceiling'])


def _verify_transport_deadline(test):
    # Cold optional-backend imports can exceed this fixture's two-second wire
    # deadline on Windows. Warm imports only; request/deadline bounds stay unchanged.
    import anyio._backends._asyncio
    import httpcore._backends.anyio
    from core import vision_gemini_client as client
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from http.client import IncompleteRead
    from threading import Thread
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path=='/upload':time.sleep(.4);return
            self.rfile.read(int(self.headers.get('Content-Length','0')))
            if self.path=='/headers':time.sleep(.4)
            body=b'{"error":{"type":"insufficient_balance"}}' if self.path=='/balance' else b'{}'
            self.send_response(402 if self.path.startswith('/error') or self.path=='/balance' else 200)
            self.send_header('x-request-id','fixture-gateway-id')
            self.send_header('Content-Length',str(len(body)) if self.path in {'/ok','/error','/balance'} else '100');self.end_headers()
            try:
                if self.path in {'/ok','/truncated','/error','/balance'}:self.wfile.write(body)
                else:
                    for _ in range(20):self.wfile.write(b'x');self.wfile.flush();time.sleep(.04)
            except ConnectionError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=lambda:server.serve_forever(poll_interval=.01),daemon=True);thread.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}'
        audit={}
        test.assertEqual('{}',client._post_json_preserve_redirects(url+'/ok',{}, {},timeout_seconds=2,audit=audit))
        test.assertEqual('fixture-gateway-id',audit['response_headers']['x-request-id'])
        with test.assertRaises(IncompleteRead):client._post_json_preserve_redirects(url+'/truncated',{}, {},timeout_seconds=2)
        with test.assertRaises(client.urllib.error.HTTPError) as rejected:
            client._post_json_preserve_redirects(url+'/error',{}, {},timeout_seconds=2,audit=audit)
        test.assertEqual(402,rejected.exception.code)
        test.assertEqual(b'{}',rejected.exception.read())
        for route in ('error','balance'):
            audit={}
            with test.assertRaises(client.urllib.error.HTTPError):
                client._post_json_preserve_redirects(url+'/'+route,{}, {},timeout_seconds=2,audit=audit)
            test.assertTrue(audit['response_complete'])
            test.assertEqual('rejected' if route=='balance' else 'unknown',audit['request_outcome'])
            event=client._emit_attempt(None,request_id='fixture',client={'_transport':audit},model='fixture',protocol='test',
                attempt=1,status='transport_failure',started=time.monotonic())
            test.assertTrue(event['response_body_sha256']);test.assertIn('error' if route=='balance' else '{}',event['response_body'])
            test.assertNotIn('_response_body',event['transport'])
        for route in ('slow','headers','error-slow','upload'):
            started=time.monotonic()
            payload={'padding':'x'*3_000_000} if route=='upload' else {}
            with test.assertRaises(TimeoutError):
                client._post_json_preserve_redirects(url+'/'+route,payload,{},timeout_seconds=2,deadline=started+.15)
            test.assertLess(time.monotonic()-started,.6,route)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=1)
    endpoint=dict(name='primary',base_url='https://fixture.invalid/v1',api_key='fixture')
    alias={**endpoint,'name':'alias','model':'different-model'};other={**endpoint,'name':'other','base_url':'https://other.invalid/v1'}
    with patch.object(client,'gemini_clients',return_value=[endpoint,alias,other]),patch.object(client,'provider_concurrency_limit',return_value=1):
        test.assertEqual(client._vision_resource(endpoint)[1],client._vision_resource(alias)[1]);test.assertNotEqual(client._vision_resource(endpoint)[1],client._vision_resource(other)[1])


if __name__=='__main__':
    unittest.main()

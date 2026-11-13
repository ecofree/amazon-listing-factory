"""Offline behavior regressions for the Christmas production blockers."""
from copy import deepcopy
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import urllib.error
from unittest.mock import patch


def verify_unsent_budget_and_account(test):
    from core import vision_gemini_client as vision
    from core.image_provider_common import ProviderQueueUnavailable
    from core.model_call_health import reset_provider_run_circuits
    from core.planning_journal import PlanningJournal
    from core.vision_errors import VisionRequestError
    primary = dict(name='offline-primary', model='gemini-a', protocol='openai',
                   api_key='fixture-key-a', key_env='FIXTURE_ACCOUNT_A', base_url='https://offline.invalid/v1')
    clients = [primary, {**primary, 'name':'offline-alias', 'model':'gemini-b'},
               {**primary, 'name':'offline-reserve', 'api_key':'fixture-key-b','key_env':'FIXTURE_ACCOUNT_B'}]
    @contextmanager
    def busy(_provider, **kwargs):
        test.assertGreater(kwargs['deadline'] - time.monotonic(), 30)
        raise ProviderQueueUnavailable('offline-primary', 'local queue')
        yield
    with tempfile.TemporaryDirectory() as tmp, patch.object(vision, 'gemini_clients', return_value=clients), \
            patch.object(vision, 'ordered_gemini_clients', return_value=clients), \
            patch.object(vision, 'model_provider_cooldown_active', return_value=False), \
            patch.object(vision, '_record_vision_model_event'):
        journal = PlanningJournal(Path(tmp)/'budget.json', child='B1', scope_key='scope')
        def invoke():
            identity = journal.reserve('tool_calls')
            counts = []
            def observe(event):
                if event.get('event') == 'request_budget':
                    counts.append(event['physical_request_count'])
                    journal.physical(identity, event['physical_request_count'])
            try:
                result = vision.gemini_stream_generate('offline', [], client_scope='visual_planning',
                    total_timeout_seconds=90, max_physical_requests=2, attempt_observer=observe)
            except VisionRequestError as exc:
                journal.settle(identity, known_unsent=exc.metadata['physical_request_count']==0)
                raise
            (Path(tmp)/'response.txt').write_text(result, encoding='utf-8')
            journal.settle(identity, result_path='response.txt')
            return result, counts
        with patch.object(vision, 'provider_concurrency_slot', side_effect=busy), \
                patch.object(vision, '_post_json_preserve_redirects') as post:
            with test.assertRaises(VisionRequestError):
                invoke()
            post.assert_not_called()
        test.assertEqual(4, journal.remaining('tool_calls'), 'Unsent work must release its reservation')
        try:
            success = json.dumps({'choices':[{'message':{'content':'ok'}}]})
            error = urllib.error.HTTPError('https://offline.invalid', 402, 'insufficient_balance', {},
                                            io.BytesIO(b'{"error":{"code":"insufficient_balance"}}'))
            sent_keys = []
            def send(url, body, *, headers, **kwargs):
                sent_keys.append(headers['Authorization'])
                if len(sent_keys)==1:
                    raise error
                return success
            with patch.object(vision, '_post_json_preserve_redirects', side_effect=send), \
                    patch.object(vision, 'provider_concurrency_slot'):
                result, counts = invoke()
                test.assertEqual('ok', result)
                test.assertEqual([0,1,2], counts)
                test.assertEqual(['Bearer fixture-key-a','Bearer fixture-key-b'], sent_keys)
            test.assertEqual(2, journal.remaining('tool_calls'), 'Both physical submissions remain charged')
            # Already known unavailable account: no new request and no consumption.
            with patch.object(vision, 'ordered_gemini_clients', return_value=clients[:2]), \
                    patch.object(vision, '_post_json_preserve_redirects') as post:
                with test.assertRaises(VisionRequestError):
                    invoke()
                post.assert_not_called()
            test.assertEqual(2, journal.remaining('tool_calls'))
        finally:
            reset_provider_run_circuits()


def verify_gateway_wait(test):
    from core import image_provider_routing as routing
    from core import image_generation as generation, model_call_health as health
    from core.image_provider_common import ProviderQueueUnavailable, ProviderTransportError
    from tests.test_provider_runtime_v1 import _Plugin
    clock = [1000.0]
    fake_time = SimpleNamespace(time=lambda:clock[0], monotonic=lambda:clock[0],
                               sleep=lambda _seconds:clock.__setitem__(0,clock[0]+30))
    task = dict(logical_task_id='generate:B1:scene', child='B1', role='scene', providers=['p'])
    with patch.object(routing,'provider_run_circuit_open',return_value=False),patch.object(routing,'provider_runtime_circuit_key',return_value='offline'),\
            patch.object(routing,'provider_attempts',return_value=1),patch.object(routing,'provider_timeout_seconds',return_value=420),\
            patch.object(routing,'provider_concurrency_slot'),patch.object(routing,'admit_provider_probe',return_value=True),\
            patch.object(routing,'_generate_with_provider_deadline') as post:
        for seconds in (2,5):
            with test.assertRaises(ProviderQueueUnavailable):
                routing.generate_with_provider_retries(provider_name='offline',image_input_paths=[],prompt='offline',total_timeout_seconds=seconds)
        post.assert_not_called()
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(health, 'model_call_health_ledger_path', return_value=Path(tmp)/'health.json'), \
            patch.object(health, 'time', fake_time), patch.object(generation, 'time', fake_time):
        for _ in range(2):
            with test.assertRaises(ProviderTransportError), health.image_gateway_attempt('https://offline.invalid/v1'):
                raise ProviderTransportError('p', 'fixture transport')
        calls = []
        def generate(value, **_kwargs):
            calls.append(clock[0])
            with health.image_gateway_attempt('https://offline.invalid/v1'):
                return {**value, 'provider':'p'}
        with patch.object(generation, 'generate_one', side_effect=generate):
            completed, failures = generation._execute([task], plugin=_Plugin(), workers=1)
        test.assertEqual([], failures)
        test.assertEqual(1, len(completed))
        test.assertEqual(2, len(calls), 'Cooldown must wait, not repeatedly dispatch')
        test.assertGreaterEqual(calls[1]-calls[0], 180)
        # A cooldown cannot extend the invocation's authorized execution deadline.
        clock[0]=1000
        unavailable=ProviderQueueUnavailable('image_gateway','cooldown')
        unavailable.retry_at=1180
        with patch.object(generation, 'generate_one', side_effect=unavailable) as remote:
            completed, failures = generation._execute([{**task,'deadline_monotonic':1060}],plugin=_Plugin(),workers=1)
        test.assertEqual(1, remote.call_count)
        test.assertEqual([], completed)
        test.assertEqual('generation_provider_capacity', failures[0]['failure_owner'])
        test.assertLessEqual(clock[0],1060)
        clock[0]=1000
        def after_cooldown(value, **_kwargs):
            if clock[0]<1180:raise unavailable
            return {**value,'provider':'p'}
        later={**task,'logical_task_id':'generate:B1:size','role':'size','deadline_monotonic':1300}
        with patch.object(generation,'generate_one',side_effect=after_cooldown):
            completed, failures=generation._execute([{**task,'deadline_monotonic':1060},later],plugin=_Plugin(),workers=1)
        test.assertEqual(['size'],[item['role'] for item in completed])
        test.assertEqual(['scene'],[item['task']['role'] for item in failures])


def verify_local_planning_feedback(test):
    from core.planning_contract import region_action_schema, schema_issues, work_capabilities
    from core.planning_feedback import parse_decisions
    from core.product_region import validate_region_action, RegionToolError
    from core.visual_design_kit_compiler import collect_brief_issues
    from products.generic_extractors import product_pack_counts
    from tests.test_visual_flow_contract import protect, delta, source, draft
    from tests.current_image_contract_fixture import current_art_direction
    for text in ('4 tree sections','4 tree segments','3 cabinet doors','2 bed rails'):
        test.assertEqual(set(), product_pack_counts(text, display=True), text)
    for text in ('4 trees','2 cabinets','2 bed frames'):
        test.assertEqual({int(text[0])}, product_pack_counts(text, display=True), text)
    intent=protect()
    intent['targets'][0]['crop']['bottom']=.94
    row={'intent':intent,'candidates':[{'candidate_id':'c1','parent_id':'frame'}]}
    catalog={'frame':{'parts':['__whole__'],'windows':{'__whole__':intent['targets'][0]['crop']},'candidate_ids':['c1']}}
    correction=delta(); correction['crop']['bottom']=.95
    test.assertTrue(schema_issues({'deltas':[correction]}, region_action_schema(catalog)))
    with test.assertRaisesRegex(RegionToolError,'allowed=.*0.94.*patch_plan'):
        validate_region_action({'deltas':[correction]},row)
    correction['crop']['bottom']=.94
    validate_region_action({'deltas':[correction]},row)
    test.assertEqual([],schema_issues({'deltas':[correction]},region_action_schema(catalog)))
    context=dict(role='size',key='a'*64,work_kind='decide_region',issues=[],source_ids=['source_00'],
        draft={'product_region':{}},region_catalog=catalog,capabilities=work_capabilities('decide_region',0,1,selection_available=True))
    context['draft']['product_region']={'path':'fixture.json'}
    answer={'role':'size','action':'change_region','reason':'Existing candidate covers the product. '*30,
            'region_action':{'select':[{'object_id':'frame','candidate_ids':['c1']}]}}
    test.assertEqual('change_region',parse_decisions({'decisions':[answer]},[context])['size']['action'])
    answer['region_action']['select'][0]['candidate_ids']=['foreign']
    test.assertIn('issue',parse_decisions({'decisions':[answer]},[context])['size'])
    planned=draft();planned['image_direction']['environment_mode']='source_setting'
    planned['image_direction']['presentation']['components']=['room.wall']
    errors=collect_brief_issues(planned,source(),current_art_direction(),[source()],category_id='artificial_tree')
    denied=[e for e in errors if 'not authorized' in e['message']]
    test.assertTrue(denied)
    test.assertNotIn('room.wall',denied[0]['allowed_values'])
    planned['image_direction']['presentation']['components']=[]
    test.assertFalse(any('not authorized' in e['message'] for e in collect_brief_issues(
        planned,source(),current_art_direction(),[source()],category_id='artificial_tree')))


from tempfile import TemporaryDirectory

def verify_equivalent_facts(test):
    from core.visual_semantics import fact_identity,same_fact_meaning,source_fact_records,observe_child_sources
    from core.visual_design_kit import compact_product_claims
    from tests.test_image_branch_v1 import _child,_evidence
    from core.io import file_sha256
    from PIL import Image
    child=_child();child['title']='White tree 4.5 FT';child['specs'].update(height='54',height_unit='in')
    base=source_fact_records(child);previous={'product_claims':compact_product_claims(child)}
    enriched=deepcopy(child);enriched['normalized_facts']['resolved_facts']={
        'size':{'status':'confirmed','value':'4ft 6in','evidence':[{'source':'variation'}]}}
    enriched['specs']['size']='4ft 6in'
    test.assertEqual(fact_identity(base),fact_identity(source_fact_records(enriched)))
    test.assertEqual(previous['product_claims'],compact_product_claims(enriched,previous=previous))
    original={'product.specs.base_type':'base type: Stand'}
    confirmed={**original,'product.fact_resolutions.base_type':json.dumps({'status':'confirmed','value':'Stand','evidence':[{'source':'attributes'}]})}
    test.assertTrue(same_fact_meaning(original,confirmed))
    test.assertNotEqual(fact_identity(original),fact_identity(confirmed),'Persisted identities are never rewritten')
    for status,value in [('conflicted','Stand'),('unconfirmed','Stand'),('confirmed','Pot')]:
        changed={**confirmed,'product.fact_resolutions.base_type':json.dumps({'status':status,'value':value,'candidates':[value]})}
        test.assertFalse(same_fact_meaning(original,changed))
    for value,status in [('5ft','confirmed'),('4ft 6in','conflicted')]:
        bad=deepcopy(enriched);bad['normalized_facts']['resolved_facts']['size'].update(value=value,status=status)
        test.assertNotEqual(fact_identity(base),fact_identity(source_fact_records(bad)))
        test.assertNotEqual(previous['product_claims'],compact_product_claims(bad,previous=previous))
    # Duplicate size must not mean the width of a different physical axis.
    dimensions={'product.title':'Tree 4.5 FT','product.specs.dimensions':'54"W x 72"H','product.specs.size':'54 in'}
    test.assertIn('product.specs.size',fact_identity(dimensions))
    malformed={'product.title':'Tree 100/200/300 in many options'}
    test.assertEqual(malformed,fact_identity(malformed))
    from core.visual_semantics import recovery_facts_match
    before={'product.title':'Pine tree, 1498 tips, warm white lights',
            'product.specs.tree_type':'synthetic','product.specs.plant_or_animal_product_type':'synthetic',
            'product.specs.sold_unit_count':'1','product.specs.material':'PVC'}
    after={**before,'product.specs.tree_type':'Pine','product.specs.tip_count':'1498','product.specs.light_color':'Warm White'}
    test.assertTrue(recovery_facts_match(before,after,category_id='artificial_tree',referenced_fields={'product.title'}))
    test.assertFalse(recovery_facts_match(before,after,category_id='bed_frame'))
    test.assertFalse(recovery_facts_match(before,after,category_id='artificial_tree',referenced_fields={'product.specs.tree_type'}))
    for field,value in [('sold_unit_count','2'),('material','metal'),('tree_type','Fir')]:
        changed={**before,'product.specs.'+field:value}
        if field=='tree_type':changed['product.specs.plant_or_animal_product_type']='Fir'
        test.assertFalse(recovery_facts_match(before,changed,category_id='artificial_tree'))
    test.assertFalse(recovery_facts_match(after,{**after,'product.specs.tip_count':'1800'},category_id='artificial_tree'))
    conflicted={**after,'product.fact_resolutions.light_color':json.dumps({'status':'conflicted','candidates':['red','white']})}
    test.assertFalse(recovery_facts_match(before,conflicted,category_id='artificial_tree'))
    with TemporaryDirectory() as tmp:
        job=Path(tmp);image=job/'source.png';Image.new('RGB',(32,32),'white').save(image)
        sources=[{'source_id':'source_00','sha256':file_sha256(image),'path':image,'ocr':[]}]
        observation=_evidence('main')['visual_evidence'];observation['source_id']='source_00'
        observation['objects'][0]['membership_evidence']=[{'fact_id':'product.title','quote':child['title']}]
        observation.pop('status');observation.pop('child_facts_revision_id');observation.pop('policy_version')
        observation['reference_purposes']=[]
        response=json.dumps({'sources':[observation],'appearance_source_id':'source_00'})
        with patch('core.visual_semantics.gemini_stream_generate',return_value=response) as model:
            first=observe_child_sources(job,child,sources);second=observe_child_sources(job,enriched,sources)
        test.assertEqual(1,model.call_count)
        test.assertEqual(first['source_00']['objects'],second['source_00']['objects'])
        test.assertEqual(first['source_00']['product_features'],second['source_00']['product_features'])
        test.assertNotEqual(first['source_00']['child_facts_revision_id'],second['source_00']['child_facts_revision_id'])
    from products.generic_extractors import explicit_item_counts
    test.assertEqual({1,2},explicit_item_counts({'title':'Artificial tree','productDetails':{'Number of Items':'2','Unit Count':'1 Count'}}))
    test.assertEqual({2},explicit_item_counts({'title':'Artificial tree','productDetails':{'Number of Items':'2','Unit Count':'2 Count'}}))
    test.assertEqual({1},explicit_item_counts({'title':'Artificial tree','productDetails':{
        'Number of Items':'1','Unit Count':'1498','Tip Count':'1498'}}))
    test.assertEqual(set(),explicit_item_counts({'productDetails':{'Unit Count':'300','Number of Lights':'300'}}))
    test.assertEqual({1,2},explicit_item_counts({'title':'2 Pack Artificial Trees','productDetails':{'Number of Items':'1'}}))
    from core.plugin import load_plugin
    from products.generic_extractors import extract_specs_by_fields
    fields=load_plugin('artificial_tree').merged_config()['extractors']['product_specific_fields']
    variant={'title':'7.5ft Pine with 820 PVC Branch Tips','variantAttributes':[{'key':'Size','value':'7.5 ft'}],
             'aPlusContent':{'rawText':'Number of Tips: 820(7.5ft), 950(8ft)'},
             'productDetails':{'Tip Count':'950','Number of Items':'1','Unit Count':'820 Count'}}
    test.assertEqual('820',extract_specs_by_fields(variant,fields)['tip_count'])
    test.assertEqual({1},explicit_item_counts(variant))
    sized = {'title':'6ft Artificial Tree','variantAttributes':[{'key':'Size','value':'6ft'}],
             'description':'Blade width: 2.4"  6FT: Number of tips: 650  8FT: Number of tips: 1138',
             'attributes':{'Tip Count':'1138','Product Dimensions':'40"D x 2.4"W x 72"H'}}
    specs = extract_specs_by_fields(sized,fields)
    test.assertEqual(('650','2.4 in','40 in'),(specs['tip_count'],specs['blade_width'],specs['item_depth']))
    test.assertNotIn('width',specs)
    test.assertNotIn('dimensions',specs)
    test.assertNotIn('tip_count',extract_specs_by_fields({**sized,'title':'8ft Artificial Tree'},fields))
    result=extract_specs_by_fields({'productDetails':{'Tree Type':'Artificial','Plant Type':'Fir',
        'Plant or Animal Product Type':'Spruce','Style':'Flocked','Tip Count':'1498'}},fields)
    test.assertEqual(['Artificial','Fir','Spruce','Flocked','1498'],[result[k] for k in
        ('tree_type','plant_type','plant_or_animal_product_type','style','tip_count')])


def verify_saved_lane_and_accounting(test):
    from core import image_generation as generation
    from core.image_response import response_submission_metrics
    from core.status import runtime_presence,job_run_lock
    from core.io import write_json
    with TemporaryDirectory() as tmp:
        job=Path(tmp);task={'job_dir':tmp,'logical_task_id':'generate:B1:func','child':'B1','role':'func','raw_response_path':'saved.json','providers':[]}
        with patch.object(generation,'_generation_worker_limit',return_value=1),patch.object(generation,'_dispatch_generation_batch',return_value=([],[])),\
                patch.object(generation,'generate_one',side_effect=AssertionError('No remote admission for saved bytes')) as remote,\
                patch.object(generation,'finalize_candidate',return_value=task) as local:
            completed,failures=generation._execute([task],plugin=None,workers=1)
        test.assertEqual([task],completed);test.assertFalse(failures);remote.assert_not_called();local.assert_called_once()
        for binding,status in [('old','submitted'),('new','received')]:
            write_json(job/f'reports/image_responses/{binding}/receipt.json',{'schema':'image-response-v1','binding':binding,'status':status,
                'submitted_at':'2026-10-21T00:00:00+00:00','request_audit':{'logical_task_id':'generate:B1:func'},'replaces':[]})
        metrics=response_submission_metrics(job)
        test.assertEqual(1,metrics['image_remote_unknown_receipt_count']);test.assertEqual(1,metrics['image_saved_response_receipt_count'])
        write_json(job/'reports/image_responses/bad/receipt.json',{'schema':'image-response-v1','binding':'bad','submitted_at':None})
        test.assertEqual(1,response_submission_metrics(job)['image_provider_submission_unrecorded_count'])
        from core.candidate_state import candidate_inventory
        write_json(job/'reports/candidate_manifests/B1/func/bad/candidate0.json',[])
        test.assertEqual(1,candidate_inventory(job)['candidate_manifest_unreadable_count'])
        test.assertEqual('interrupted',runtime_presence(job,{'status':'running'})['runtime_status'])
        with job_run_lock(job):test.assertEqual('active',runtime_presence(job,{'status':'running'})['runtime_status'])
    from core.planning_feedback import output_budget
    test.assertGreater(output_budget({'work_kind':'create_draft','draft':{}}),output_budget({'work_kind':'confirm_region'}))
    test.assertLessEqual(output_budget({'work_kind':'create_draft','draft':{'text':'x'*30000}}),7000)

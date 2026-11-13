"""Request identity and single facts/offer authority regressions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from copy import deepcopy
import json,os


def raw_product(asin='B000000001',size='Queen'):
    return {'asin':asin,'title':f'{size} Metal Platform Bed Frame','bulletPoints':['Metal construction'],
        'images':['https://example.com/source.png'],'productDetails':{'Size':size,'Color':'Black','Material':'Metal'}}


def verify_source_identity_and_facts(test):
    from tests.four_stage_fixture import verify_fields_prices
    verify_fields_prices(test)
    from core.source_fetch.apify_client import ApifyClient
    from core.source_fetch import apify
    from core.product_family import effective_product_facts
    from core.plugin import load_plugin
    from core.copy_polish import _copy_facts
    from core.image_task_inputs import visual_variation_values
    from core.template_engine import _family_specific,_normalized_variation_values_for_template
    plugin=load_plugin('bed_frame');ext=plugin.load_extractors();a,b='B000000001','B000000002'
    client=ApifyClient('dummy','offline~actor')
    with patch.object(client,'fetch_items',return_value=[raw_product(a),raw_product(b)]):test.assertEqual(b,client.fetch_product(b)['asin'])
    for data in ([raw_product(a)],[{k:v for k,v in raw_product(b).items() if k!='asin'}]):
        with patch.object(client,'fetch_items',return_value=data),test.assertRaises(RuntimeError):client.fetch_product(b)
    for raw in (raw_product(a),{k:v for k,v in raw_product(b).items() if k!='asin'}):
        test.assertTrue(apify._raw_quality_issues(raw,extractors=ext,seed_asin=b,require_variations=False))
    with TemporaryDirectory() as tmp:
        path=Path(tmp)/f'{b}.json';path.write_text(json.dumps(raw_product(a)),encoding='utf-8')
        with patch.object(client,'fetch_product',return_value=raw_product(b)) as fetch:
            valid=apify._fetch_validated_raw(client,Path(tmp),b,False,extractors=ext,require_variations=False)
            test.assertEqual(b,valid['asin']);test.assertEqual(1,fetch.call_count)
    for variation,spec,expected_status in [('Queen','Twin','conflicted'),('Queen','Queen','confirmed'),('Twin XL','Twin-XL','confirmed'),
                                         ('6 ft with pot','72 in without pot','conflicted')]:
        normalized=apify._normalized_child_facts(variation_values={'size':variation},specs={'size':spec},specific={'size':spec},offer={},sold_unit_count=1,package_quantity=1)
        child={'asin':a,'variation_values':{'size':variation},'specs':{'size':spec},'product_specific':{'bed_frame':{'size':spec}},'normalized_facts':normalized}
        decision=normalized['resolved_facts']['size'];test.assertEqual(expected_status,decision['status'])
        facts=effective_product_facts(child);copy=_copy_facts(child);specific=_family_specific(child,plugin)
        template=_normalized_variation_values_for_template(child,specific,child['variation_values'])
        if expected_status=='conflicted':
            for row in (facts,copy,specific,template,visual_variation_values(child)):test.assertNotIn('size',row)
        else:
            for row in (facts,copy,specific,template):test.assertEqual(variation,row['size'])
    from core.product_family import identity_values_equal
    test.assertTrue(identity_values_equal('6 ft','72 in'))
    test.assertEqual({},apify._source_offer({'asin':a,'variations':[{'asin':b,'price':'123.45','currency':'EUR'}]}))
    own=apify._source_offer({'asin':a,'price':'19.99','currency':'CAD','recommendations':[{'asin':b,'price':'123.45'}]})
    test.assertEqual(('19.99','CAD'),(own['current_price'],own['current_currency']))
    test.assertNotIn('list_price',own)
    separate=apify._source_offer({'asin':a,'price':42.74,'listPrice':47.49},marketplace='US')
    from core.template_submit_ready import listing_prices
    test.assertEqual(('42.74','47.49'),(separate['current_price'],separate['list_price']))
    test.assertEqual({'list_price':'47.49','selling_price':''},listing_prices({'asin':a,'offer':separate},
        {'price_policy':'use_source_list_price'},submit_ready=True))
    split=apify._source_offer({'asin':a,'price':'19.99','recommendations':[{'asin':b,'currency':'EUR'}]})
    test.assertNotEqual('EUR',split.get('current_currency'))
    verify_material_ownership(test)
    from products.generic_extractors import extract_variations,theme_from_dimensions
    package={'asin':a,'variantAttributes':[{'key':'Item Package Quantity','value':'2'}],
        'variantDetails':[{'asin':a,'name':'2'},{'asin':b,'name':'1'}]}
    extracted=extract_variations(package,a,['color','size','style'])
    test.assertEqual(['item_package_quantity'],extracted['dimensions'])
    test.assertEqual({'1','2'},{v['item_package_quantity'] for v in extracted['variants']})
    test.assertNotEqual('COLOR',extracted['variation_theme'])
    test.assertEqual('',theme_from_dimensions([]))
    test.assertEqual('SIZE/LIGHT_COLOR',theme_from_dimensions(['light_color','size'],['COLOR/SIZE','SIZE/LIGHT_COLOR']))
    test.assertEqual('COMPATIBLE_WITH_MATTRESS_SIZE',theme_from_dimensions(['compatible_with_mattress_size']))
    from core.product_family import family_variation_issues
    family={'variation_dimensions':['color'],'variation_theme':'COLOR','children':[
        {'asin':a,'variation_values':{'color':'Green'}},{'asin':b,'variation_values':{'color':'green'}}]}
    test.assertTrue(family_variation_issues(family))
    family['children'][1]['variation_values']['color']='White'
    test.assertEqual([],family_variation_issues(family))
    missing={'sold_unit_count':None,'sold_unit_count_source':'apify_missing_pack_count',
             'package_quantity':None,'package_quantity_source':'apify_missing_package_quantity'}
    test.assertNotIn('sold_unit_count',effective_product_facts(missing))
    test.assertNotIn('package_quantity',effective_product_facts(missing))


    # Source groups are observations, never last-write-wins or duplicate votes.
    ext = load_plugin('bathroom_cabinet').load_extractors()
    raw = {'productDetails': {'Color': 'Black', 'Number of Doors': '2', 'Product Dimensions': '10 x 20 x 30 inches'},
           'attributes': [{'key': 'Color', 'value': 'White'}, {'key': 'Number of Doors', 'value': '4'},
                          {'key': 'Product Dimensions', 'value': '40 x 50 x 60 inches'}]}
    specs = ext.extract_specs(raw)
    decisions = apify._resolve_structured_facts(title='4 Door Cabinet', bullets=[], description='',
                                               specs=specs, specific=ext.product_specific(raw), variation={})
    for key in ('color', 'number_of_doors', 'dimensions'):
        test.assertEqual('conflicted', decisions[key]['status'])
        test.assertEqual(2, len(decisions[key]['candidates']))
    facts = effective_product_facts({'specs': specs, 'normalized_facts': {'resolved_facts': decisions,
        'physical_dimensions': '40 x 50 x 60 inches', 'height': '60'}})
    for key in ('color', 'number_of_doors', 'dimensions', 'physical_dimensions', 'height'):
        test.assertNotIn(key, facts)
    packaging = ext.extract_specs({'description': 'Shipping carton 40 x 20 x 10 inches; packing height 10 inches'})
    for key in ('length', 'width', 'height', 'dimensions'):
        test.assertNotIn(key, packaging)
    from products.generic_extractors import explicit_item_counts, explicit_package_quantity
    test.assertEqual({1, 2}, explicit_item_counts({'productDetails': {'Number of Items': '1'},
        'attributes': [{'key': 'Number of Items', 'value': '2'}]}))
    with test.assertRaisesRegex(ValueError, 'Conflicting'):
        explicit_package_quantity({'productDetails': {'Package Quantity': '1'},
            'attributes': [{'key': 'Item Package Quantity', 'value': '2'}]})


    raw = {'attributes': [{'key': 'Item Weight', 'value': '28.5 pounds'},
                          {'key': 'Weight Capacity Maximum', 'value': '175 pounds'},
                          {'key': 'Item Depth', 'value': '12 inches'}]}
    specs = ext.extract_specs(raw)
    decisions = apify._resolve_structured_facts(title='', bullets=[], description='', specs=specs, specific=specs, variation={})
    child = {'specs': specs, 'normalized_facts': {'resolved_facts': decisions}}
    from core.product_family import fact_resolutions, fact_statement_issues
    test.assertEqual([], fact_statement_issues('Weighs 28.5 pounds and supports 175 pounds.', fact_resolutions(child)))
    projection = effective_product_facts(child)
    test.assertEqual(('28.5', 'Pounds'), (projection['item_weight'], projection['item_weight_unit']))
    test.assertEqual(('12', 'Inches'), (projection['item_depth'], projection['item_depth_unit']))


def verify_material_ownership(test):
    from core.plugin import load_plugin
    from core.source_fetch.apify import _resolve_structured_facts
    from core.product_family import effective_product_facts, fact_statement_issues
    from core.template_engine import _family_specific
    from core.copy_polish import _copy_facts, _source_copy
    for category, raw, expected in (
        ('artificial_tree', {'productDetails': {'Leaf Material': 'Silk', 'Trunk Material': 'Wood', 'Pot Material': 'Concrete'}},
         {'leaf_material': 'Silk', 'trunk_material': 'Wood', 'pot_material': 'Concrete'}),
        ('medicine_cabinet', {'productDetails': {'Frame Material': 'Steel', 'Top Material Type': 'MDF'}},
         {'frame_material': 'Steel', 'top_material': 'MDF'}),
        ('bed_frame', {'productDetails': {'Frame Material': 'Metal'}}, {'frame_material': 'Metal'}),
        ('bathroom_cabinet', {'productDetails': {'Material': 'Wood', 'Frame Material': 'Steel'}},
         {'material': 'Wood', 'frame_material': 'Steel'}),
    ):
        plugin = load_plugin(category); specs = plugin.load_extractors().extract_specs(raw)
        decision = _resolve_structured_facts(title='', bullets=[], description='', variation={}, specs=specs, specific=specs)
        child = {'specs': specs, 'product_specific': {category: specs}, 'normalized_facts': {'resolved_facts': decision}}
        for projection in (effective_product_facts(child), _copy_facts(child), _family_specific(child, plugin)):
            for key, value in expected.items(): test.assertEqual(value, projection[key])
            if 'material' not in expected: test.assertNotIn('material', projection)
            test.assertNotIn('source_fact_evidence', projection)
        for key in expected:
            test.assertTrue(decision[key]['evidence'][0]['field'])
            test.assertTrue(decision[key]['evidence'][0]['owner'])
        if category == 'artificial_tree':
            test.assertEqual([], fact_statement_issues('Silk leaves and Wood trunk in Concrete pot', decision))
            test.assertEqual(['leaf_material'], fact_statement_issues('Entirely Silk', decision))
            test.assertEqual(['leaf_material'], fact_statement_issues('Silk tree', decision))
            child.update(title='Silk tree', bullets=['Silk leaves and Wood trunk'])
            test.assertEqual('', _source_copy(child)['title'])
            test.assertEqual(['Silk leaves and Wood trunk'], _source_copy(child)['item_highlights'])
    plugin = load_plugin('medicine_cabinet')
    specs = plugin.load_extractors().extract_specs({'productDetails': {'Frame Material': 'Steel'},
                                                  'attributes': [{'key': 'Frame Material Type', 'value': 'Aluminum'}]})
    decision = _resolve_structured_facts(title='', bullets=[], description='', variation={}, specs=specs, specific=specs)
    test.assertEqual('conflicted', decision['frame_material']['status'])
    test.assertEqual({'Steel', 'Aluminum'}, set(decision['frame_material']['candidates']))
    test.assertEqual({'productDetails', 'attributes'}, {row['source'] for row in decision['frame_material']['evidence']})
    test.assertNotIn('frame_material', effective_product_facts({'specs': specs, 'normalized_facts': {'resolved_facts': decision}}))


def verify_fetch_recovery_binding(test):
    from core.job import create_job,load_job
    from core.plugin import load_plugin
    from core.source_fetch import apify
    from core import production
    from core.io import read_json,write_json
    plugin=load_plugin('bed_frame')
    with TemporaryDirectory() as tmp:
        job=create_job(plugin=plugin,seed_asin='B000000001',brand='Original',sku_prefix='OLD',out_root=tmp)
        request=production.JobRunRequest(job_dir=job,plugin=plugin,resume=True,template_mode='draft')
        class Client:
            def fetch_product(self,asin):return raw_product(asin)
        env={'APIFY_TOKEN':'offline','APIFY_ACTOR_ID':'offline~actor'}
        with patch.object(apify,'load_env',return_value=env),patch.object(apify,'ApifyClient',return_value=Client()):
            result=production._run_stage('fetch',request=request)
        test.assertFalse(result.get('reused',False),'Missing initial family must enter normal fetch')
        test.assertTrue(production._fetch_current(job,plugin))
        original=load_job(job)
        for key,new in [('brand','New Brand'),('sku_prefix','NEW')]:
            changed={**original,key:new};write_json(job/'job.json',changed)
            test.assertFalse(production._fetch_current(job,plugin))
            with patch.object(apify,'ApifyClient',side_effect=AssertionError('Metadata change must not buy another fetch')):
                production.run_job(request,stages=['fetch'])
            test.assertEqual(new,read_json(job/'source/product_family_v3.json')['family'][key])
            original=changed
        for key,new in [('seed_asin','B000000009'),('marketplace','CA')]:
            write_json(job/'job.json',{**original,key:new})
            with patch.object(apify,'ApifyClient',side_effect=AssertionError('Changed source identity must not silently refetch')):
                with test.assertRaises(RuntimeError):production._run_stage('fetch',request=request)
        write_json(job/'job.json',original)
        (job/'source/product_family_v3.json').write_text('{bad',encoding='utf-8')
        with test.assertRaises(ValueError):production._fetch_current(job,plugin)
    verify_quantity_policy_revalidation(test)


def verify_quantity_policy_revalidation(test):
    from core.job import create_job
    from core.plugin import load_plugin
    from core.source_fetch import apify
    from core.product_family import PRODUCT_FAMILY_POLICY_VERSION,ProductFamilyError,read_product_family
    from core.io import read_json,write_json,file_sha256
    from core import production
    plugin=load_plugin('artificial_tree');seed='B000000001'
    def raw(asin):
        data={'asin':asin,'title':'Artificial Tree','bulletPoints':['Each package includes two artificial trees.'],
              'images':['https://example.com/tree.jpg'],'productDetails':{'Color':'White'}}
        if asin==seed:data['variants']=[{'asin':code,'color':'White'} for code in [seed,'B000000002','B000000003']]
        return data
    class Client:
        def fetch_product(self,asin):return raw(asin)
    with TemporaryDirectory() as tmp:
        job=create_job(plugin=plugin,seed_asin=seed,brand='Test',sku_prefix='TEST',out_root=tmp)
        with patch.object(apify,'load_env',return_value={'APIFY_TOKEN':'offline','APIFY_ACTOR_ID':'offline'}),patch.object(apify,'ApifyClient',return_value=Client()):
            fresh=apify.fetch_family(job_dir=job,plugin=plugin,limit_children=2)
        test.assertEqual([2,2],[c['sold_unit_count'] for c in fresh['family']['children']])
        from core.run_scope import ensure_run_scope,read_run_scope
        fresh['family']['children'].reverse()
        write_json(job/'source/product_family_v3.json',fresh)
        frozen_scope=ensure_run_scope(job_dir=job,production=True)
        saved=deepcopy(fresh);saved['source']['policy_version']='product-family-v3-resolved-facts-v15-material-ownership'
        saved['source']['request_identity']['extractor_sha256']='a'*64
        for child in saved['family']['children']:
            child['sold_unit_count']=child['normalized_facts']['sold_unit_count']=1
        write_json(job/'source/product_family_v3.json',saved)
        test.assertFalse(Path(fresh['source']['raw_dir']).is_absolute())
        raw_dir=job/Path(fresh['source']['raw_dir'])
        before={p:file_sha256(p) for p in raw_dir.glob('*.json')}
        receipt=job/'source/apify_requests/unknown.json';write_json(receipt,{'status':'submitted','remote_id':'keep-original'})
        receipt_sha=file_sha256(receipt);family_sha=file_sha256(job/'source/product_family_v3.json')
        with test.assertRaises(ProductFamilyError):production._fetch_current(job,plugin)
        request=production.JobRunRequest(job_dir=job,plugin=plugin,resume=False,template_mode='draft')
        with patch.object(apify,'load_env',side_effect=AssertionError('Local revalidation must not require credentials')),patch.object(apify,'ApifyClient',side_effect=AssertionError('Local revalidation must not create a remote client')):
            production.run_job(request,stages=['fetch'])
        rebuilt=read_product_family(job)
        test.assertEqual(PRODUCT_FAMILY_POLICY_VERSION,rebuilt['source']['policy_version'])
        test.assertEqual(fresh['source']['request_identity'],rebuilt['source']['request_identity'])
        test.assertEqual([2,2],[c['sold_unit_count'] for c in rebuilt['family']['children']])
        test.assertEqual([c['asin'] for c in fresh['family']['children']],[c['asin'] for c in rebuilt['family']['children']])
        test.assertEqual(frozen_scope,read_run_scope(job))
        test.assertEqual(fresh['source']['fetched_at'],rebuilt['source']['fetched_at'])
        test.assertEqual(before,{p:file_sha256(p) for p in raw_dir.glob('*.json')})
        test.assertEqual(receipt_sha,file_sha256(receipt))
        test.assertFalse(production._fetch_current(job,plugin),'A source work limit cannot redefine the full family')
        test.assertTrue(apify.family_current(job,plugin,require_complete=False))
        test.assertEqual(3,rebuilt['source']['expected_child_count'])
        from core.run_scope import RUN_SCOPE_ARTIFACT
        (job/'reports'/RUN_SCOPE_ARTIFACT).unlink()
        incomplete=deepcopy(saved)
        incomplete['source']['child_fetch_errors']=[{'asin':'B000000003','error':'Original unknown request remains unresolved'}]
        incomplete['source']['expected_child_count']=3
        write_json(job/'source/product_family_v3.json',incomplete)
        with patch.object(apify,'ApifyClient',side_effect=AssertionError('Do not retry the unknown child')):
            preserved=production._run_stage('fetch',request=request)
        test.assertEqual(incomplete['source']['child_fetch_errors'],preserved['source']['child_fetch_errors'])
        test.assertEqual(3,preserved['source']['expected_child_count'])
        test.assertEqual(receipt_sha,file_sha256(receipt))
        # Tampered evidence is rejected atomically, never repaired by another POST.
        write_json(job/'source/product_family_v3.json',saved)
        path=raw_dir/f'{seed}.json';original=path.read_bytes();path.write_bytes(original+b' ')
        with patch.object(apify,'ApifyClient',side_effect=AssertionError('No remote retry')),test.assertRaises(ValueError):
            production._run_stage('fetch',request=request)
        test.assertEqual(family_sha,file_sha256(job/'source/product_family_v3.json'))

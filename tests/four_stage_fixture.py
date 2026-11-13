"""Behavior checks for semantic field use, selected measurements and QA attribution."""
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory


def verify_fields_prices(test):
    from products.generic_extractors import usage_environment, extract_specs_by_fields
    from core.source_fetch.apify import _normalized_child_facts, _source_offer
    from core.template_submit_ready import listing_prices
    from core.template_field_values import sourced_template_attributes
    from core.product_family import effective_product_facts, family_variation_issues
    from core.plugin import load_plugin
    plugin=load_plugin('artificial_tree')
    fields=plugin.merged_config()['extractors']['product_specific_fields']
    raw={'asin':'B000000001','title':'7ft Cactus Christmas Tree with 160 LED Lights',
         'attributes':{'Recommended Uses For Product':'Christmas Tree,Tree','Tree Type':'Cactus','Material':'PVC',
                       'Product Dimensions':'5"D x 36"W x 82"H'},
         'bulletPoints':['A special decoration indoors; not suitable for outdoor use.']}
    specs=extract_specs_by_fields(raw,fields)
    normalized=_normalized_child_facts(variation_values={'size':'6ft 10in'},specs=specs,specific={},offer={},
        sold_unit_count=1,package_quantity=1,title=raw['title'],bullets=raw['bulletPoints'])
    child={'asin':raw['asin'],'specs':specs,'normalized_facts':normalized,'raw':raw}
    facts=effective_product_facts(child)
    test.assertEqual(('7ft','82','Indoor','160'),tuple(facts[k] for k in ('size','height','indoor_outdoor','light_count')))
    test.assertIn('6ft 10in',normalized['resolved_facts']['size']['candidates'])
    for text,expected in [('Christmas Tree',''),('Indoor and Outdoor','Indoor, Outdoor'),
                          ('Not for outdoor use',''),('Indoor use only, not outdoor','Indoor'),
                          ('No assembly required for indoor use','Indoor'),('Indoor or outdoor use is not recommended',''),
                          ('Not only indoor but outdoor too','Indoor, Outdoor')]:
        test.assertEqual(expected,usage_environment(text))
    from core.io import write_json, file_sha256
    with TemporaryDirectory() as tmp:
        job=Path(tmp);path=job/'source/apify_raw/US'/f"{raw['asin']}.json";write_json(path,raw)
        family={'category_id':'artificial_tree','source':{'raw_sha256':{raw['asin']:file_sha256(path)}},
                'family':{'parent_asin':'','marketplace':'US','children':[child]}}
        attrs=sourced_template_attributes(job,family,child)
        test.assertEqual('Indoor',attrs['recommended_uses'])
        test.assertEqual('Not Applicable',attrs['required_product_compliance_certificate'])
        other=deepcopy(child);other['specs']['material']='Engineered Wood';other['normalized_facts']['resolved_facts'].pop('material')
        test.assertNotIn('required_product_compliance_certificate',sourced_template_attributes(job,family,other))
    test.assertEqual([],family_variation_issues({'parent_asin':'','variation_dimensions':['size'],'variation_theme':'SIZE',
        'children':[{'asin':'B000000001','variation_values':{'size':'5ft'}}]}))
    offer=_source_offer({'asin':raw['asin'],'price':89.99,'listPrice':119.99},marketplace='US')
    test.assertEqual({'list_price':'119.99','selling_price':'119.99'},listing_prices({'asin':raw['asin'],'offer':offer},
        {'price_policy':'same_as_list_price'},submit_ready=True))
    offer=_source_offer({'asin':raw['asin'],'price':89.99},marketplace='US')
    test.assertEqual({'list_price':'0.00','selling_price':'89.99'},listing_prices({'asin':raw['asin'],'offer':offer},
        {'price_policy':'same_as_list_price','list_price':0},submit_ready=True))
    test.assertEqual({'list_price':'0.00','selling_price':''},listing_prices({'asin':'B000000002','offer':offer},
        {'price_policy':'same_as_list_price'},submit_ready=True))
    from core.backend_keywords import generate_backend_keywords
    terms=generate_backend_keywords(category_id='artificial_tree',title='Cactus Christmas Tree',bullets=[],description='',product_specific={})
    test.assertEqual(len(terms.split()),len(set(terms.split())))


def verify_selected_measurements(test):
    from core.measurement_sources import measurement_authority
    from core.visual_design_kit import compact_product_claims
    from core.text_evidence import extract_measurements
    source={'source_id':'source_00','measurements':[{'source_occurrence':'m1','text':'84 in','source_label':'Tree height',
        'axis_hint':'height','measurement_kind':'dimension','canonical_pair':extract_measurements('84 in')[0]['canonical_pair'],
        'evidence_type':'arrow_endpoints'}]}
    facts=compact_product_claims({'specs':{'size':'7ft','height':'82 in','width':'36 in','stand_width':'18 in'}})
    direction={'measurement_ids':['source_00:m1']}
    authority=measurement_authority('size',direction,[source],facts)
    group=authority['measurement_groups'][0]
    test.assertEqual(('82 in','product.specs.height'),(group['render_text'],group['fact_value_evidence']['field_path']))
    test.assertEqual('84 in',source['measurements'][0]['text'])
    source['measurements'][0]['source_label']='tree'
    test.assertEqual('82 in',measurement_authority('size',direction,[source],facts)['render_text'][0])
    source['measurements'][0].update(source_label='Stand width',axis_hint='width',text='16 in')
    group=measurement_authority('size',direction,[source],facts)['measurement_groups'][0]
    test.assertEqual('18 in',group['render_text'])
    source['measurements'][0].update(source_label='Unknown bracket width')
    test.assertEqual('16 in',measurement_authority('size',direction,[source],facts)['render_text'][0])


def verify_qa_attribution(test):
    from core.image_qa import _parse_factual_gates
    from core.release_manifest import _validate_resolutions, ReleaseManifestError
    check={'check':'unauthorized_text','status':'fail','candidate_observation':'','reference_observation':'Source banner',
           'source_ids':['source_00'],'reason':'Banner detected','candidate_text':['Merry Christmas'],
           'text_issue':{'kind':'unexpected_text','attachment':2,'text':'Merry Christmas','location':'top banner'}}
    parse=lambda row:_parse_factual_gates(json.dumps({'checks':[row]}),['unauthorized_text'],{'source_00'})[0]
    test.assertEqual('inconclusive',parse(check)['status'])
    check['text_issue']['attachment']=1
    test.assertEqual('fail',parse(check)['status'])
    check.update(status='pass',candidate_text=[],text_issue={})
    test.assertEqual('pass',parse(check)['status'])
    target={'candidate_sha256':'c'*64,'source_sha256':'s'*64,'failed_checks':['unauthorized_text']}
    with test.assertRaises(ReleaseManifestError):_validate_resolutions([],target)
    resolution={'candidate_sha256':'c'*64,'source_sha256':'s'*64,'check':'unauthorized_text',
        'conclusion':'confirmed','evidence':'Attachment 1 has no authored text; banner occurs only in source.'}
    _validate_resolutions([resolution],target)
    with test.assertRaises(ReleaseManifestError):_validate_resolutions([resolution],{**target,'failed_checks':['image_integrity']})

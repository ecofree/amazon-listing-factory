"""Self-contained immutable archive; current eligibility is a separate read-only check."""
from __future__ import annotations
import csv,hashlib,json,os,re,shutil,tempfile,time
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from .io import file_sha256,read_json,write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id

SCHEMA=3
POLICY='delivery-package-v3-scoped-streamed-evidence'
MAX_ARCHIVE_BYTES=1024**3
MAX_STRUCTURED_BYTES=16*1024*1024


def _bounded_bytes(path):
    with path.open('rb') as handle:data=handle.read(MAX_STRUCTURED_BYTES+1)
    if len(data)>MAX_STRUCTURED_BYTES:raise ValueError('Structured evidence exceeds bounded serialization size')
    return data


def _context(job):
    from .release_manifest import HUMAN_REVIEW_ARTIFACT
    from .final_source_intents import SOURCE_INTENT_REVIEW_ARTIFACT,FINAL_SOURCE_INTENT_ARTIFACT
    from .image_tasks import IMAGE_TASK_ARTIFACT
    from .image_prompt_compiler import IMAGE_PROMPT_ARTIFACT
    from .visual_design_kit import VISUAL_DESIGN_KIT_ARTIFACT
    from .run_scope import RUN_SCOPE_ARTIFACT
    metadata=read_json(job/'job.json')
    if metadata.get('business_input'):
        from .job import _validate_business_input,JobError
        try:_validate_business_input(metadata['business_input'],metadata)
        except JobError as exc:raise ValueError('Business evidence is no longer eligible: '+str(exc)) from exc
    # Credentials, config paths, source code and workstation paths are not listing semantics.
    fields=('seller_id','listing_intent','seed_asin','category_id','brand','sku_prefix','marketplace','r2_prefix',
            'manufacturer','country','condition','gtin_exempt','product_id_type','product_id','fulfillment',
            'shipping_template','dangerous_goods','batteries_required','batteries_included','contains_battery',
            'is_fragile','package_level','business_input','conditional_dispositions','publication_policy','design_inputs','measurement_decisions')
    plan=read_json(job/'template/plan.json')
    return {'job':_redact({key:metadata.get(key) for key in fields},{}),
        'template_sha256':file_sha256(Path(plan['template_path'])) if plan.get('template_path') else None,
        'decisions':{name:file_sha256(job/'reports'/name) if (job/'reports'/name).is_file() else None
        for name in (HUMAN_REVIEW_ARTIFACT,SOURCE_INTENT_REVIEW_ARTIFACT,FINAL_SOURCE_INTENT_ARTIFACT,
                     IMAGE_TASK_ARTIFACT,IMAGE_PROMPT_ARTIFACT,VISUAL_DESIGN_KIT_ARTIFACT,RUN_SCOPE_ARTIFACT)}}


def _bound_evidence(job,approved,selected,generated):
    from .image_tasks import read_image_tasks
    from .candidate_state import candidate_by_sha,production_candidate_error
    from .image_response import finalized_native_response
    from .qa_evidence import qa_receipt_root,qa_receipt_revision
    tasks=read_image_tasks(job)['tasks']
    qa=[json.loads(line) for line in (job/'reports/qa_evidence_v5.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    def add(name,path,expected=None):
        path=resolve_job_owned_path(job,path)
        if not path.is_file() or expected and file_sha256(path)!=expected:raise ValueError('Delivery evidence missing/changed: '+name)
        selected[name]=path
    for row in approved:
        matches=[t for t in tasks if (t['child'],t['role'])==(row['child'],row['role'])]
        if len(matches)!=1:raise ValueError('Delivery task evidence is missing/ambiguous')
        task=matches[0];candidate=candidate_by_sha(job,task,row['candidate_sha256'])
        if production_candidate_error(candidate) or candidate['candidate_sha256']!=row['candidate_sha256']:
            raise ValueError('Delivery candidate provenance is not current provider output')
        prefix=f"evidence/{row['child']}/{row['role']}"
        generated[prefix+'/task.json']=task;generated[prefix+'/candidate-binding.json']=candidate
        from .measurement_sources import statement_evidence
        for evidence in statement_evidence(task).values():
            ref=evidence['raw_source'];add('evidence/source/'+evidence['child']+'.json',ref['path'],ref['sha256'])
        references=task.get('generation_references') or []
        if not any(r.get('kind')!='design_reference' and r.get('child')==row['child'] for r in references):
            raise ValueError('Delivery lacks bound same-child references')
        for ref in references:
            path=resolve_job_owned_path(job,ref['path'])
            add('evidence/references/'+ref['sha256']+path.suffix.lower(),path,ref['sha256'])
        origins=candidate['provenance_manifests']
        for index,ref in enumerate(origins):
            add(prefix+('/candidate.json' if index==0 else f'/generation-parent-{index}.json'),ref['path'],ref['sha256'])
        origin=read_json(resolve_job_owned_path(job,origins[-1]['path']))
        native=finalized_native_response(job,origin)
        add(prefix+'/image-receipt.json',native['native_receipt_path'],native['native_receipt_sha256'])
        add(prefix+'/native.bin',native['native_path'],origin['native_image']['sha256'])
        add(prefix+'/original-edit-prompt.txt',origin['prompt_path'],origin['request_prompt_fingerprint'])
        receipt_path=resolve_job_owned_path(job,native['native_receipt_path']);receipt=read_json(receipt_path)
        if receipt.get('local_finalization'):
            local=receipt['local_finalization']
            add(prefix+'/original-receipt.json',receipt_path.with_suffix('.local-before'),local['request']['receipt']['sha256'])
            private=receipt_path.with_suffix('.http')
            if not private.is_file() or file_sha256(private)!=receipt['body_sha256']:raise ValueError('Private response integrity changed')
            generated[prefix+'/original-response-provenance.json']={'sha256':receipt['body_sha256'],
                'distribution':'Private raw HTTP retained by its original owner; not embedded in distribution archive'}
        evidence=[r for r in qa if (r.get('child'),r.get('role'),r.get('candidate_sha256'))==(row['child'],row['role'],row['candidate_sha256'])]
        if len(evidence)!=1 or evidence[0].get('model_receipt_revision')!=qa_receipt_revision(job,task,candidate):
            raise ValueError('QA receipt set does not match approved evidence')
        root=qa_receipt_root(job,task,candidate);receipts=list(root.glob('*.json'))
        if not receipts:raise ValueError('QA raw receipt evidence missing')
        for path in receipts:
            add(prefix+'/qa/'+path.name,path)
            if path.with_suffix('.response').is_file():add(prefix+'/qa/'+path.with_suffix('.response').name,path.with_suffix('.response'))
    family=read_json(job/'source/product_family_v3.json')
    from .source_fetch.apify import raw_source_directory
    for asin,digest in family['source'].get('raw_sha256',{}).items():
        add('evidence/source/'+asin+'.json',raw_source_directory(job,family['family']['marketplace'])/(asin+'.json'),digest)


def _redact(value,mapping):
    if isinstance(value,Path):value=str(value)
    if isinstance(value,dict):
        return {key:_redact(item,mapping) for key,item in value.items()
            if str(key).lower() not in {'api_key','api_token','authorization','secret','secret_access_key','access_key_id','bearer_token',
                'upload_url','upload_base','config_path','http_proxy','https_proxy','all_proxy','headers'}
            and not re.search(r'upload.*url',str(key),re.I)}
    if isinstance(value,list):return [_redact(v,mapping) for v in value]
    if isinstance(value,str):
        if value in mapping:return mapping[value]
        if re.match(r'^[A-Za-z]:[\\/]|^/',value):return '[non-delivery local diagnostic path omitted]'
        from urllib.parse import urlparse
        def scrub(match):
            url=match[0];parts=urlparse(url)
            if parts.username or parts.password or '/p/' in parts.path or re.search('token|api.?key|secret|signature',parts.query,re.I):
                return '[credential-bearing diagnostic URL omitted]'
            return url
        return re.sub(r'https?://[^\s"<>]+',scrub,value)
    return value


def commit_delivery(job_dir,plugin, *, config_path=''):
    from .release_manifest import build_release_manifest,release_submit_ready,release_order_complete
    from .template_contract import template_plan_current
    from .publish import url_record_current
    job=Path(job_dir).resolve();release=build_release_manifest(job_dir=job,plugin=plugin)
    if not release_submit_ready(release):raise ValueError('Whole family release is incomplete; no delivery commit')
    if not template_plan_current(job_dir=job,plugin=plugin,config_path=config_path,mode='submit_ready',write_excel=True):
        raise ValueError('Current submit-ready workbook missing/stale; no delivery commit')
    plan=read_json(job/'template/plan.json')
    if any(r.get('severity')=='error' for r in plan.get('audit',[])):raise ValueError('Blocking template audit')
    selected={'listing.xlsm':resolve_job_owned_path(job,plan['output_path']),
        'listing_data.json':job/'template/listing_data.json','copy.json':job/'reports/copy_v1.json',
        'product_facts.json':job/'source/product_family_v3.json','release.json':job/'reports/release_manifest_v6.json',
        'qa.jsonl':job/'reports/qa_evidence_v5.jsonl','template_plan.json':job/'template/plan.json',
        'image_urls.csv':job/'images/_r2_image_urls.csv'}
    generated={};policy=read_json(job/'job.json').get('publication_policy')
    import io
    url_bytes=_bounded_bytes(selected['image_urls.csv'])
    urls=list(csv.DictReader(io.StringIO(url_bytes.decode('utf-8-sig'))))
    url_source_sha=hashlib.sha256(url_bytes).hexdigest()
    approved=[r for r in release['rows'] if r['final_decision']=='approved']
    from .publish import _required_rows_from_published
    verified=[u for u in urls if u.get('url','').startswith('https://') and url_record_current(u,policy)
              and any((u.get('child'),u.get('role'),u.get('candidate_sha256'))==(r['child'],r['role'],r['candidate_sha256']) for r in approved)]
    needed,missing=_required_rows_from_published(release,approved,{(u['child'],u['role']) for u in verified})
    if missing:raise ValueError('Required publication is incomplete: '+', '.join(missing))
    used={(r['child'],r['role']) for r in needed}
    for child in read_json(selected['listing_data.json']).get('children',[]):
        images=child.get('images') or {}
        for url in [images.get('main'),*images.get('other',[])]:
            if not url:continue
            matches=[u for u in verified if u['child']==child['asin'] and u['url']==url]
            if len(matches)!=1:raise ValueError('An actual template image lacks current approved publication evidence')
            used.add((matches[0]['child'],matches[0]['role']))
    required_urls=[]
    for row in approved:
        matching=[u for u in verified if (u['child'],u['role'],u['candidate_sha256'])==(row['child'],row['role'],row['candidate_sha256'])]
        if (row['child'],row['role']) in used:
            if len(matching)!=1:raise ValueError('Required URL is missing, stale or ambiguous')
            required_urls.append({k:matching[0][k] for k in ('child','role','candidate_sha256','url')})
        image=resolve_job_owned_path(job,row['local_path'])
        if file_sha256(image)!=row['candidate_sha256']:raise ValueError('Approved image changed')
        selected[f"images/{row['child']}/{row['role']}.png"]=image
    _bound_evidence(job,approved,selected,generated)
    review=job/'reports/human_review_v5.json'
    if review.is_file():selected['evidence/human_review.json']=review
    mapping={}
    for name,path in selected.items():
        mapping[str(path.resolve())]=name;mapping[path.relative_to(job).as_posix()]=name
    context=_context(job);bindings={};total=0;source_seen={}
    context['delivery']={'completion':'order_complete' if release_order_complete(release) else 'listing_ready',
                         'required_urls':required_urls}
    folder=job/'delivery';folder.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=folder));archive=staging/'listing-package.zip'
    def encode(value):return json.dumps(_redact(value,mapping),ensure_ascii=False,sort_keys=True).encode()
    def chunks(name,path):
        if name.endswith(('.json','.response')):
            raw=_bounded_bytes(path);source_seen[name]=hashlib.sha256(raw).hexdigest()
            yield encode(json.loads(raw.decode('utf-8-sig')))
        elif name.endswith('.jsonl'):
            digest=hashlib.sha256()
            with path.open('rb') as handle:
                for line in iter(lambda:handle.readline(MAX_STRUCTURED_BYTES+1),b''):
                    if len(line)>MAX_STRUCTURED_BYTES:raise ValueError('Evidence line exceeds serialization bound')
                    digest.update(line)
                    if line.strip():yield encode(json.loads(line.decode('utf-8-sig')))+b'\n'
            source_seen[name]=digest.hexdigest()
        elif name=='image_urls.csv':
            source_seen[name]=url_source_sha
            buffer=io.StringIO();fields=('child','role','candidate_sha256','upload_sha256','upload_encoding','url','verified_at','verified_sha256','valid_until','retention_source','publication_policy_sha256')
            writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader()
            writer.writerows({key:row.get(key,'') for key in fields} for row in verified);yield buffer.getvalue().encode()
        else:
            with path.open('rb') as handle:yield from iter(lambda:handle.read(65536),b'')
    def add(bundle,name,parts):
        nonlocal total
        if '\\' in name or name.startswith('/') or '..' in Path(name).parts:raise ValueError('Unsafe archive member')
        digest=hashlib.sha256()
        with bundle.open(name,'w') as member:
            for part in parts:
                total+=len(part)
                if total>MAX_ARCHIVE_BYTES:raise ValueError('Archive exceeds local verification bound')
                member.write(part);digest.update(part)
        return digest.hexdigest()
    try:
        with ZipFile(archive,'w',ZIP_DEFLATED) as bundle:
            for name,path in selected.items():
                source_sha=file_sha256(path);digest=add(bundle,name,chunks(name,path))
                bindings[name]={'source':path.relative_to(job).as_posix(),'source_sha256':source_sha,'sha256':digest}
                if source_seen.get(name,source_sha)!=source_sha or file_sha256(path)!=source_sha:raise ValueError('Delivery inputs changed during assembly')
                if not name.endswith(('.json','.jsonl','.response','.csv')) and digest!=source_sha:raise ValueError('Binary evidence changed while streaming')
            for name,value in generated.items():bindings[name]={'source':None,'sha256':add(bundle,name,[encode(value)])}
            text=b'Immutable distribution archive; not Amazon submission. Raw private HTTP is retained locally, represented by its original SHA. Archive integrity and current eligibility are different.\n'
            bindings['README.txt']={'source':None,'sha256':add(bundle,'README.txt',[text])}
            revision=input_revision_id({'policy':POLICY,'files':bindings,'context':context})
            embedded={'schema':SCHEMA,'revision':revision,'files':bindings,'context':context}
            add(bundle,'package.json',[json.dumps(embedded,ensure_ascii=False,sort_keys=True).encode()])
        if any(file_sha256(selected[name])!=row['source_sha256'] for name,row in bindings.items() if row['source']):raise ValueError('Delivery inputs changed during assembly')
        if {k:v for k,v in context.items() if k!='delivery'}!=_context(job):raise ValueError('Delivery decisions changed during assembly')
        manifest={**embedded,'archive':archive.name,'archive_sha256':file_sha256(archive),'status':'committed',
                  'delivered_at':time.time(),'amazon_submission':'not_submitted'}
        write_json(staging/'commit.json',manifest);verify_delivery(staging)
        destination=folder/revision
        if not destination.exists():os.replace(staging,destination)
        result=verify_delivery(destination)
        write_json(folder/'current.json',{'revision':revision});return result
    finally:
        if staging.exists():shutil.rmtree(staging)


def verify_delivery(directory):
    folder=Path(directory).resolve();manifest=read_json(folder/'commit.json')
    if manifest.get('schema')!=SCHEMA or manifest.get('status')!='committed':raise ValueError('No current-format committed archive')
    expected=input_revision_id({'policy':POLICY,'files':manifest['files'],'context':manifest['context']})
    if manifest.get('revision')!=expected or manifest.get('archive')!='listing-package.zip':raise ValueError('Delivery manifest identity changed')
    archive=folder/manifest['archive']
    if file_sha256(archive)!=manifest['archive_sha256']:raise ValueError('Delivery archive changed')
    with ZipFile(archive) as bundle:
        names=bundle.namelist()
        if len(names)!=len(set(names)) or set(names)!={*manifest['files'],'package.json'}:raise ValueError('Archive inventory changed')
        if any('\\' in n or n.startswith('/') or '..' in Path(n).parts for n in names):raise ValueError('Unsafe archive member')
        if sum(info.file_size for info in bundle.infolist())>MAX_ARCHIVE_BYTES:raise ValueError('Archive exceeds local verification bound')
        if bundle.getinfo('package.json').file_size>MAX_STRUCTURED_BYTES:raise ValueError('Embedded manifest exceeds serialization bound')
        if json.loads(bundle.read('package.json'))!={k:manifest[k] for k in ('schema','revision','files','context')}:raise ValueError('Embedded identity changed')
        for name,row in manifest['files'].items():
            digest=hashlib.sha256()
            with bundle.open(name) as member:
                for chunk in iter(lambda:member.read(65536),b''):digest.update(chunk)
            if digest.hexdigest()!=row['sha256']:raise ValueError('Archive member changed: '+name)
    return {**manifest,'directory':str(folder),'download_path':str(archive)}


def archive_delivery(job_dir,revision=None):
    job=Path(job_dir).resolve()
    revision=revision or read_json(job/'delivery/current.json')['revision']
    if not re.fullmatch('[0-9a-f]{64}',revision):raise ValueError('Invalid archive revision')
    result=verify_delivery(resolve_job_owned_path(job/'delivery',revision))
    if result['revision']!=revision:raise ValueError('Archive pointer changed')
    return result


def current_delivery(job_dir):
    from .publish import url_record_current
    job=Path(job_dir).resolve();result=archive_delivery(job)
    if {k:v for k,v in result['context'].items() if k!='delivery'}!=_context(job):raise ValueError('Listing facts or decisions differ from delivery commit')
    for row in result['files'].values():
        if row['source'] and file_sha256(resolve_job_owned_path(job,row['source']))!=row['source_sha256']:
            raise ValueError('Current source differs from delivered revision; new commit required')
    with (job/'images/_r2_image_urls.csv').open(encoding='utf-8-sig',newline='') as handle:urls=list(csv.DictReader(handle))
    for needed in result['context']['delivery']['required_urls']:
        matching=[row for row in urls if all(row.get(k)==v for k,v in needed.items())]
        if len(matching)!=1 or not url_record_current(matching[0],result['context']['job'].get('publication_policy')):
            raise ValueError('Publication verification expired/revoked; refresh publishing, never regenerate images')
    return result

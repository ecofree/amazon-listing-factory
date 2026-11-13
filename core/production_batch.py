"""Persistent batch entry to the existing production stage controller, one process per job."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from functools import lru_cache

import psutil

from .batch_ledger import BatchLedger, identity, order_identity, REVIEW_PREFIX, COMPLETION_SERVICES
from .io import file_sha256, read_json, write_json
from .paths import FACTORY_ROOT
from .process_lock import stop_process


def _connection_independent(value):
    """Execution semantics, not current credentials. Never used as QA evidence."""
    import re
    from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
    secret=re.compile(r'^(key|token|access_token|api_?key|api_?token|x_api_key|authorization|proxy_authorization|bearer_token|secret.*|password)$',re.I)
    if isinstance(value,dict):return {k:_connection_independent(v) for k,v in value.items() if not secret.fullmatch(k.replace('-','_'))}
    if isinstance(value,list):return [_connection_independent(v) for v in value]
    if isinstance(value,str) and value.startswith(('https://','http://')):
        parsed=urlsplit(value);host=parsed.hostname or ''
        if ':' in host:host='['+host+']'
        if parsed.port:host+=':'+str(parsed.port)
        query=urlencode([(k,'<credential>' if re.search('key|token|secret|signature',k,re.I) else v) for k,v in parse_qsl(parsed.query,keep_blank_values=True)])
        return urlunsplit((parsed.scheme,host,re.sub(r'/p/[^/]+/','/p/<credential>/',parsed.path),query,parsed.fragment))
    return value


def configuration_revision(config_path, *, metadata_config=''):
    from .io import environment_values
    import re
    values=environment_values(FACTORY_ROOT/'config.env',FACTORY_ROOT/'config.local.env',metadata_config,config_path)
    registry=(json.loads(values['AMAZON_FACTORY_API_REGISTRY']) if values.get('AMAZON_FACTORY_API_REGISTRY') else
              read_json(Path(values.get('AMAZON_FACTORY_API_REGISTRY_FILE') or FACTORY_ROOT/'configs/api_registry.json')))
    from .api_registry import _items_from_payload
    entries=_items_from_payload(registry)
    aliases={r.get(k) for r in entries if isinstance(r,dict) for k in ('key_env','api_key_env','bearer_env','bearer_token_env','token_env','authorization_env')}
    semantic={k:_connection_independent(v) for k,v in values.items() if k not in aliases
        and not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|SECRET(?:_ACCESS_KEY)?|ACCESS_KEY_ID|BEARER_TOKEN|PASSWORD|TOKEN)$',k,re.I)
        and k.upper() not in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','AMAZON_FACTORY_API_REGISTRY'}}
    return identity({'environment':semantic,'registry':_connection_independent(registry)})


def _config_file_revision(path):
    try:return identity(_connection_independent(read_json(path)))
    except ValueError:return identity({'invalid_configuration_sha256':file_sha256(path)})


def _ui_execution_revision(text):
    from html.parser import HTMLParser
    class Contract(HTMLParser):
        def __init__(self):super().__init__();self.script=False;self.parts=[]
        def handle_starttag(self,tag,attrs):
            if tag=='script':self.script=True
            if tag in {'script','form','input','select','option','button','textarea'}:
                self.parts.append((tag,sorted((k,v) for k,v in attrs if k not in {'class','style'})))
        def handle_endtag(self,tag):
            if tag=='script':self.script=False
        def handle_data(self,data):
            if self.script:self.parts.append(data)
    parser=Contract();parser.feed(text);return identity(parser.parts)


def production_revision():
    files = [path for folder in ('core', 'products', 'schemas', 'configs', 'scripts')
             for path in (FACTORY_ROOT / folder).rglob('*')
             if path.is_file() and path.suffix in {'.py', '.json', '.yaml', '.ps1', '.html', '.js'} and '__pycache__' not in path.parts]
    return identity({path.relative_to(FACTORY_ROOT).as_posix():
                     _ui_execution_revision(path.read_text(encoding='utf-8-sig')) if path.suffix=='.html' else
                     _config_file_revision(path) if path.suffix=='.json' and path.is_relative_to(FACTORY_ROOT/'configs') else file_sha256(path)
                     for path in sorted(files)})


def create_batch(path, manifest):
    """Per-item admission receipts; atomic means all-or-none ledger enrollment."""
    from .batch_ledger import _validate_policy
    from .job import create_job, resume_job_initialization
    from .plugin import load_plugin
    import inspect,re
    policy=manifest['policy'];_validate_policy(policy)
    entries=manifest.get('jobs');atomic=manifest.get('atomic',False)
    if not isinstance(entries,list) or not entries or type(atomic) is not bool:
        raise ValueError('Explicit job list and boolean atomic policy required')
    fields=set(inspect.signature(create_job).parameters)-{'plugin','out_root','timestamp','initialization_key','reserved_path'}
    allowed=fields|{'category','production','upload','limit','child_ids','stages','purpose','max_paid_calls','budget_microunits'}
    ledger=BatchLedger(path);root=ledger.path.parent/'new_jobs';prepared=[];receipts=[]
    for index,original in enumerate(entries):
        try:
            if not isinstance(original,dict) or set(original)-allowed:raise ValueError('Unknown job input; retry permission belongs to a receipt, not a persistent worker switch')
            spec=dict(original)
            if not re.fullmatch('[A-Z0-9]{10}',str(spec.get('seed_asin',''))):raise ValueError('Invalid seed_asin')
            if any(type(spec.get(k,True)) is not bool for k in ('production','upload')):raise ValueError('Production and upload must be booleans')
            if 'max_family_members' in spec and (type(spec['max_family_members']) is not int or spec['max_family_members'] < 1):
                raise ValueError('max_family_members must be a positive candidate selection limit')
            children=spec.get('child_ids',[]);limit=spec.get('limit',0)
            if type(limit) is not int or limit<0:raise ValueError('Child limit must be a nonnegative integer')
            if not isinstance(children,list) or any(not isinstance(c,str) or not re.fullmatch('[A-Z0-9]{10}',c) for c in children) or len(set(children))!=len(children):raise ValueError('Explicit child IDs must be unique ASINs')
            if children and limit:raise ValueError('Use explicit child IDs or a child limit, not both')
            if spec.get('production',True) and (limit or children):raise ValueError('Production requires the full family, not a child selection')
            if not all(str(spec.get(k) or '').strip() for k in ('seller_id','brand','sku_prefix')):raise ValueError('Seller identity, brand and SKU prefix required')
            if spec.get('execution_policy','progressive') not in {'strict','progressive'}:raise ValueError('Unknown execution policy')
            plugin=load_plugin(spec['category'])
            if plugin.manifest.get('lifecycle')!='production_ready':raise ValueError('Unsupported production category')
            config=Path(spec.get('config_path') or FACTORY_ROOT/'config.local.env').resolve()
            if not config.is_file():raise ValueError('Explicit execution configuration file is missing')
            spec.update(config_path=str(config),config_semantics_sha256=configuration_revision(config))
            if spec.get('business_input_path'):spec['business_input_sha256']=file_sha256(Path(spec['business_input_path']))
            key=order_identity(spec);prepared.append((index,spec,root/f"{spec['seed_asin']}_{key[:20]}"))
        except (ValueError,OSError,KeyError,TypeError) as exc:
            receipts.append({'index':index,'status':'rejected','error':str(exc)})
    if atomic and receipts or not prepared:
        raise ValueError('No enrollment performed: '+json.dumps(receipts,ensure_ascii=False))
    ledger.require_workspace()
    if not ledger.path.exists():
        try:ledger.create(policy=policy,source_revision=production_revision())
        except FileExistsError:pass  # A concurrent complete publication is checked below.
        ledger.pause()
    if ledger.settings()['policy']!=policy:raise ValueError('Existing workspace spending policy cannot be replaced by a group')
    group=str(manifest.get('group_id') or 'default')
    atomic_rows=ledger.enqueue_many([(s,p) for _,s,p in prepared],group=group) if atomic else None
    for position,(index,spec,target) in enumerate(prepared):
        row=None
        try:
            row=atomic_rows[position] if atomic_rows is not None else ledger.enqueue(spec,target,group=group)
            target=Path(row['path']);key=row['id'];result='reused'
            from .process_lock import process_file_lock
            with process_file_lock(ledger.path.parent/'initializers'/(key+'.lock')):
                row=next(current for current in ledger.rows() if current['id']==key)
                if row['state']=='initializing':
                    if (target/'initialization.json').is_file():
                        resume_job_initialization(target,expected_key=identity(spec))
                    else:
                        create_job(plugin=load_plugin(spec['category']),out_root=root,timestamp=key[:20],
                            reserved_path=target,initialization_key=identity(spec),**{k:v for k,v in spec.items() if k in fields})
                    ledger.initialized(key);result='accepted'
            receipts.append({'index':index,'id':key,'status':result})
        except (ValueError,OSError,KeyError,TypeError) as exc:
            receipts.append({'index':index,'id':row['id'] if row else None,
                             'status':'initialization_incomplete' if row else 'rejected','error':str(exc)})
    ledger.enrollment_results=sorted(receipts,key=lambda r:r['index'])
    return ledger


RECEIPT_LOCATIONS=('reports/image_responses','source/apify_requests','reports/copy_requests',
    'reports/ocr_evidence/requests','reports/qa_ocr_evidence/requests','reports/source_observations/requests',
    'reports/qa_requests','reports/storage_requests','reports/storage_verifications')


def authority_receipts(job):
    return [p for folder in RECEIPT_LOCATIONS for p in (Path(job)/folder).rglob('*.json')]


@lru_cache(maxsize=2048)
def _arrival_digest(path, size, mtime_ns, ctime_ns):
    # A polling hint only. Every consuming owner independently validates bytes;
    # these cached hints cannot qualify a candidate, settle money or allow POST.
    return file_sha256(Path(path)) if size<=128*1024*1024 else 'oversize-arrival'


def review_revision(job, *, ledger=None):
    job = Path(job)
    files = [job / 'job.json', job / 'source/product_family_v3.json', job / 'reports/human_review_v5.json', job / 'reports/source_intent_reviews_v1.jsonl']
    decisions={str(p.relative_to(job)):file_sha256(p) for p in files if p.is_file()}
    state=read_json(job/'job_state.json') if (job/'job_state.json').is_file() else {}
    row=next((r for r in ledger.rows() if Path(r['path']).resolve()==job.resolve()),None) if ledger else None
    selected=(json.loads(row['resume_stages']) if row.get('resume_stages') else json.loads(row['spec']).get('stages')) if row else None
    pending=[t for t in (state.get('tasks') or {}).values() if t.get('status') not in {'success','skipped','deferred','not_required'}
             and (not selected or t.get('owner_stage') in selected)
             and t.get('request_outcome')!='unknown' and t.get('remote_request_allowed') is not False]
    failure=read_json(job/'reports/batch_failure.json') if (job/'reports/batch_failure.json').is_file() else {}
    budget_codes={'request_budget_exhausted','completion_capacity_reserved','order_money_blocked','workspace_money_blocked'}
    budget=[t for t in pending if t.get('reason_code') in budget_codes]
    failed_admission=bool(row and failure.get('attempt')==row['attempt'] and failure.get('reason_code') in budget_codes)
    if row and (budget or failed_admission):
        services={s for t in budget for s in COMPLETION_SERVICES.get(t.get('owner_stage'),())}
        if failed_admission and failure.get('service'):services.add(failure['service'])
        decisions['failed_request_capacity_available']=ledger.free_capacity_available(key=row['id'],services=services)
    # Only a failed service depends on its connections; contract/receipt waits do not.
    connection_stages={t.get('owner_stage') for t in pending if t.get('status')=='retryable'
        and t.get('reason_code') not in budget_codes|{'local_commit_pending','contract_repairable','protocol_incomplete','needs_region','needs_confirmation','needs_policy_confirmation','local_tool_failed'}}
    if connection_stages and (job/'job.json').is_file():
        from .io import environment_values
        metadata=read_json(job/'job.json')
        connections=environment_values(FACTORY_ROOT/'config.env',FACTORY_ROOT/'config.local.env',metadata.get('config_path',''))
        registry=Path(connections.get('AMAZON_FACTORY_API_REGISTRY_FILE') or FACTORY_ROOT/'configs/api_registry.json')
        from .api_registry import _items_from_payload,_normalize_entry
        payload=json.loads(connections['AMAZON_FACTORY_API_REGISTRY']) if connections.get('AMAZON_FACTORY_API_REGISTRY') else read_json(registry)
        scopes={scope for stage,scope in {'classify':'visual_planning','brief':'visual_planning','generate':'image_generation','qa':'vision_qa'}.items() if stage in connection_stages}
        entries=[item for item in _items_from_payload(payload) if (entry:=_normalize_entry(item)) and scopes.intersection(entry.scopes)]
        variables={value for item in entries for name,value in item.items() if name.endswith('_env') and isinstance(value,str)}
        prefixes=tuple(prefix for stage,prefixes in {'fetch':('APIFY_',),'copy':('COPY_','DEEPSEEK_'),'classify':('OCR_',),
                         'publish':('R2_','OCI_','ORACLE_')}.items() if stage in connection_stages for prefix in prefixes)
        decisions['failed_service_connections']=identity({'entries':entries,'values':{k:v for k,v in connections.items() if k in variables or prefixes and k.startswith(prefixes)}})
    # Owner receipts/local arrivals wake existing work for owner validation.
    # Polling never re-hashes all finalized images; a wake is not new permission.
    for path in authority_receipts(job):
        row=read_json(path)
        if not isinstance(row,dict):raise ValueError('Receipt authority is not an object')
        key=path.relative_to(job).as_posix()
        if row.get('resolution'):decisions[key]=row['resolution']
        for field,suffix in (('response_sha256','.response'),('raw_sha256','.bin'),('body_sha256','.http')):
            saved=path.with_suffix(suffix)
            if row.get(field):
                decisions[key+suffix]={'declared_sha256':row[field],'status':row.get('status'),'local_finalization':row.get('local_finalization')}
            elif saved.is_file() and row.get('status') in {'submitted','unknown','received'}:
                stat=saved.stat()
                decisions[key+suffix]={'unsettled_arrival':_arrival_digest(str(saved),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)}
    family=read_json(job/'source/product_family_v3.json') if (job/'source/product_family_v3.json').is_file() else {}
    from .planning_journal import journal_path
    for child in (family.get('family') or {}).get('children',[]):
        path=journal_path(job,child['asin'])
        if path.is_file():
            row=read_json(path);decisions[path.relative_to(job).as_posix()]={
                'grants':row.get('grants',[]),'adoptions':row.get('operation_authorizations',[]),
                'restorations':{k:r for k,r in row.get('restorations',{}).items() if r.get('status') in {'completed','cancelled'}},
                'received':{k:r['result_sha256'] for k,r in row.get('requests',{}).items() if r.get('status')=='received'
                            and r.get('result_path') and r.get('result_sha256')
                            and (job/r['result_path']).resolve().is_relative_to(job.resolve())
                            and (job/r['result_path']).is_file()},
                'resolutions':{k:r['resolution'] for k,r in row.get('requests',{}).items() if r.get('resolution')}}
    for path in [*(job/'reports/image_contract_reprojection').glob('*/decision.json'),*(job/'reports/scope_promotions').glob('*.json')]:
        row=read_json(path)
        if row.get('status') in {'completed','cancelled'}:decisions[path.relative_to(job).as_posix()]=file_sha256(path)
    return REVIEW_PREFIX+identity(decisions)


def _worker(path, key, lease):
    ledger = BatchLedger(path)
    ledger.require_workspace()
    row = ledger.worker(key, lease)
    spec = json.loads(row['spec'])
    if production_revision() != ledger.settings()['source_revision']:
        raise ValueError('Source changed; pause and explicitly reconcile execution revision on the original workspace/order')
    metadata=read_json(Path(row['path'])/'job.json')
    if configuration_revision(spec['config_path'],metadata_config=metadata.get('config_path','')) != spec.get('config_semantics_sha256'):
        raise ValueError('Effective execution policy changed after admission; credential rotation alone does not require reapproval')
    os.environ.update(FACTORY_BATCH_DB=str(ledger.path), FACTORY_BATCH_JOB=key, FACTORY_BATCH_LEASE=lease)
    from .plugin import load_plugin
    from .production import JobRunRequest, run_job
    selected_stages=json.loads(row['resume_stages']) if row.get('resume_stages') else spec.get('stages')
    request = JobRunRequest(job_dir=Path(row['path']), plugin=load_plugin(spec['category']),
        config_path=spec['config_path'], workers=1, limit=int(spec.get('limit', 0)), child_ids=tuple(spec.get('child_ids', ())),
        production=spec.get('production', True), upload=spec.get('upload', True), write_excel=True,
        execution_policy=spec.get('execution_policy', 'progressive'),
        resume=True, all_generation_tasks=not selected_stages or 'generate' in selected_stages,
        deadline_monotonic=time.monotonic() + max(0, row['lease_until'] - time.time()))
    try:
        run_job(request, stages=selected_stages)
    except Exception as exc:
        cause=exc;seen=set()
        while not getattr(cause,'reason_code',None) and (cause.__cause__ or cause.__context__) and id(cause) not in seen:
            seen.add(id(cause));cause=cause.__cause__ or cause.__context__
        write_json(Path(row['path']) / 'reports/batch_failure.json',
                   {'lease': lease, 'attempt':row['attempt'], 'error': f'{type(exc).__name__}: {exc}'[:2000],
                    'reason_code':getattr(cause,'reason_code',''), 'service':getattr(cause,'service','')})
        raise


def _settle(ledger, row, *, expired=False):
    job = Path(row['path'])
    try:
        from .delivery_package import current_delivery
        package = current_delivery(job)
        if package['context']['delivery']['completion']=='order_complete':
            ledger.complete(row, state='delivered', package=package['revision'])
            return
    except (OSError, ValueError, KeyError):
        pass
    policy = ledger.settings()['policy']
    summary_path = job / 'reports/production_summary_v3.json'
    state_path = job / 'job_state.json'
    failure_path = job / 'reports/batch_failure.json'
    try:
        summary = read_json(summary_path) if summary_path.is_file() else {}
        state = read_json(state_path) if state_path.is_file() else {}
        failure = read_json(failure_path) if failure_path.is_file() else {}
        if not all(isinstance(value, dict) for value in (summary, state, failure)):
            raise ValueError('Job evidence must contain objects')
    except (OSError, ValueError) as exc:
        ledger.complete(row, state='exception', reason=f'Unreadable job evidence: {type(exc).__name__}',
                        review_revision=REVIEW_PREFIX+'unreadable')
        return
    # A completed requested stage range is not a delivery package or a failure.
    spec=json.loads(row['spec'])
    requested=json.loads(row['resume_stages']) if row.get('resume_stages') else spec.get('stages')
    selected_stages=set(requested or [])
    def task_in_scope(task):
        owner=str(task.get('owner_stage') or '')
        if owner:return not selected_stages or owner in selected_stages
        prefix=str(task.get('logical_task_id') or '').split(':',1)[0]
        return not selected_stages or not prefix or prefix in selected_stages
    all_tasks=list((state.get('tasks') or {}).values())
    tasks=[task for task in all_tasks if task_in_scope(task)]
    selection=state.get('generation_execution_scope') or {};execution=summary.get('generation_invocation') or {}
    limited=requested==['generate'] and selection.get('mode')=='selected'
    if limited:
        attempt=(state.get('stages',{}).get('generate') or {}).get('attempt_id')
        tasks=[task for task in tasks if task.get('attempt_id')==attempt]
        count=len(selection.get('tasks') or [])
        selection_complete=bool(not summary.get('error') and summary.get('workflow_status')!='failed'
            and execution.get('mode')=='selected' and attempt and execution.get('attempt_id')==attempt and count
            and selection.get('selection_sha256') and execution.get('selection_sha256')==selection['selection_sha256'] and execution.get('tasks')==selection['tasks']
            and execution.get('status')=='success' and execution.get('requested_count')==execution.get('completed_count')==count
            and execution.get('failed_count')==execution.get('blocked_count')==0)
    selected_tasks_settled=all(str(task.get('status') or '') in {'success','deferred','skipped','not_required'} for task in tasks)
    from datetime import datetime
    try:fresh=datetime.fromisoformat(summary.get('snapshot_at','')).timestamp() >= row['started']
    except (ValueError,TypeError):fresh=False
    if fresh and spec.get('max_family_members') and summary.get('selection_excluded'):
        ledger.complete(row, state='cancelled', reason=summary['selection_excluded'])
        return
    if (requested and 'template' not in requested and fresh and selected_tasks_settled
            and summary.get('run_environment',{}).get('stages')==requested
            and all(stage in summary.get('stage_times',{}) and (selection_complete if limited else
                state.get('stages',{}).get(stage,{}).get('status')=='success') for stage in requested)
            and not (row.get('lease') and failure.get('lease')==row['lease'])):
        ledger.complete(row,state='completed',reason=(f'Selected {count}/{count} generation tasks completed; whole-job coverage reported separately'
            if limited else 'Requested stages completed through '+requested[-1]+'; downstream not requested'))
        return
    waiting = any(
        str(task.get('status')) in {'remote_unknown', 'awaiting_review', 'blocked', 'needs_review', 'review'}
        or task.get('request_outcome') == 'unknown' for task in tasks)
    retryable = (expired and not waiting) or any(task.get('status')=='retryable' and task.get('request_outcome')!='unknown' for task in tasks)
    reason = ('Worker deadline/interruption; receipts retained' if expired else
              str(summary.get('workflow_status') or 'worker_failed'))
    if row.get('lease') and failure.get('lease') == row['lease']:
        reason += ': ' + str(failure.get('error') or 'Worker initialization failed')
    errors = list(dict.fromkeys(str(task.get('error')) for task in tasks if task.get('status') != 'success' and task.get('error')))
    if errors:
        reason += ': ' + ' | '.join(error[:420] for error in errors[:2])
    if retryable and row['automatic_retries'] < policy.get('max_attempts',1)-1:
        ledger.complete(row, state='retry', reason=reason, due=time.time() + min(300, 10 * 2 ** row['attempt']))
    else:
        ledger.complete(row, state='exception', reason=reason, review_revision=review_revision(job,ledger=ledger))


def refresh_operational_alerts(ledger):
    """Local monitor of enrolled authorities only; no network, decisions or dispatch."""
    from datetime import datetime,timezone
    policy=ledger.settings()['policy'];now=time.time();sla=policy.get('unknown_sla_seconds',300)
    for row in ledger.rows():
        job=Path(row['path'])
        if row['state'] in {'cancelled','initializing'}:continue
        try:
            for receipt in authority_receipts(job):
                data=read_json(receipt)
                if not isinstance(data,dict):raise ValueError('Receipt authority is not an object')
                if data.get('status') not in {'submitted','unknown'}:continue
                stamp=data.get('submitted_at')
                if stamp and now-datetime.fromisoformat(stamp).timestamp()>sla:
                    ledger.record_alert(row['id'],'unknown_over_sla','Original request remains unresolved: '+receipt.relative_to(job).as_posix())
            family_path=job/'source/product_family_v3.json'
            family=read_json(family_path) if family_path.is_file() else {}
            from .planning_journal import journal_path
            from .paths import resolve_job_owned_path
            for child in family.get('family',{}).get('children',[]):
                journal=resolve_job_owned_path(job,journal_path(job,child['asin']))
                data=read_json(journal) if journal.is_file() else {}
                for key,request in data.get('requests',{}).items():
                    if request.get('status') in {'reserved','submitted','unknown'} and now-datetime.fromisoformat(request['created_at']).timestamp()>sla:
                        ledger.record_alert(row['id'],'planning_unknown_over_sla',f"{child['asin']} / {key}: retain original request; no automatic retry")
            if row['state']=='delivered':
                from .publish import url_record_current
                import csv
                metadata=read_json(job/'job.json')
                if metadata.get('business_input'):
                    from .job import _validate_business_input
                    _validate_business_input(metadata['business_input'],metadata)
                with (job/'images/_r2_image_urls.csv').open(encoding='utf-8-sig',newline='') as handle:urls=list(csv.DictReader(handle))
                if not urls or any(not url_record_current(r,metadata.get('publication_policy')) for r in urls):
                    ledger.record_alert(row['id'],'publication_expired','Refresh publication verification/retention; archived package remains separate')
        except (OSError,ValueError,KeyError,RuntimeError) as exc:
            ledger.record_alert(row['id'],'evidence_unavailable',str(exc))


def run_batch(path, *, drain=False, poll_seconds=2, stop_event=None):
    ledger = BatchLedger(path)
    ledger.require_workspace()
    settings = ledger.settings()
    if settings['source_revision'] != production_revision():
        raise ValueError('Batch source fingerprint is stale; no worker launched')
    policy = settings['policy']
    dispatcher=f'{os.getpid()}:{psutil.Process().create_time()}'
    active = {};next_monitor=0.0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():ledger.pause()
            ledger.heartbeat(dispatcher)
            if production_revision()!=settings['source_revision']:
                ledger.pause();ledger.record_alert('workspace','execution_revision_changed','Source changed; explicit source reconciliation required, no new spending domain')
            if time.monotonic()>=next_monitor:
                refresh_operational_alerts(ledger);next_monitor=time.monotonic()+30
            now = time.time()
            for row in ledger.rows():
                if row['state'] == 'running':
                    process = active.get(row['id'])
                    expired = now >= row['lease_until']
                    alive = process.poll() is None if process else (not row['pid'] and not expired) or _alive(row)
                    if expired or not alive:
                        if row['pid']:
                            stop_process(row['pid'], row['process_start'])
                        if process:
                            process.wait(timeout=5)
                            active.pop(row['id'], None)
                        from .batch_ledger import AdmissionDenied
                        try:
                            _settle(ledger, row, expired=expired or not process)
                        except AdmissionDenied:
                            pass  # Another dispatcher already settled this fenced lease.
                elif row['state'] == 'exception':
                    try:
                        changed = review_revision(row['path'],ledger=ledger)
                        ledger.requeue(row['id'], review_revision=changed)
                    except (OSError,ValueError,KeyError):
                        continue  # Unreadable authority stays an exception; other jobs still run.
            running = sum(row['state'] == 'running' for row in ledger.rows())
            while running < policy.get('workers',1):
                row = ledger.claim(ttl=policy.get('job_timeout_seconds',7200))
                if not row:
                    break
                # Every launch has a fresh interpreter and a job-specific environment load.
                env = {key: value for key, value in os.environ.items() if not key.startswith('FACTORY_BATCH_')}
                env['PYTHONDONTWRITEBYTECODE'] = '1'
                log_path = Path(row['path']) / 'reports' / f"batch-attempt-{row['attempt']}-{row['lease']}.log"
                with log_path.open('wb') as log:
                    process = subprocess.Popen([sys.executable, '-B', '-m', 'core.production_batch',
                        '--worker', str(ledger.path), row['id'], row['lease']], cwd=FACTORY_ROOT, env=env,
                        stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                try:
                    ledger.attach_process(row, process.pid, psutil.Process(process.pid).create_time())
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                active[row['id']] = process
                running += 1
            rows = ledger.rows()
            if drain and not any(row['state'] in {'queued','retry','running'} and json.loads(row['spec']).get('purpose','production')=='production' for row in rows):
                break
            if ledger.settings()['paused'] and not any(row['state'] == 'running' for row in rows):
                break
            time.sleep(max(0.05, min(poll_seconds, 5)))
    except KeyboardInterrupt:
        ledger.pause()
        for row in ledger.rows():
            if row['id'] in active:
                stop_process(row['pid'], row['process_start'])
                active[row['id']].wait(timeout=5)
                _settle(ledger, row, expired=True)
        raise
    return {'jobs': ledger.rows(), 'cost': ledger.cost(), 'paused': bool(ledger.settings()['paused'])}


def _alive(row):
    try:
        return bool(row['pid'] and psutil.Process(row['pid']).create_time() == row['process_start'])
    except psutil.NoSuchProcess:
        return False


if __name__ == '__main__':
    if len(sys.argv) != 5 or sys.argv[1] != '--worker':
        raise SystemExit('Use factory.py batch for dispatch')
    _worker(*sys.argv[2:])

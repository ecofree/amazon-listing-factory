"""Loopback console for the existing workspace and stage decision authorities.
No model call, candidate approval shortcut, or second exception/dispatch controller.
"""
from __future__ import annotations
import json,secrets,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .batch_ledger import BatchLedger,identity
from .io import read_json,file_sha256,write_json
from .paths import resolve_job_owned_path

PAGE_PATH=Path(__file__).with_name('assets')/'batch_console.html'


def _row(ledger,key):
    value=next((r for r in ledger.rows() if r['id']==key),None)
    if value is None:raise ValueError('Order is not enrolled in this workspace')
    return value


def _optional(path,default):return read_json(path) if path.is_file() else default


def _receipts(job):
    result=[]
    from .production_batch import authority_receipts
    for path in authority_receipts(job):
        record=read_json(path)
        if not isinstance(record,dict):raise ValueError('Receipt metadata is not an object')
        result.append({'path':path.relative_to(job).as_posix(),'sha256':file_sha256(path),
            'schema':record.get('schema'),'status':record.get('status'),
            'owners':record.get('owners') or [record.get('request_audit',{}).get('logical_task_id','')],
            'request_id':record.get('id') or path.stem,'submitted_at':record.get('submitted_at'),
            'resolution':record.get('resolution'),'actual_cost':'unknown'})
    return result


def evidence(ledger,key):
    from .production_batch import review_revision
    row=_row(ledger,key);job=Path(row['path']);spec=json.loads(row['spec'])
    metadata=_optional(job/'job.json',{});family=_optional(job/'source/product_family_v3.json',{})
    release=_optional(job/'reports/release_manifest_v6.json',{})
    receipts=_receipts(job)
    safe_fields=('seed_asin','brand','seller_id','marketplace','category_id','sku_prefix','gtin_exempt','business_input','publication_policy','execution_policy')
    from .template_runtime import child_sku
    children=family.get('family',{}).get('children',[])
    declarations=[{'child':c['asin'],'sku':child_sku(metadata,c,i)} for i,c in enumerate(children,1)]
    planning={}
    if children:
        try:
            from .visual_design_kit import planning_status
            from .plugin import load_plugin
            planning=planning_status(job,load_plugin(spec['category']))
        except (OSError,ValueError,KeyError,RuntimeError) as exc:
            planning={'status':'currentness_blocked','reason':str(exc),'read_only':True,'requests_sent':0}
    download=_optional(job/'images/download_manifest_v2.json',{})
    sources=[{k:r.get(k) for k in ('child','index','source_index','source_sha256','raw_path','status','error','attempts')} for r in download.get('rows',[])]
    preflight=_optional(job/'reports/template_preflight_source.json',{}) or _optional(job/'reports/template_preflight_business.json',{})
    result={'id':key,'seed_asin':spec.get('seed_asin',''),'state':row['state'],'reason':row.get('reason',''),'archive_revision':row.get('package'),
        'job':{k:metadata.get(k) for k in safe_fields},'job_sha256':file_sha256(job/'job.json') if (job/'job.json').is_file() else '',
        'facts_sha256':file_sha256(job/'source/product_family_v3.json') if family else '',
        'rows':release.get('rows',[]),'sources':sources,'skus':declarations,'receipts':receipts,'planning':planning,
        'family_progress':{'target_count':family.get('source',{}).get('expected_child_count',len(children)),
                           'facts_ready_count':len(children),'pending_members':family.get('source',{}).get('child_fetch_errors',[])},
        'execution_policy':spec.get('execution_policy','progressive'),
        'preflight':preflight,'summary':_optional(job/'reports/production_summary_v3.json',{}),
        'authority_revision':review_revision(job,ledger=ledger),'requests_sent':0}
    result['snapshot']=identity({k:result[k] for k in ('job_sha256','facts_sha256','rows','sources','receipts','authority_revision','state','archive_revision')})
    return result


def status_snapshot(ledger):
    settings=ledger.settings();rows=[]
    for row in ledger.rows():
        spec=json.loads(row['spec']);job=Path(row['path'])
        item={k:row[k] for k in ('id','state','attempt','automatic_retries','elapsed','reason','package','lease_until')}
        item.update(seed_asin=spec.get('seed_asin','diagnostic'),category=spec.get('category','diagnostic'),archive_available=False,
                    current_eligibility='not_checked')
        pointer=_optional(job/'delivery/current.json',{})
        if pointer.get('revision'):
            item['archive_available']=True;item['archive_revision']=pointer['revision'];item['download']='/download/'+row['id']
            # Download verifies all bytes. Polling a status page never re-hashes a large ZIP or calls storage.
        rows.append(item)
    heartbeat=settings.get('heartbeat')
    try:ledger.require_workspace();workspace_ready=True
    except RuntimeError:workspace_ready=False
    return {'jobs':rows,'paused':bool(settings['paused']),'cost':ledger.cost(),'currency':settings['policy'].get('currency'),
        'dispatcher_alive':bool(heartbeat and time.time()-heartbeat<15),'heartbeat':heartbeat,
        'workspace_ready':workspace_ready,'alerts':ledger.alerts(),'workspace_revision':identity({k:settings[k] for k in ('policy','source_revision','paused')}),
        'notice':'Archive download is not current listing eligibility. UI alone does not start a dispatcher. Actual fees remain unreconciled.'}


def apply_action(ledger,body):
    """Serialize one decision; persisted results and original owners reconcile crashes."""
    from .process_lock import process_file_lock
    path=ledger.path.parent/'action_results'/(identity(body.get('decision_id'))+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    with process_file_lock(path.with_suffix('.lock')):
        return _apply_action_locked(ledger,body,path)


def _finish_action(ledger,body,path,result):
    write_json(path,{'request':identity(body),'result':result})
    ledger.finish_action(body['decision_id'],result)
    return result


def _reconciled_owner(ledger,body):
    action=body['action'];decision=body['decision_id']
    if action in {'pause','resume'}:
        return bool(ledger.settings()['paused'])==(action=='pause')
    if action in {'cancel','publication_refresh','acknowledge_alert','promote_scope'}:
        with ledger.transaction() as db:
            return db.execute('SELECT 1 FROM decisions WHERE id=?',(decision+'/authority',)).fetchone() is not None
    row=_row(ledger,body['id']);job=Path(row['path']);metadata=_optional(job/'job.json',{})
    if action in {'business_input','template_conditions','download_recheck'}:
        field={'business_input':'business_decisions','template_conditions':'template_decisions','download_recheck':'download_rechecks'}[action]
        return any(r['id']==decision for r in metadata.get(field,[]))
    if action in {'resolve_service','resolve_image'}:
        receipt=_optional(resolve_job_owned_path(job,body['receipt']),{})
        resolution=receipt.get('resolution') or {}
        return resolution.get('action')==body['resolution'] and resolution.get('reason')==body['reason']
    if action in {'planning_grant','planning_retry','planning_recover'}:
        from .planning_journal import journal_path
        journal=_optional(journal_path(job,body['child']),{})
        if action=='planning_grant':return any(r.get('id')==decision or r.get('grant_id')==decision for r in journal.get('grants',[]))
        request=journal.get('requests',{}).get(body['request_id'],{})
        if action=='planning_retry':return (request.get('resolution') or {}).get('reason')==body['reason']
        return request.get('status') in {'received','rejected','not_sent'}
    from .io import read_jsonl
    if action=='source_review':
        from .final_source_intents import SOURCE_INTENT_REVIEW_ARTIFACT
        path=job/'reports'/SOURCE_INTENT_REVIEW_ARTIFACT
        return any(all(r.get(k)==body.get(k) for k in ('child','source_index','role','source_sha256','reason')) for r in (read_jsonl(path) if path.is_file() else []))
    if action=='review':
        from .release_manifest import _review_rows
        review=_review_rows(job).get((body['child'],body['role'],body['candidate_sha256']),{})
        return all(review.get(k)==body.get(k) for k in ('decision','reason','resolutions'))
    return False


def _apply_action_locked(ledger,body,result_path):
    key=body.get('id') or 'workspace';decision=body.get('decision_id');action=body.get('action')
    previous=ledger.begin_action(key,decision,body)
    if previous is not None:
        if previous.get('status')!='pending_reconciliation':return previous
        if result_path.is_file():
            saved=read_json(result_path)
            if saved['request']!=identity(body):raise ValueError('Console result belongs to another decision')
            ledger.finish_action(decision,saved['result']);return saved['result']
        if _reconciled_owner(ledger,body):
            if key!='workspace':
                from .production_batch import review_revision
                ledger.requeue(key,review_revision=review_revision(_row(ledger,key)['path'],ledger=ledger),explicit=True)
            return _finish_action(ledger,body,result_path,{'status':'applied','recovered_from':'original_owner','requests_sent':0})
    try:
        if action in {'pause','resume'}:
            if body.get('expected_snapshot')!=status_snapshot(ledger)['workspace_revision']:raise ValueError('Workspace view is stale')
            if action=='resume':ledger.require_workspace()
            ledger.pause(action=='pause');result={'status':action,'requests_sent':0}
        elif action=='acknowledge_alert':
            ledger.acknowledge(body['alert_id'],decision_id=decision+'/authority',reason=body['reason']);result={'status':'acknowledged','requests_sent':0}
        elif action=='cancel':
            # Stopping an idle order must not depend on readable image artifacts.
            ledger.cancel_order(key,decision_id=decision+'/authority',reason=body['reason'])
            result={'status':'cancelled','requests_sent':0}
        else:
            row=_row(ledger,key);job=Path(row['path']);view=evidence(ledger,key)
            if row['state']=='running':raise ValueError('A worker owns this order; pause and wait for settlement before changing evidence')
            if body.get('expected_snapshot')!=view['snapshot']:raise ValueError('Order evidence changed; refresh the page before deciding')
            from .plugin import load_plugin
            plugin=load_plugin(json.loads(row['spec'])['category'])
            reason=body['reason']
            if action in {'resolve_service','resolve_image','planning_retry','planning_grant','publication_refresh','promote_scope','download_recheck'} or action=='source_review' and body.get('role')=='reobserve':
                if body.get('acknowledge_risk') is not True:raise ValueError('Explicit unchecked-by-default risk acknowledgement required; budgets are not automatically increased')
            if action=='promote_scope':
                from .run_scope import promote_run_scope
                spec=json.loads(row['spec'])
                if spec.get('purpose','production')!='production':raise ValueError('Diagnostic requests are not listing orders; no identity or budget rekey is allowed')
                result=promote_run_scope(job,decision_id=decision,reason=reason)
                revised={**spec,'production':True,'upload':True,'purpose':'production','limit':0,'child_ids':[],'stages':None}
                ledger.revise_order(key,spec=revised,expected_spec=identity(spec),decision_id=decision+'/authority',reason=reason)
            elif action=='business_input':
                from .job import update_business_inputs,_validate_business_input,load_job
                data=body['data'];_validate_business_input(data,load_job(job))
                target=job/'reports/business_inputs'/(identity(data)+'.json');write_json(target,data)
                result=update_business_inputs(job,target,expected_job_sha256=view['job_sha256'],decision_id=decision,reason=reason)
            elif action=='template_conditions':
                from .template_engine import update_template_dispositions
                result=update_template_dispositions(job,plugin,records=body['records'],expected_job_sha256=view['job_sha256'],decision_id=decision,reason=reason)
            elif action=='download_recheck':
                from .asset_manager import authorize_download_recheck
                result=authorize_download_recheck(job,body['targets'],decision_id=decision,reason=reason)
            elif action=='source_review':
                from .final_source_intents import record_source_intent_review
                result=record_source_intent_review(job,child=body['child'],source_index=int(body['source_index']),role=body['role'],reason=reason,
                    expected_source_sha256=body['source_sha256'])
            elif action=='review':
                from .release_manifest import record_human_review
                result=record_human_review(job_dir=job,plugin=plugin,**{k:body[k] for k in ('child','role','decision','candidate_sha256','resolutions')},reason=reason)
            elif action in {'resolve_service','resolve_image'}:
                from .status import job_run_lock
                matching=next((r for r in view['receipts'] if r['path']==body['receipt'] and r['sha256']==body['receipt_sha256']),None)
                if not matching:raise ValueError('Receipt is not in the displayed enrolled order evidence')
                receipt=resolve_job_owned_path(job,body['receipt'])
                with job_run_lock(job):
                    if file_sha256(receipt)!=body['receipt_sha256']:raise ValueError('Receipt changed; refresh evidence')
                    if action=='resolve_image':
                        from .image_response import resolve_response
                        result=resolve_response(job,str(receipt),action=body['resolution'],reason=reason)
                    else:
                        from .service_response import resolve_service_response
                        result=resolve_service_response(receipt,action=body['resolution'],reason=reason)
            elif action in {'planning_retry','planning_recover','planning_grant'}:
                from .status import job_run_lock
                from .planning_journal import PlanningJournal,journal_path
                from .planning_identity import journal_scope
                child=body['child']
                if child not in {s['child'] for s in view['skus']}:raise ValueError('Planning child is outside enrolled family')
                with job_run_lock(job):
                    journal=PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),initialize=False)
                    if action=='planning_grant':
                        result=journal.grant(kind=body['kind'],additional=body['additional'],grant_id=decision,reason=reason)
                    elif action=='planning_retry':result=journal.accept_retry_risk(body['request_id'],reason=reason)
                    else:
                        request=journal.read()['requests'][body['request_id']]
                        journal.settle_attempt(body['request_id'],job=job,trace=request['context']['trace'],known_unsent=request.get('physical_count')==0)
                        result=journal.read()['requests'][body['request_id']]
            elif action=='publication_refresh':
                ledger.publication_refresh(key,decision_id=decision+'/authority',reason=reason)
                result={'status':'queued_publish_and_template_only','requests_sent':0}
            else:raise ValueError('Unsupported authority action')
            from .production_batch import review_revision
            ledger.requeue(key,review_revision=review_revision(job,ledger=ledger),explicit=True)
            result={'status':'applied','owner_result':result,'requests_sent':0,'note':'Resident dispatcher may resume within the original order limits'}
        return _finish_action(ledger,body,result_path,result)
    except Exception as exc:
        if result_path.is_file():
            return {**read_json(result_path)['result'],'settlement_pending':True}
        result={'status':'rejected','error':str(exc),'requests_sent':0}
        return _finish_action(ledger,body,result_path,result)


def make_server(path, *, port=8766):
    ledger=BatchLedger(path);ledger.require_workspace();token=secrets.token_hex(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def respond(self,data, *, status=200,content_type='application/json; charset=utf-8',attachment=False):
            self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            if attachment:self.send_header('Content-Disposition','attachment; filename="listing-package.zip"')
            self.end_headers()
            if isinstance(data,Path):
                import shutil
                with data.open('rb') as handle:shutil.copyfileobj(handle,self.wfile)
            else:self.wfile.write(data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,default=str).encode())
        def host(self):
            if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':raise ValueError('Unexpected host')
        def do_GET(self):
            try:
                self.host();route=urlparse(self.path);key=route.path.split('/')[-1]
                if route.path=='/':self.respond(PAGE_PATH.read_text(encoding='utf-8').replace('__TOKEN__',token).encode(),content_type='text/html; charset=utf-8')
                elif route.path=='/api/status':self.respond(status_snapshot(ledger))
                elif route.path.startswith('/api/evidence/'):self.respond(evidence(ledger,key))
                elif route.path.startswith('/api/eligibility/'):
                    from .delivery_package import current_delivery
                    result=current_delivery(_row(ledger,key)['path']);self.respond({'eligible':True,'revision':result['revision'],'checked_at':time.time()})
                elif route.path.startswith('/download/'):
                    from .delivery_package import archive_delivery
                    result=archive_delivery(_row(ledger,key)['path']);self.respond(Path(result['download_path']),content_type='application/zip',attachment=True)
                elif route.path.startswith('/image/'):
                    view=evidence(ledger,key);sha=parse_qs(route.query).get('sha',[''])[0]
                    allowed={r.get('candidate_sha256'):r.get('local_path') for r in view['rows']}
                    allowed.update({r.get('source_sha256'):r.get('raw_path') for r in view['sources']})
                    allowed.update({ref.get('sha256'):ref.get('path') for row in view['rows'] for ref in row.get('reference_images',[])})
                    image=resolve_job_owned_path(_row(ledger,key)['path'],allowed[sha])
                    if file_sha256(image)!=sha:raise ValueError('Image changed; refresh source evidence')
                    self.respond(image,content_type='image/png' if image.suffix.lower()=='.png' else 'image/jpeg')
                else:self.respond({'error':'Not found'},status=404)
            except Exception as exc:self.respond({'error':str(exc)},status=409)
        def do_POST(self):
            try:
                self.host()
                origin=f'http://127.0.0.1:{self.server.server_port}'
                if self.headers.get('Origin')!=origin or self.headers.get('X-Factory-Token')!=token:raise ValueError('Action origin/token mismatch')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=262144:raise ValueError('Invalid action size')
                body=json.loads(self.rfile.read(length))
                if self.path=='/api/action':
                    result=apply_action(ledger,body);self.respond(result,status=409 if result.get('status')=='rejected' else 200)
                elif self.path=='/api/order':
                    from .production_batch import create_batch
                    spec=body['spec']
                    if 'business_input' in body:
                        target=ledger.path.parent/'inputs'/(identity(body['business_input'])+'.json');write_json(target,body['business_input'])
                        spec={**spec,'business_input_path':str(target)}
                    enrolled=create_batch(ledger.path,{'policy':ledger.settings()['policy'],'group_id':body.get('group_id','console'),'jobs':[spec]})
                    self.respond({'status':'enrollment_result','items':enrolled.enrollment_results,'requests_sent':0})
                else:self.respond({'error':'Not found'},status=404)
            except Exception as exc:self.respond({'error':str(exc)},status=409)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def serve(path, *, port=8766,dispatch=False):
    import threading
    server=make_server(path,port=port);stop=threading.Event();worker=None
    if dispatch:
        from .production_batch import run_batch
        worker=threading.Thread(target=run_batch,args=(path,),kwargs={'stop_event':stop},daemon=False);worker.start()
    print(f'Workspace console: http://127.0.0.1:{server.server_port}; dispatcher={dispatch}',flush=True)
    try:server.serve_forever()
    finally:
        server.server_close();stop.set()
        if worker:worker.join()

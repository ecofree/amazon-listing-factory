"""Durable single-request storage for existing fetch/copy/OCR owners; no retries or scheduler."""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime,timezone,timedelta
import hashlib,json,os,socket,threading,uuid
from typing import Callable
import psutil
from .io import read_json,write_json,write_bytes_atomic,file_sha256
from .process_lock import process_file_lock

SCHEMA='service-response-v1'
_LOCKS={}
_LOCKS_GUARD=threading.Lock()
_REQUEST_ADMISSION = ContextVar('service_request_admission', default=None)


def current_request_admission():
    """The currently owned physical request; not a second receipt or scheduler."""
    return _REQUEST_ADMISSION.get()


class ServiceOutcomeUnknown(RuntimeError):
    pass


class RequestNotSent(RuntimeError):
    """An owned transport checkpoint, not a guess from error text or token usage."""
    def __init__(self, request_id, stage, error):
        super().__init__(f'{stage}: {type(error).__name__}: {error}')
        self.request_id,self.stage=request_id,stage


@contextmanager
def prepare_request():
    """Only local preparation belongs here; transports mark entry before HTTP."""
    try:yield
    except Exception as exc:
        context=current_request_admission()
        if isinstance(exc,RequestNotSent):raise
        if context and not context.get('submission_started'):
            raise RequestNotSent(context['id'],'local_preparation',exc) from exc
        raise


def start_submission():
    """Persist a conservative call boundary before entering the HTTP library."""
    context=current_request_admission()
    if context is None:return None
    token={'request_id':context['id'],'previous_submission':context['submission_started'],
           'sequence':context.get('submission_sequence',0)+1}
    with prepare_request():
        observer=context.get('submission_observer')
        if observer:observer()
    context.update(submission_started=True,submission_sequence=token['sequence'])
    return token


def connection_not_sent(token, error):
    """Called only on an actual connect-failed trace with no headers-started event."""
    context=current_request_admission()
    if (context and token and token['request_id']==context['id'] and not token['previous_submission']
            and token['sequence']==context.get('submission_sequence')):
        context['submission_started']=False
        return RequestNotSent(context['id'],'connect_failed_before_headers',error)
    return error


def _bound_unsent(error):
    context=current_request_admission();seen=set()
    if not context or context.get('submission_started'):return False
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,RequestNotSent) and error.request_id==context['id']:return True
        error=getattr(error,'__cause__',None)
    return False


@contextmanager
def request_admission_scope(receipt_path, request_id=None, *, submission_observer=None):
    """Bind transport admission to its existing service or planning authority."""
    from .batch_ledger import AdmissionDenied
    if current_request_admission() is not None:
        raise AdmissionDenied('Nested physical request scopes cannot create new spending permission')
    path=str(Path(receipt_path).resolve())
    token=_REQUEST_ADMISSION.set({'id':path if request_id is None else path+'#'+str(request_id),
                                 'receipt_path':path,'admitted':False,'submission_started':False,
                                 'submission_observer':submission_observer})
    try:yield
    finally:_REQUEST_ADMISSION.reset(token)


@contextmanager
def _locked(root):
    root.mkdir(parents=True,exist_ok=True)
    with _LOCKS_GUARD:lock=_LOCKS.setdefault(os.path.normcase(str(root)),threading.RLock())
    with lock,process_file_lock(root/'.requests.lock'):yield


def _records(root,verify_owners, *, recover=True):
    rows=[]
    for path in root.glob('*.json'):
        row=read_json(path)
        if (row.get('schema')!=SCHEMA or row.get('id')!=path.stem or not isinstance(row.get('owners'),list)
                or not row['owners'] or row.get('status') not in {'submitted','unknown','received','known_failure','retry_authorized'}):
            raise ValueError(f'Invalid service receipt: {path}')
        body=path.with_suffix('.response')
        relevant=bool(set(row['owners']) & set(verify_owners))
        if relevant and row.get('response_sha256') and (not body.is_file() or file_sha256(body)!=row['response_sha256']):
            raise ServiceOutcomeUnknown(f'Saved service response changed; no replacement authorized: {path}')
        # A receipt is created before budget admission and before the transport
        # checkpoint. If its owner process died while it still says "preparation",
        # no HTTP call was entered; safely return this exact owner to retryable.
        if (recover and relevant and row['status']=='submitted' and not body.is_file()
                and row.get('submission_stage')=='preparation'
                and isinstance(row.get('pid'),int) and row.get('process_start') is not None
                and not _alive(row)):
            row.update(status='known_failure',known_not_executed=True,
                       submission_stage='not_sent',error_type='WorkerInterruptedBeforeSubmission')
            write_json(path,row)
        if recover and relevant and row['status'] in {'submitted','unknown'} and body.is_file():
            if body.stat().st_size>16*1024*1024:raise ValueError(f'Saved service response exceeds limit: {path}')
            row.update(status='received',response_sha256=file_sha256(body),response_bytes=body.stat().st_size)
            write_json(path,row)
        rows.append((path,row))
    consumed={r.get('replaces') for _,r in rows if r.get('replaces') and not r.get('known_not_executed')}
    return sorted(rows,key=lambda p:int(p[1]['sequence'])),consumed


def _alive(row):
    try:return psutil.Process(row['pid']).create_time()==row['process_start']
    except (psutil.Error,KeyError):return False


def known_unsent(error):
    """Only transport proof of no send, not an arbitrary timeout or HTTP 5xx."""
    import requests
    from .batch_ledger import AdmissionDenied
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,(socket.gaierror,requests.ConnectTimeout,AdmissionDenied)):return True
        error=getattr(error,'reason',None) if isinstance(getattr(error,'reason',None),BaseException) else error.__cause__
    return False


def _authorization_current(row):
    grant=row.get('resolution') or {}
    try:
        expires=datetime.fromisoformat(grant['expires_at'])
        return bool(grant.get('authorization_id') and grant.get('binding')=={'id':row['id'],'key':row['key'],'owners':row['owners']}
                    and expires.tzinfo is not None and expires>datetime.now(timezone.utc))
    except (KeyError,TypeError,ValueError):return False


def retry_authorized(root: Path, owners: list[str], *, include_known_unsent: bool = False) -> bool:
    """Original unissued work or one valid grant; never spending admission.
    perform_request alone reserves/replaces, and transport still enforces the ledger.
    """
    owners = sorted(set(owners))
    # Reconcile only provably orphaned pre-submission receipts before deciding
    # whether this logical owner has safe retry permission.
    rows, consumed = _records(Path(root), owners, recover=True)
    relevant = [row for _, row in rows if row['id'] not in consumed and set(row['owners']) & set(owners)]
    if any(row['status'] in {'submitted','unknown'} for row in relevant):return False
    grants = [row for row in relevant if row['status']=='retry_authorized']
    if len(grants)==1 and grants[0]['owners']==owners and _authorization_current(grants[0]):return True
    return include_known_unsent and bool(relevant) and all(row['status']=='known_failure' and row.get('known_not_executed') is True for row in relevant)


def perform_request(root: Path,owners:list[str],identity:dict,send:Callable[[],bytes],*,
                    known_not_executed:Callable[[Exception],bool]=known_unsent,
                    retry_received:bool=False,max_bytes:int=16*1024*1024,receipt_observer=None)->bytes:
    """Reserve once before sending; interrupted/unknown attempts cannot be implicitly reclaimed."""
    root=Path(root).resolve();owners=sorted(set(str(v) for v in owners if str(v)))
    if not owners:raise ValueError('Service request needs stable logical owners')
    key=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()
    with _locked(root):
        rows,consumed=_records(root,owners)
        relevant=[(p,r) for p,r in rows if set(r['owners']) & set(owners) and r['id'] not in consumed]
        pending=[(p,r) for p,r in relevant if r['status'] in {'submitted','unknown'}]
        if pending:raise ServiceOutcomeUnknown(f'Original service request is pending/unknown; recover or explicitly resolve it, no new POST: {pending[0][0]}')
        grants=[(p,r) for p,r in relevant if r['status']=='retry_authorized']
        if len(grants)>1 or any(r['owners']!=owners or not _authorization_current(r) for _,r in grants):
            raise ServiceOutcomeUnknown('Retry authorization does not match the exact logical-owner set')
        received=[(p,r) for p,r in rows if r['key']==key and r['owners']==owners and r['status']=='received']
        if received and not retry_received and not grants:
            path,row=received[-1];body=path.with_suffix('.response')
            if not body.is_file() or body.stat().st_size>max_bytes or file_sha256(body)!=row['response_sha256']:
                raise ServiceOutcomeUnknown(f'Saved service result is missing/changed; reconcile without another POST: {path}')
            if receipt_observer:receipt_observer({'receipt':str(path),'submitted_at':row['submitted_at'],'reused':True})
            return body.read_bytes()
        sequence=max([0,*[r['sequence'] for _,r in rows]])+1
        identity_id=f'{sequence:06d}-{uuid.uuid4().hex}';path=root/(identity_id+'.json');process=psutil.Process()
        row={'schema':SCHEMA,'id':identity_id,'sequence':sequence,'key':key,'owners':owners,'status':'submitted',
             'pid':os.getpid(),'process_start':process.create_time(),'submitted_at':datetime.now(timezone.utc).isoformat(),
             'replaces':grants[0][1]['id'] if grants else '', 'operation':str(identity.get('operation') or ''),
             'submission_stage':'preparation'}
        write_json(path,row)
    response_received=False
    def submitting():
        row.update(submission_stage='submission_call_started',budget_admitted=current_request_admission()['admitted'])
        with _locked(root):write_json(path,row)
    with request_admission_scope(path,submission_observer=submitting):
        try:
            data=send()
            response_received=True
            row['submission_stage']='result_returned'
            if not isinstance(data,bytes) or len(data)>max_bytes:raise ValueError('Service response exceeds the bounded byte contract')
            write_bytes_atomic(path.with_suffix('.response'),data)
            with _locked(root):write_json(path,{**row,'status':'received','response_sha256':hashlib.sha256(data).hexdigest(),'response_bytes':len(data)})
            if receipt_observer:receipt_observer({'receipt':str(path),'submitted_at':row['submitted_at'],'reused':False})
            return data
        except Exception as exc:
            # A fully written response remains recoverable even if metadata settlement failed.
            body=path.with_suffix('.response')
            if body.is_file():raise ServiceOutcomeUnknown(f'Service response bytes saved; local reconciliation required: {path}') from exc
            # A paid reservation is not proof of HTTP submission. Only a bound
            # checkpoint can override it; any earlier submission stays unknown.
            safe=not response_received and (_bound_unsent(exc) or
                (not current_request_admission()['admitted'] and not current_request_admission()['submission_started'] and known_not_executed(exc)))
            with _locked(root):write_json(path,{**row,'status':'known_failure' if safe else 'unknown','known_not_executed':safe,
                'submission_stage':'not_sent' if safe else row['submission_stage'],
                'budget_admitted':current_request_admission()['admitted'],
                'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None) or getattr(getattr(exc,'response',None),'status_code',None)})
            if safe:raise
            raise ServiceOutcomeUnknown(f'Service POST outcome unknown; no automatic resend: {path}') from exc


def resolve_service_response(receipt:Path,*,action:str,reason:str)->dict:
    """An explicit maintenance action; no HTTP call and no candidate/QA authority."""
    path=Path(receipt).resolve();root=path.parent
    if path.suffix!='.json' or action not in {'confirmed_not_executed','approve_one_retry','approve_received_retry','recover_saved_response'} or not reason.strip():
        raise ValueError('Service resolution requires a receipt, explicit action and evidence/reason')
    with _locked(root):
        requested=read_json(path)
        rows,consumed=_records(root,requested.get('owners') or []);row=next((r for p,r in rows if p==path),None)
        if not row or row['id'] in consumed:raise ValueError('Service receipt is missing or its retry authorization was consumed')
        body=path.with_suffix('.response')
        if row['status']=='retry_authorized':
            if row.get('resolution',{}).get('action')!=action:raise ValueError('Existing authorization has another purpose')
            if _authorization_current(row):
                return {'receipt':str(path),'status':row['status'],'owners':row['owners'],'requests_sent':0}
            row.setdefault('resolution_history',[]).append(row['resolution'])
            row['status']='received' if body.is_file() else 'unknown'
        if action in {'approve_one_retry','approve_received_retry'}:
            chain=set();cursor=row
            while cursor.get('replaces'):
                old=next((r for _,r in rows if r['id']==cursor['replaces']),None)
                if old is None or old['id'] in chain:raise ValueError('Service replacement chain is invalid')
                chain.add(old['id']);cursor=old
            if len(chain)>=3:raise ValueError('Service replacement chain limit (3) reached')
        if body.is_file():
            if action not in {'recover_saved_response','approve_received_retry'}:raise ValueError('Saved service bytes must be recovered locally; a new known-result attempt needs approve_received_retry')
            if row.get('response_sha256') and file_sha256(body)!=row['response_sha256']:raise ValueError('Saved service bytes changed')
            if body.stat().st_size>16*1024*1024:raise ValueError('Saved service response exceeds byte limit')
            row.update(status='retry_authorized' if action=='approve_received_retry' else 'received',response_sha256=file_sha256(body),response_bytes=body.stat().st_size)
        else:
            if action in {'recover_saved_response','approve_received_retry'}:raise ValueError('No saved service response to recover/inspect')
            if row['status'] not in {'unknown','submitted'} or (row['status']=='submitted' and _alive(row)):
                raise ValueError('Only a failed/unknown or orphaned submitted service request can be resolved')
            row['status']='retry_authorized' if action=='approve_one_retry' else 'known_failure'
        row['resolution']={'action':action,'reason':reason.strip(),'at':datetime.now(timezone.utc).isoformat(),
                           'duplicate_operation_risk_accepted':action in {'approve_one_retry','approve_received_retry'}}
        if row['status']=='retry_authorized':
            row['resolution'].update(authorization_id=uuid.uuid4().hex,
                binding={'id':row['id'],'key':row['key'],'owners':row['owners']},
                expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                budget_scope='one_replacement_within_existing_order_limits')
        write_json(path,row)
        return {'receipt':str(path),'status':row['status'],'owners':row['owners'],'requests_sent':0}

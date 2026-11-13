from __future__ import annotations
import hashlib,json,multiprocessing,os,queue,time
from pathlib import Path
from typing import Any
from . import model_router
from .api_registry import (dedupe_image_provider_names,image_provider_entries,image_provider_physical_identity,
    image_provider_resource_group,image_provider_fallback_only)
from .image_provider_common import (ImageGenerationError,CandidateCommitError,ImageOutputRejected,ReceiptDispositionRequired,
    ProviderConfigurationError,ProviderContentError,ProviderQueueUnavailable,ProviderTransportError,
    assert_imagegen_prompt_contract,is_transient_imagegen_error,normalize_provider_error,provider_attempts,
    provider_concurrency_limit,provider_concurrency_slot,provider_failure_class,provider_failure_code,
    provider_failure_status,provider_retry_delay_seconds,provider_timeout_seconds)
from .image_provider_transport import generate_with_registry_image_provider,has_registry_image_provider
from .image_role_utils import role_key
from .io import read_json
from .image_response import begin_response,submit_response,save_response,save_transport_response,finish_response,reject_response_output
from .model_call_health import (model_provider_cooldown_active,model_health_scores,open_provider_run_circuit,
    provider_run_circuit_open,admit_provider_probe,image_gateway_attempt,record_model_call_event,record_provider_run_result)
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin
from .provider_policy import filter_not_forbidden_providers,load_provider_policy
from .batch_ledger import AdmissionDenied


def provider_order(plugin):
    return dedupe_image_provider_names(filter_not_forbidden_providers(model_router.provider_names_for_scope('image_generation'),
        plugin.merged_config(),global_policy=load_provider_policy()))


def apply_role_provider_policy(task,plugin):
    registry={entry.name:entry for entry in image_provider_entries()}
    role=role_key(str(task.get('role') or task.get('role_family') or ''))
    ordered=[name for name in provider_order(plugin) if name in registry and role in registry[name].raw.get('allowed_roles',[])]
    task['category_id']=plugin.category_id
    task['providers']=[name for name in ordered if not _global_provider_cooldown_active(name)
                       and not provider_run_circuit_open(provider_runtime_circuit_key(name))]
    return task


def _global_provider_cooldown_active(provider):
    return model_provider_cooldown_active(scope='image_generation',provider=provider,
        model=str(image_provider_physical_identity(provider).get('model') or provider),
        configuration_revision=_provider_configuration_revision(provider))


def assign_provider_pool(tasks):
    result,assigned_load=[],{}
    for task in tasks:
        ordered=_order_by_health(task,list(task.get('providers') or []))
        normal=[name for name in ordered if not image_provider_fallback_only(name)]
        backups=[name for name in ordered if image_provider_fallback_only(name)]
        choices=backups if task.get('request_outcome')=='unknown' else normal or backups
        primary=min(choices,key=lambda name:(assigned_load.get(image_provider_resource_group(name),0)/max(1,provider_concurrency_limit(name)),choices.index(name)),default='')
        if primary:
            group=image_provider_resource_group(primary);assigned_load[group]=assigned_load.get(group,0)+1
        backup=next((name for name in backups if name!=primary),'');eligible=[n for n in (primary,backup) if n]
        result.append({**task,'providers':eligible,'child_provider_reserve':[n for n in ordered if n not in eligible],
            'child_provider_primary':primary,'child_provider_backup':backup,
            'child_provider_lane':str(task.get('child_provider_lane_key') or task.get('child') or 'default'),
            'child_provider_role_lane':'infographic' if role_key(task.get('role','')) in {'func','size'} else 'photo'})
    return result


def generate_with_provider_retries(*,provider_name,image_input_paths,prompt,region_map_bytes=None,attempt_observer=None,
        total_timeout_seconds=None,request_id='',request_audit=None,response_directory=None):
    """Existing bounded transport attempts; an unknown or a local spending denial stops."""
    circuit=provider_runtime_circuit_key(provider_name)
    if provider_run_circuit_open(circuit):raise ProviderConfigurationError(provider_name,'Provider circuit is open for this run')
    try:total=float(total_timeout_seconds if total_timeout_seconds is not None else os.environ.get('AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS') or '480')
    except ValueError:total=480.0
    run_deadline=time.monotonic()+max(0.0,total)
    if total<=1:raise ImageGenerationError('Image request budget exhausted before provider admission')
    last=None
    for attempt in range(1,provider_attempts(provider_name)+1):
        attempt_started_at=None
        try:
            remaining=run_deadline-time.monotonic()
            if remaining<=1:raise ProviderTransportError(provider_name,'Role provider deadline exhausted',status='timeout_failure')
            queue_budget=max(1.0,min(5.0,remaining-30.0));queued_at=time.monotonic()
            with provider_concurrency_slot(provider_name,deadline=time.monotonic()+queue_budget):
                if request_audit is not None:request_audit['provider_queue_seconds']=round(time.monotonic()-queued_at,3)
                if not admit_provider_probe(circuit):raise ProviderConfigurationError(provider_name,'Provider circuit opened while this task waited for a concurrency slot')
                request_remaining=run_deadline-time.monotonic()
                if request_remaining<29:raise ProviderQueueUnavailable(provider_name,'Execution window exhausted after queue wait; no request sent')
                attempt_timeout=min(float(provider_timeout_seconds(provider_name)),request_remaining)
                with image_gateway_attempt(str(image_provider_physical_identity(provider_name).get('url') or '')) as domain:
                    if request_audit is not None and domain:request_audit['gateway_failure_domain']=domain
                    attempt_started_at=time.monotonic()
                    if attempt_observer:attempt_observer(provider_name,attempt,status='started')
                    data=_generate_with_provider_deadline(provider_name=provider_name,image_input_paths=image_input_paths,
                        prompt=prompt,region_map_bytes=region_map_bytes,timeout_seconds=attempt_timeout,
                        request_id=request_id,request_audit=request_audit,response_directory=response_directory)
                if request_audit is not None:request_audit['provider_execution_seconds']=round(time.monotonic()-(attempt_started_at or queued_at),3)
            if attempt_observer:attempt_observer(provider_name,attempt,status='success',duration_seconds=max(0.0,time.monotonic()-attempt_started_at))
            record_provider_run_result(circuit,'success');return data
        except Exception as exc:
            if isinstance(exc,AdmissionDenied):raise
            error=normalize_provider_error(provider_name,exc);last=error
            if attempt_observer and attempt_started_at is not None:
                attempt_observer(provider_name,attempt,status=provider_failure_status(error),
                    duration_seconds=max(0.0,time.monotonic()-attempt_started_at),error=f'{type(error).__name__}: {error}',failure_class=provider_failure_class(error))
            if isinstance(error,ProviderQueueUnavailable):raise error from exc if error is not exc else error
            circuit_opened=False if getattr(error,'ambiguous',False) else record_provider_run_result(circuit,provider_failure_status(error),threshold=2)
            if isinstance(error,ProviderConfigurationError):open_provider_run_circuit(circuit)
            if getattr(error,'ambiguous',False) or circuit_opened or attempt>=provider_attempts(provider_name) or not is_transient_imagegen_error(error):
                raise error from exc if error is not exc else error
            delay=provider_retry_delay_seconds(provider_name,attempt)
            if time.monotonic()+delay>=run_deadline:break
            time.sleep(delay)
    assert last is not None
    raise last


def _generate_with_provider_deadline(*,provider_name,image_input_paths,prompt,region_map_bytes=None,timeout_seconds=None,
        request_id='',request_audit=None,response_directory=None):
    assert_imagegen_prompt_contract(prompt,provider_name)
    if not has_registry_image_provider(provider_name):raise ProviderConfigurationError(provider_name,f'Unsupported registry image provider: {provider_name}')
    timeout=max(1.0,float(timeout_seconds or provider_timeout_seconds(provider_name)))
    context=multiprocessing.get_context('spawn');result_queue=context.Queue(maxsize=1)
    if response_directory is None or not request_audit or not request_audit.get('response_binding'):
        raise CandidateCommitError('Durable response binding is required before sending')
    receipt=begin_response(response_directory,provider=provider_name,audit=request_audit);result_path=receipt.with_suffix('.bin')
    process=context.Process(target=_provider_worker,args=(provider_name,image_input_paths,prompt,region_map_bytes,request_id,str(receipt),result_queue),daemon=True)
    deadline=time.monotonic()+timeout
    try:
        process.start()
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise ProviderTransportError(provider_name,f'Provider result unknown after its {timeout:.0f}-second attempt deadline; request_id={request_id}',status='timeout_failure',ambiguous=True)
            try:result=result_queue.get(timeout=min(0.25,remaining))
            except queue.Empty:
                if process.is_alive():continue
                try:result=result_queue.get_nowait()
                except queue.Empty as exc:raise ProviderTransportError(provider_name,f'Provider subprocess exited without a result (exit_code={process.exitcode})',ambiguous=True) from exc
            if result.get('event')=='request_prepared':
                if request_audit is not None:request_audit.update(result.get('request_audit') or {})
                continue
            break
        if result.get('ok') is True:
            if not result_path.is_file():raise ProviderTransportError(provider_name,'Provider subprocess returned no result file')
            if request_audit is not None:request_audit.update(result.get('request_audit') or {})
            return receipt
        if request_audit is not None:request_audit.update(result.get('request_audit') or {})
        code=str(result.get('failure_code') or '');message=str(result.get('message') or 'Provider subprocess failed')
        if code=='budget_denied':raise AdmissionDenied(message,result.get('admission_reason_code') or 'admission_denied')
        if result.get('local_failure'):raise CandidateCommitError(message)
        if code=='local_contract_mismatch':raise ProviderConfigurationError(provider_name,message)
        if code=='provider_transport_failure':raise ProviderTransportError(provider_name,message,status=str(result.get('status') or 'transport_failure'),ambiguous=bool(result.get('ambiguous')))
        raise ProviderContentError(provider_name,message)
    except Exception as exc:
        _stop_provider_process(process);record=read_json(receipt)
        if record.get('status')=='output_rejected':raise ReceiptDispositionRequired(f"Generated output rejected without automatic resend: {record.get('output_rejection')}") from exc
        if record.get('status')=='received' or record.get('body_sha256'):
            if request_audit is not None:request_audit.update(record.get('request_audit') or {})
            return receipt
        if not process.is_alive() and record.get('status')=='prepared':
            finish_response(receipt,'known_failure')
            raise ProviderTransportError(provider_name,f'Worker failed before transport submission: {exc}') from exc
        if record.get('status')=='submitted' and not getattr(exc,'ambiguous',False):
            raise ProviderTransportError(provider_name,f'Submitted request has no confirmed result: {exc}',ambiguous=True) from exc
        raise
    finally:
        _stop_provider_process(process);result_queue.cancel_join_thread();result_queue.close()


def _stop_provider_process(process):
    if process.is_alive():process.terminate();process.join(timeout=2)
    if process.is_alive() and hasattr(process,'kill'):process.kill();process.join(timeout=1)


def _provider_worker(provider,image_input_paths,prompt,region_map,request_id,receipt_path,output):
    receipt=Path(receipt_path);record=read_json(receipt)
    audit={**record['request_audit'],'attempt_id':receipt.stem,'receipt_path':str(receipt)}
    remote_complete=False;transport_started=False
    try:
        images=[Path(path).read_bytes() for path in image_input_paths]
        def prepared(snapshot):
            nonlocal transport_started
            transport_started=True;submit_response(receipt,snapshot);output.put({'event':'request_prepared','request_audit':snapshot})
        data=generate_with_registry_image_provider(provider_name=provider,image_inputs=images,prompt=prompt,
            region_map_bytes=region_map,request_id=request_id,request_audit=audit,request_observer=prepared,
            transport_observer=lambda phase,data,snapshot:save_transport_response(receipt,phase,data,snapshot))
        remote_complete=True;save_response(receipt,data,audit);output.put({'ok':True,'request_audit':audit})
    except Exception as exc:
        has_body=any(receipt.with_suffix(suffix).is_file() for suffix in ('.http','.bin'))
        if isinstance(exc,ImageOutputRejected):reject_response_output(receipt,str(exc))
        elif not remote_complete and not has_body and not getattr(exc,'ambiguous',False):finish_response(receipt,'known_failure')
        output.put({'ok':False,'failure_code':provider_failure_code(exc),'status':provider_failure_status(exc),
            'message':f'{type(exc).__name__}: {exc}','ambiguous':bool(getattr(exc,'ambiguous',False)),
            'admission_reason_code':getattr(exc,'reason_code',''),
            'request_audit':audit,'local_failure':remote_complete or has_body or not transport_started or isinstance(exc,(MemoryError,CandidateCommitError))})


def record_provider_transport_attempt_event(*,output_path,provider,task,attempt,status,duration_seconds=None,error='',failure_class=''):
    job=Path(str(task['job_dir'])).resolve()
    if resolve_job_owned_path(job,output_path)!=resolve_job_owned_path(job,task['output_path']):raise ValueError('Provider event output does not match current task')
    # Sole persisted health authority. Selection/finalization are progress, not extra model calls.
    record_model_call_event(scope='image_generation',provider=provider,
        model=str(image_provider_physical_identity(provider).get('model') or provider),status=status,protocol='images_edit',
        error=error,configuration_revision=_provider_configuration_revision(provider),
        attempt_id=f"{job}:{task.get('logical_task_id')}:{task.get('candidate_revision',0)}:{attempt}")


def _order_by_health(task,providers):
    scores=_provider_scores(task,providers);order={name:i for i,name in enumerate(providers)}
    role=role_key(str(task.get('role') or ''))
    preferences={entry.name:(entry.raw.get('role_priority') or {}).get(role,0) for entry in image_provider_entries()}
    return sorted(providers,key=lambda name:(scores[name]<0,-preferences.get(name,0),-scores[name],order[name]))


def _provider_scores(task,providers):
    return model_health_scores(scope='image_generation',providers={name:(str(image_provider_physical_identity(name).get('model') or name),
        _provider_configuration_revision(name)) for name in providers})


def _provider_configuration_revision(provider):
    entry=next((r for r in image_provider_entries() if r.name==provider),None)
    credentials='\0'.join((str(entry.api_key or ''),str(entry.bearer_token or ''))) if entry else ''
    material={'request_budget_policy':'provider-window-v2','physical_identity':image_provider_physical_identity(provider),
              'credential_revision':hashlib.sha256(credentials.encode()).hexdigest()}
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def provider_runtime_circuit_key(provider):
    return f'image_generation:{_provider_configuration_revision(provider)}'

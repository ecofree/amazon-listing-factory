"""Explicitly budgeted diagnostics using the existing service/image receipt owners."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from . import api_registry, vision_gemini_client as vision_client
from .batch_ledger import BatchLedger, AdmissionDenied, admit_paid_request
from .io import read_json
from .provider_smoke_store import registry_fingerprint
from .service_response import perform_request
from .status import input_revision_id


class ProviderSmokeError(RuntimeError):
    pass


def _diagnostic_context():
    database, key, lease = (os.environ.get(k) for k in ('FACTORY_BATCH_DB','FACTORY_BATCH_JOB','FACTORY_BATCH_LEASE'))
    if not database or not key or not lease:
        raise AdmissionDenied('Live diagnostics require an explicit enrolled diagnostic budget; no request sent')
    row=BatchLedger(database).worker(key,lease)
    if json.loads(row['spec']).get('purpose') != 'provider_diagnostic':
        raise AdmissionDenied('A production lease is not permission for paid provider diagnostics')
    return Path(row['path']).resolve(), time.monotonic()+max(0,row['lease_until']-time.time())


def _result(name, scope, steps):
    status = 'failed' if any(s['status']=='failed' for s in steps) else 'cached' if any(s.get('reused') for s in steps) else 'passed'
    stamps=[s['submitted_at'] for s in steps if s.get('submitted_at')]
    return {'provider':name,'scope':scope,'status':status,'steps':steps,
        'checked_at':min(stamps) if stamps else None,'reported_at':datetime.now(timezone.utc).isoformat(),
        'acceptance_scope':'diagnostic_transport_only_not_listing_quality'}


def smoke_model_provider(client: dict[str, Any], *, scope: str) -> dict[str, Any]:
    steps=[]
    operations=[('text',_run_text_step)]
    if _has_capability(client,'vision_input'):operations.append(('image',_run_image_step))
    for name, operation in operations:
        try:
            receipt=operation(client,scope=scope)
            steps.append({'step':name,'status':'passed',**receipt})
        except Exception as exc:
            steps.append({'step':name,'status':'failed','error':f'{type(exc).__name__}: {exc}'})
            break
    return _result(str(client.get('name') or ''),scope,steps)


def smoke_registry_provider(provider_name: str, *, scope: str = '') -> list[dict[str, Any]]:
    _diagnostic_context()  # Reject before even preparing diagnostic image inputs.
    entries=[e for e in api_registry.load_registry_entries() if e.name==provider_name]
    if not entries:raise ProviderSmokeError('Provider not found in api_registry: '+provider_name)
    results=[]
    for entry in entries:
        for selected in ([scope] if scope else list(entry.scopes)):
            if selected not in entry.scopes:raise ProviderSmokeError('Provider does not declare the requested scope')
            if selected=='image_generation':
                try:steps=[{'step':'configured','status':'passed'},
                           {'step':'image_generation','status':'passed',**_run_image_generation_step(entry)}]
                except Exception as exc:steps=[{'step':'image_generation','status':'failed','error':f'{type(exc).__name__}: {exc}'}]
                result=_result(entry.name,selected,steps)
            else:
                clients=[c for c in api_registry.model_clients_for_scope(selected) if c.get('name')==entry.name]
                if not clients:raise ProviderSmokeError('No usable model client for scope')
                result=smoke_model_provider(clients[0],scope=selected)
            result['registry_fingerprint']=registry_fingerprint(entry.raw)
            results.append(result)
    return results


def _run_text_step(client, *, scope):
    return _post_and_parse(client,_model_payload(client,'Return compact JSON only: {"ok":true}',[]),scope=scope,step='text')


def _run_image_step(client, *, scope):
    with tempfile.TemporaryDirectory() as tmp:
        image=Path(tmp)/'provider_smoke.jpg'
        Image.new('RGB',(32,32),(245,245,245)).save(image,format='JPEG')
        return _post_and_parse(client,_model_payload(client,'Return compact JSON only: {"image_received":true}',[image]),scope=scope,step='image')


def _model_payload(client, prompt, image_paths):
    protocol=str(client.get('protocol') or '').lower();model=str(client.get('model') or '')
    if vision_client._is_openai_responses_protocol(protocol):return vision_client._openai_responses_payload(model,prompt,image_paths,client)
    if vision_client._is_openai_chat_protocol(protocol):return vision_client._openai_chat_payload(model,prompt,image_paths,client)
    if protocol in {'gemini','google_gemini','native_gemini'}:
        return vision_client._gemini_native_payload([{'text':prompt},*[vision_client._image_part(p) for p in image_paths]],client)
    raise ProviderSmokeError('Unsupported diagnostic protocol: '+protocol)


def _post_and_parse(client, payload, *, scope, step):
    root,deadline=_diagnostic_context()
    if scope not in {'visual_planning','vision_qa'}:raise ProviderSmokeError('Unsupported diagnostic scope')
    protocol=str(client.get('protocol') or '').lower();base=str(client.get('base_url') or '')
    headers=vision_client._openai_chat_headers(str(client.get('api_key') or ''),
        auth_mode=str(client.get('openai_auth_mode') or 'bearer'),bearer_token=client.get('bearer_token'))
    if vision_client._is_openai_responses_protocol(protocol):
        url=vision_client._openai_responses_url(base);parser=vision_client._parse_openai_responses_candidates
    elif vision_client._is_openai_chat_protocol(protocol):
        url=vision_client._openai_chat_completions_url(base);parser=vision_client._parse_openai_chat_candidates
    else:
        endpoint=vision_client._gemini_native_endpoint_url(base,str(client.get('model') or ''),'generateContent')
        mode=vision_client._normalize_gemini_auth_mode(str(client.get('auth_mode') or '')) or vision_client._gemini_auth_modes(base)[0]
        url,headers=vision_client._gemini_request_auth(endpoint,str(client.get('api_key') or ''),mode,client.get('bearer_token'))
        parser=vision_client._parse_generate_content_candidates
    identity={'operation':'provider_diagnostic','client':api_registry.model_client_physical_identity(client),'scope':scope,'payload':payload}
    receipt={}
    def send():
        if time.monotonic()>=deadline:raise AdmissionDenied('Diagnostic lease expired before submission')
        admit_paid_request('qa' if scope=='vision_qa' else 'planning')
        return vision_client._post_json_preserve_redirects(url,payload,headers=headers,
            timeout_seconds=min(90,max(1,int(deadline-time.monotonic())))).encode('utf-8')
    raw=perform_request(root/'reports/provider_smoke_requests',[f"smoke:{client.get('name')}:{scope}:{step}"],
        identity,send,receipt_observer=receipt.update)
    candidates=parser(raw.decode('utf-8'))
    if not candidates:raise ProviderSmokeError('Provider returned no parseable text; inspect retained response before another request')
    return receipt


def _run_image_generation_step(entry):
    from .image_prompt_compiler import PROMPT_CONTRACT_VERSION
    from .image_provider_common import provider_concurrency_slot
    from .image_provider_routing import _generate_with_provider_deadline
    from .image_response import response_binding,response_directory,recover_response,materialize_response
    from .imagegen_artifacts import assert_native_image
    from .io import write_bytes_atomic
    root,deadline=_diagnostic_context()
    buffer=io.BytesIO();Image.new('RGB',(32,32),(245,245,245)).save(buffer,format='PNG');pixels=buffer.getvalue()
    prompt=(f'IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}\n[ROLE]\nDiagnostic edit, not a listing product. '
        'Add a small neutral rectangle to the source canvas.\n[REFERENCE]\nEdit the first attachment. '
        '\n[STYLE]\nNeutral plain canvas.\n[TEXT]\nNo authored text, branding or watermark.'
        '\n[OUTPUT]\nReturn one square PNG image only.')
    task={'job_dir':str(root),'logical_task_id':'smoke:'+entry.name+':image','candidate_revision':0,'prompt':prompt,
          'task_fingerprint':input_revision_id({'provider':registry_fingerprint(entry.raw),'pixels':hashlib.sha256(pixels).hexdigest()}),
          'generation_references':[]}
    saved=recover_response(task)
    reused=bool(saved)
    if saved:receipt=Path(saved['receipt_path'])
    else:
        source=root/'reports/provider_smoke_inputs'/f'{task["task_fingerprint"]}.png'
        write_bytes_atomic(source,pixels)
        audit={'response_binding':response_binding(task),'logical_task_id':task['logical_task_id'],
               'request_id':task['task_fingerprint'],'purpose':'provider_diagnostic'}
        with provider_concurrency_slot(entry.name,deadline=deadline):
            remaining=min(90,deadline-time.monotonic())
            if remaining<=1:raise AdmissionDenied('Diagnostic deadline exhausted before image submission')
            receipt=_generate_with_provider_deadline(provider_name=entry.name,image_input_paths=[str(source)],
                prompt=prompt,timeout_seconds=remaining,request_id=task['task_fingerprint'],
                request_audit=audit,response_directory=response_directory(task))
    native=materialize_response(receipt,deadline=deadline)
    assert_native_image(native.read_bytes())
    record=read_json(receipt)
    return {'receipt':str(receipt),'submitted_at':record.get('submitted_at'),'reused':reused}


def _has_capability(client, capability):
    raw=client.get('capabilities')
    if isinstance(raw,str):
        try:raw=json.loads(raw)
        except json.JSONDecodeError:raw=raw.replace(',',' ').split()
    return capability in {str(v).strip().lower().replace('-','_') for v in raw or []}

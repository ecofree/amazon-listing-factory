"""The existing brief owner's durable allowance and operation journal, not a controller."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import uuid
from datetime import datetime,timezone,timedelta
from .io import read_json,write_json,utc_now
from .status import input_revision_id
from .process_lock import process_file_lock

SCHEMA = 'planning-journal-v1'
DEFAULT_LIMITS = {'plan':4,'tool_calls':4}


class PlanningBudgetError(ValueError):
    pass


class PlanningJournal:
    def __init__(self, path: Path, *, child: str, scope_key: str, initialize=True, role_count=None):
        self.path,self.child,self.scope_key=Path(path),child,scope_key
        if role_count is not None and (type(role_count) is not int or role_count<1):raise ValueError('Positive frozen role count required')
        if not initialize:
            if not self.path.is_file():raise PlanningBudgetError('Missing planning allowance; do not initialize over existing work')
            self._validate(read_json(self.path));return
        with process_file_lock(self.path.with_suffix('.lock')):
            if self.path.is_file():
                self._validate(read_json(self.path))
            else:
                if any(self.path.parent.rglob('attempt_budget.json')) or any(self.path.parent.glob('*/request.txt')):
                    raise PlanningBudgetError('Previous planning work exists without this allowance; reconcile explicitly')
                # Byte-bounded requests may contain one complete role. Allow a
                # repair, a region decision and a confirmation per frozen role.
                limits={**DEFAULT_LIMITS,'tool_calls':max(DEFAULT_LIMITS['tool_calls'],3*(role_count or 0))}
                write_json(self.path,dict(schema=SCHEMA,child=child,scope_key=scope_key,limits=limits,
                    carry={k:0 for k in DEFAULT_LIMITS},plan=0,tool_calls=0,roles={},requests={},tool_records=[],grants=[]))

    def _validate(self,value):
        if (not isinstance(value,dict) or value.get('schema')!=SCHEMA or value.get('child')!=self.child
                or value.get('scope_key')!=self.scope_key):
            raise PlanningBudgetError('Planning allowance scope/schema changed; explicit reconciliation required')
        for kind in DEFAULT_LIMITS:
            if type(value.get(kind)) is not int or value[kind]<0 or type(value.get('limits',{}).get(kind)) is not int or value['limits'][kind]<0:
                raise PlanningBudgetError('Invalid planning allowance counters')
        if not all(isinstance(value.get(k),dict) for k in ('roles','requests','carry')) or not isinstance(value.get('tool_records'),list):
            raise PlanningBudgetError('Invalid planning journal')
        restorations=value.get('restorations',{})
        if not isinstance(restorations,dict) or any(not isinstance(r,dict) or r.get('status') not in {'prepared','completed','cancelled'} for r in restorations.values()):
            raise PlanningBudgetError('Invalid local restoration journal')
        for record in restorations.values():
            proof=record.get('proof') or {};request=proof.get('request') or {}
            if (record.get('proposal_sha256')!=input_revision_id(proof) or request.get('child')!=self.child
                    or request.get('role')!=record.get('role') or record.get('request_fingerprint')!=input_revision_id({
                        'request':request,'proposal':record.get('proposal_sha256'),'reason':record.get('reason')})):
                raise PlanningBudgetError('Local restoration proof identity changed')
        for kind in DEFAULT_LIMITS:
            prior=value['carry'].get(kind)
            if type(prior) is not int or prior<0 or value[kind]!=prior+sum(r['count'] for r in value['requests'].values() if r['kind']==kind):
                raise PlanningBudgetError('Planning consumption does not reconcile with physical reservations')
        return value

    def read(self):
        return self._validate(read_json(self.path))

    def save_roles(self,roles,records):
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();incoming=deepcopy(roles)
            for role,slot in incoming.items():
                prior=value['roles'].get(role,{})
                pending=slot.get('pending_action');old=prior.get('pending_action')
                if pending and old and pending['operation_id']==old['operation_id'] and old.get('admitted'):
                    pending['admitted']=True
            if value['roles']==incoming and value['tool_records']==records:return
            for role,prior in value['roles'].items():
                after=incoming.get(role,{})
                if (prior.get('phase')=='ready' and prior.get('origin') and
                        (after.get('phase')!='ready' or after.get('origin')!=prior['origin'] or after.get('draft')!=prior.get('draft'))):
                    history=value.setdefault('design_history',[])
                    if not any((h.get('roles',{}).get(role) or {}).get('origin')==prior['origin']
                               and (h.get('roles',{}).get(role) or {}).get('draft')==prior.get('draft') for h in history):
                        history.append({'context_id':value.get('design_context_id'),'roles':{role:deepcopy(prior)},'at':utc_now()})
            value['roles']=incoming;value['tool_records']=deepcopy(records)
            write_json(self.path,value)

    def reserve_action(self,role,operation_id,*,authorized):
        """Reserve one automatic operation or the exact explicitly adopted proposal."""
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();slot=value['roles'][role];pending=slot['pending_action']
            if pending['operation_id']!=operation_id:raise PlanningBudgetError('Pending operation changed before admission')
            explicit=pending.get('authorization_id')
            if explicit:
                expected={'id':explicit,'role':role,'operation_id':operation_id,'before_content':pending['before_content'],
                    **{k:pending['packet'][k] for k in ('key','response_path','response_sha256')}}
                authorized=any(all(event.get(k)==v for k,v in expected.items()) for event in value.get('operation_authorizations',[]))
            if not authorized:return False
            if pending.get('admitted'):return True
            pending['admitted']=True;write_json(self.path,value);return True

    def adopt_action(self,role,action,*,authorization_id,reason):
        """Queue one explicitly selected saved proposal; send no request or tool call."""
        if not authorization_id or not isinstance(reason,str) or not reason.strip():raise ValueError('Explicit adoption needs ID and reason')
        event={'id':authorization_id,'role':role,'operation_id':action['operation_id'],
            'before_content':action['before_content'],'key':action['packet']['key'],'response_path':action['packet']['response_path'],
            'response_sha256':action['packet']['response_sha256'],'reason':reason}
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();events=value.setdefault('operation_authorizations',[])
            prior=next((r for r in events if r['id']==authorization_id),None)
            if prior:
                if any(prior[k]!=v for k,v in event.items()):raise PlanningBudgetError('Adoption ID reused for another proposal')
                return value
            slot=value['roles'][role]
            if slot['phase']=='ready':raise PlanningBudgetError('Cannot replace an accepted role through adoption')
            pending=slot.get('pending_action')
            if pending and pending['operation_id']!=action['operation_id']:raise PlanningBudgetError('Another pending operation needs disposition first')
            slot.update(phase='pending_execution',pending_action={**deepcopy(action),'authorization_id':authorization_id})
            events.append({**event,'at':utc_now()});write_json(self.path,value);return value

    def bind_design(self,context_id):
        """A received fresh shared plan may replace role drafts, never budgets or history."""
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read()
            if value.get('design_context_id')==context_id:return
            if value['roles']:
                value.setdefault('design_history',[]).append({'context_id':value.get('design_context_id'),
                    'roles':deepcopy(value['roles']),'at':utc_now()})
                value['roles']={role:{'phase':'needs_draft',
                    'protocol_failures':deepcopy(slot.get('protocol_failures',{}))} for role,slot in value['roles'].items()}
            value['design_context_id']=context_id
            write_json(self.path,value)

    @staticmethod
    def restoration_basis(value):
        return input_revision_id({k:v for k,v in value.items() if k!='restorations'})

    def prepare_restoration(self,decision_id,event,*,expected_basis):
        """Record a local intent; no request disposition, counter reset or model approval."""
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();records=value.setdefault('restorations',{})
            if decision_id in records:
                if records[decision_id]['request_fingerprint']!=event['request_fingerprint']:
                    raise PlanningBudgetError('Restoration decision ID reused for another request')
                return records[decision_id]
            if any(r.get('status')=='prepared' for r in records.values()):raise PlanningBudgetError('Another local restoration needs reconciliation')
            if self.restoration_basis(value)!=expected_basis:raise PlanningBudgetError('Planning state changed before restoration')
            records[decision_id]={**deepcopy(event),'status':'prepared','journal_basis':expected_basis,'at':utc_now()}
            write_json(self.path,value);return records[decision_id]

    def finish_restoration(self,decision_id,slot):
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();record=value['restorations'][decision_id]
            if record['status']=='completed':return record
            if self.restoration_basis(value)!=record['journal_basis']:raise PlanningBudgetError('Planning state changed during restoration')
            record['prior_slot']=deepcopy(value['roles'].get(record['role'],{}))
            value['roles'][record['role']]=deepcopy(slot)
            record.update(status='completed',completed_at=utc_now());write_json(self.path,value);return record

    def cancel_restoration(self,decision_id,*,reason):
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();record=value.get('restorations',{}).get(decision_id)
            if not record or record['status']!='prepared':raise PlanningBudgetError('Only a prepared local restoration may be cancelled')
            record.update(status='cancelled',cancellation_reason=reason,cancelled_at=utc_now());write_json(self.path,value)

    def remaining(self,kind):
        value=self.read();return max(0,value['limits'][kind]-value[kind])

    def blocking_requests(self,context=None,*,value=None):
        """Initial/shared plans own the child; tool decisions own only their stated roles."""
        return self.pending_request_ids(self.read() if value is None else value, (context or {}).get('roles') or [])

    @staticmethod
    def pending_request_ids(value,roles=()):
        """The same read-only scope predicate used by admission and diagnostics."""
        selected = set(roles)
        return [key for key,row in value.get('requests',{}).items()
            if row['status'] in {'reserved','submitted','unknown'}
            and (row['kind'] != 'tool_calls' or not selected
                 or not row.get('context',{}).get('roles')
                 or selected.intersection(row['context']['roles']))]

    @staticmethod
    def authorization_issues(value,roles=()):
        selected=set(roles)
        return [key for key,row in value.get('requests',{}).items() if row['status']=='retry_authorized'
            and not row.get('resolution',{}).get('consumed_by')
            and not PlanningJournal._authorization_current(value,key)
            and (row['kind']!='tool_calls' or not selected or not row.get('context',{}).get('roles')
                 or selected.intersection(row['context']['roles']))]

    @staticmethod
    def _authorization_current(value,key):
        row=value['requests'][key];grant=row.get('resolution') or {}
        if row['status']!='retry_authorized':return False
        try:
            expires=datetime.fromisoformat(grant['expires_at'])
            return bool(grant.get('authorization_id') and grant.get('request_id')==key
                and grant.get('scope_key')==value['scope_key'] and not grant.get('consumed_by')
                and expires.tzinfo is not None and expires>datetime.now(timezone.utc))
        except (KeyError,ValueError,TypeError):return False

    def reserve(self,kind,*,request_id=None,context=None,roles=None,records=None):
        if kind not in DEFAULT_LIMITS:raise ValueError('Unknown allowance kind')
        identity=request_id or uuid.uuid4().hex
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read()
            if identity in value['requests']:
                raise PlanningBudgetError('Request already reserved; recover its existing response, never resubmit')
            pending=self.blocking_requests(context,value=value)
            if pending:raise PlanningBudgetError(f'Original planning request is pending/unknown; recover its receipt before a new POST: {pending[0]}')
            selected=set((context or {}).get('roles') or [])
            if self.authorization_issues(value,selected):raise PlanningBudgetError('Old/expired authorization needs explicit reconciliation; no new POST')
            grants=[key for key,row in value['requests'].items() if row['kind']==kind and self._authorization_current(value,key)
                and (kind=='plan' or not selected or selected.intersection(row.get('context',{}).get('roles') or []))]
            if len(grants)>1 or any(set(value['requests'][key].get('context',{}).get('roles') or [])!=selected for key in grants):
                raise PlanningBudgetError('Replacement must match one exact authorized request scope')
            if value[kind]>=value['limits'][kind]:raise PlanningBudgetError(f'{kind} allowance exhausted')
            value[kind]+=1
            if roles is not None:value['roles']=deepcopy(roles)
            if records is not None:value['tool_records']=deepcopy(records)
            value['requests'][identity]=dict(kind=kind,status='reserved',count=1,physical_count=None,
                created_at=utc_now(),context=context or {},replaces=grants)
            write_json(self.path,value)
        return identity

    def physical(self,identity,count):
        if type(count) is not int or count<0:raise ValueError('Invalid physical request count')
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();row=value['requests'][identity]
            count=max(row.get('physical_count') or 0,count)
            for prior in row.get('replaces',[]):
                grant=value['requests'][prior].get('resolution') or {}
                if count and grant.get('consumed_by')!=identity:
                    if not self._authorization_current(value,prior):raise PlanningBudgetError('Authorization expired/consumed before physical submission')
                    grant['consumed_by']=identity
            # Reservation remains charged until an explicitly unsent completion.
            if count>row['count']:
                value[row['kind']]+=count-row['count'];row['count']=count
            row['physical_count']=count
            if count:row['status']='submitted'
            write_json(self.path,value)

    def settle(self,identity,*,known_unsent=False,result_path='',rejected=False,result_sha256=''):
        if rejected and (known_unsent or not result_path):raise PlanningBudgetError('Rejection needs a received, bound response')
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();row=value['requests'][identity]
            if not known_unsent and row['status'] in {'received','rejected','retry_authorized'} and not result_path:return
            if known_unsent:
                if row.get('physical_count') not in (None,0) or row.get('status') in {'received','rejected','submitted'}:
                    raise PlanningBudgetError('A submitted/received request cannot be refunded')
                if row['status']!='not_sent':value[row['kind']]-=row['count'];row['count']=0
                row['status']='not_sent'
            else:
                row['status']='rejected' if rejected else 'received' if result_path else 'unknown'
                if result_path:row['result_path']=result_path
                if result_sha256:row['result_sha256']=result_sha256
            write_json(self.path,value)

    def settle_attempt(self,identity,*,job,trace,known_unsent=False):
        """Keep complete rejected/truncated replies distinct from lost replies; never refund a sent call."""
        from .paths import resolve_job_owned_path
        import hashlib
        if known_unsent:
            self.settle(identity,known_unsent=True);return True
        attempts=resolve_job_owned_path(job,Path(trace)/'attempts.json')
        events=read_json(attempts) if attempts.is_file() else []
        last=events[-1] if events else {}
        transport=last.get('transport') or {}
        complete=transport.get('response_complete',last.get('status') in {'success','validation_failure','json_syntax','output_limit'}) is True
        raw=resolve_job_owned_path(job,attempts.parent/last['raw_response_path']) if last.get('raw_response_path') else None
        if complete and raw and raw.is_file():
            body=raw.read_bytes();text=body.decode('utf-8');digest=hashlib.sha256(body).hexdigest()
            if digest!=last.get('response_body_sha256'):raise PlanningBudgetError('Planning response trace changed')
            import json
            try:
                payload=json.loads(text);error=payload.get('error',payload) if isinstance(payload,dict) else {}
                code=str(error.get('type') or error.get('code') or '') if isinstance(error,dict) else ''
            except ValueError:code=''
            status=transport.get('http_status',200)
            rejected=status==402 and code=='insufficient_balance'
            if rejected or 200<=status<300:
                self.settle(identity,result_path=raw.relative_to(job).as_posix(),rejected=rejected,result_sha256=digest);return True
        # No known outcome may be inferred from diagnostic prose, lack of log rows, or a 5xx body.
        self.settle(identity);return False

    def recover_received_attempts(self,job,*,roles=None):
        for identity,row in self.read()['requests'].items():
            owned=set(row.get('context',{}).get('roles') or [])
            if roles is not None and (not owned or not owned<=set(roles)):continue
            trace=row.get('context',{}).get('trace')
            if trace and row['status'] in {'reserved','submitted','unknown'}:
                self.settle_attempt(identity,job=job,trace=trace)

    def accept_retry_risk(self,identity,*,reason):
        """Explicit operator resolution only; retain spent allowance and the original unknown outcome."""
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Retry-risk acceptance needs an explicit reason')
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();row=value['requests'][identity]
            if row['status']=='retry_authorized':
                old=row.get('resolution') or {}
                if old.get('consumed_by'):raise PlanningBudgetError('Authorization already consumed; resolve the replacement request instead')
                if not old.get('authorization_id'):raise PlanningBudgetError('Old authorization consumption is unbound; explicit reconciliation required')
                if self._authorization_current(value,identity):return row
                row.setdefault('resolution_history',[]).append(old)
            elif row['status']!='unknown':raise PlanningBudgetError('Only an unresolved unknown request can accept duplicate-cost risk')
            chain=[];cursor=row
            while cursor.get('replaces'):
                previous=cursor['replaces'][0]
                if previous in chain:raise PlanningBudgetError('Invalid replacement chain')
                chain.append(previous);cursor=value['requests'][previous]
            if len(chain)>=3:raise PlanningBudgetError('Replacement limit reached')
            row['resolution']={'action':'accept_retry_risk','reason':reason.strip(),'at':utc_now(),
                'authorization_id':uuid.uuid4().hex,'request_id':identity,'scope_key':value['scope_key'],
                'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                'budget_scope':'one_replacement_within_existing_order_limits',
                'original_outcome':'unknown','duplicate_cost_risk_accepted':True}
            row['status']='retry_authorized';write_json(self.path,value);return row

    def semantic_error(self,identity,message):
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read();value['requests'][identity]['semantic_error']=str(message);write_json(self.path,value)

    def grant(self,*,kind,additional,reason,grant_id):
        """Only an explicit operator command may call this; no content revision grants money."""
        if kind not in DEFAULT_LIMITS or type(additional) is not int or additional<=0 or not reason.strip() or not grant_id:
            raise ValueError('A grant needs kind, positive count, explicit ID and reason')
        with process_file_lock(self.path.with_suffix('.lock')):
            value=self.read()
            existing=next((r for r in value['grants'] if r['id']==grant_id),None)
            request={'id':grant_id,'kind':kind,'additional':additional,'reason':reason}
            if existing:
                if any(existing[k]!=v for k,v in request.items()):raise PlanningBudgetError('Grant ID was reused with different authorization')
                return value
            value['limits'][kind]+=additional;value['grants'].append({**request,'at':utc_now()})
            write_json(self.path,value);return value


def journal_path(job,child):
    return Path(job)/'reports/visual_design_kit_traces'/child/'attempt_budget.json'

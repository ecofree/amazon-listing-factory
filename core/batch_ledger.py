"""One workspace transaction domain for orders, leases, decisions and spending.
Stage/receipt authorities remain external; this ledger never declares remote success.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib, json, os, sqlite3, time, uuid
from pathlib import Path

SCHEMA = 3
REVIEW_PREFIX = 'job-evidence-v2:'
COMPLETION_SERVICES={'fetch':{'fetch'},'copy':{'copy'},'classify':{'planning','ocr'},'brief':{'planning'},
                     'generate':{'image'},'qa':{'qa'},'publish':{'storage_put','storage_get'}}

class AdmissionDenied(RuntimeError):
    """No permission to submit; this exception alone never proves an earlier POST unsent."""
    def __init__(self,message,reason_code='admission_denied'):
        super().__init__(message);self.reason_code=reason_code


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def workspace_config():
    from .paths import FACTORY_ROOT
    from .io import read_json
    value=read_json(FACTORY_ROOT/'configs/production_workspace.json')
    if value.get('schema')!='listing-workspace-v1' or value.get('ledger')!='runtime/production.sqlite':
        raise AdmissionDenied('Invalid fixed workspace configuration')
    return value


def initialize_fresh_workspace(*,decision_id,reason,fresh=False):
    """Configure a genuinely new installation; never activate spending or erase history."""
    from .paths import FACTORY_ROOT
    from .io import read_json,write_json
    from .process_lock import process_file_lock
    if fresh is not True or not isinstance(decision_id,str) or not decision_id.strip() or not isinstance(reason,str) or not reason.strip():
        raise ValueError('Explicit fresh-installation declaration, decision ID and reason required')
    root=FACTORY_ROOT.resolve();config_path=root/'configs/production_workspace.json'
    intent=root/'configs/workspace_setup'/identity(decision_id)/'intent.json'
    request={'decision_id':decision_id,'reason':reason,'declaration':'new_installation_no_prior_work'}
    with process_file_lock(root/'configs/.workspace-setup.lock'):
        if intent.is_file():
            record=read_json(intent)
            if record.get('request')!=request:raise ValueError('Workspace setup decision ID reused')
        else:
            if config_path.exists() or (root/'runtime/production.sqlite').exists():
                raise ValueError('Existing financial configuration/ledger is protected; no fresh reset')
            for name in ('jobs','runtime','Fianl_pics','Final_templates'):
                anchor=root/name
                if anchor.exists() and any(p.name!='.gitkeep' for p in anchor.iterdir()):
                    raise ValueError('Existing history anchor prevents a fresh declaration: '+name)
            config={'schema':'listing-workspace-v1','ledger':'runtime/production.sqlite',
                'installation':request}
            record={'schema':'workspace-bootstrap-v1','status':'prepared','request':request,'configuration':config}
            write_json(intent,record)
        expected=record['configuration']
        if not config_path.exists() and (root/'runtime/production.sqlite').exists():
            raise ValueError('A ledger appeared before configuration commit; preserve it for reconciliation')
        if config_path.exists():
            if read_json(config_path)!=expected:raise ValueError('Workspace configuration has unrelated later writes')
        else:write_json(config_path,expected)
        if record['status']!='completed':write_json(intent,{**record,'status':'completed'})
        return {'status':'configured_not_activated','ledger':str(root/'runtime/production.sqlite'),
                'requests_sent':0,'budget_created':False,'decision_id':decision_id}


def workspace_ledger_path():
    from .paths import FACTORY_ROOT
    return (FACTORY_ROOT/workspace_config()['ledger']).resolve()


def order_identity(spec):
    purpose=spec.get('purpose','production')
    if purpose!='production':
        return identity({'purpose':purpose,'diagnostic_id':spec.get('diagnostic_id') or spec.get('seed_asin')})
    return identity({k:str(spec.get(k) or default).strip() for k,default in (
        ('seller_id',''),('marketplace','US'),('seed_asin',''),('listing_intent','standard'))})


def _validate_policy(policy):
    for key,default,minimum in (('max_paid_calls',None,0),('workers',1,1),('job_timeout_seconds',7200,1),
                               ('total_job_seconds',7200,1),('max_attempts',1,1)):
        value=policy.get(key,default)
        if type(value) is not int or value<minimum:raise ValueError(key+' must be an explicit nonnegative/positive integer')
    for key,default,maximum in (('workers',1,8),('job_timeout_seconds',7200,7200),('max_attempts',1,5)):
        if policy.get(key,default)>maximum:raise ValueError(key+' exceeds its supported execution bound')
    cap=policy.get('budget_microunits');prices=policy.get('request_upper_bounds') or {}
    if cap is not None and (type(cap) is not int or cap<0 or not policy.get('currency')):
        raise ValueError('Monetary budget requires integer microunits and a currency')
    if any(type(v) is not int or v<0 for v in prices.values()):raise ValueError('Invalid request cost bound')
    if prices and (not policy.get('currency') or any(not str((policy.get('price_evidence') or {}).get(k) or '').strip() for k in prices)):
        raise ValueError('Cost bounds require currency and explicit service/model/input-limit pricing evidence')
    if cap is not None and not prices:raise ValueError('Monetary bounds require service cost ceilings')
    if cap is None and policy['max_paid_calls'] and policy.get('fee_mode')!='count_only_trial':
        raise ValueError('Unpriced requests require an explicit count_only_trial declaration; not monetary control')


class BatchLedger:
    def __init__(self,path):self.path=Path(path).resolve()

    @contextmanager
    def transaction(self, *, initialize=False, _database=None):
        if _database is not None and not initialize:raise ValueError('Alternate database is only for unpublished schema construction')
        path=self.path if _database is None else Path(_database)
        if not path.is_file():raise FileNotFoundError(f'No initialized workspace ledger: {path}')
        db=sqlite3.connect(path,timeout=10,isolation_level=None);db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
            if not initialize:
                row=db.execute('SELECT schema FROM batch WHERE id=1').fetchone()
                if not row or row[0]!=SCHEMA:raise ValueError('Retired ledger schema; explicit read-only cutover required, never migrate in dispatch')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def create(self, *, policy, source_revision):
        _validate_policy(policy)
        import tempfile
        if self.path.exists():raise FileExistsError('Existing ledger cannot be reinitialized: '+str(self.path))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.'+self.path.name+'.initialize-',suffix='.sqlite',dir=self.path.parent);os.close(fd)
        temporary=Path(name)
        try:
            with self.transaction(initialize=True,_database=temporary) as db:self._create_schema(db,policy,source_revision)
            os.link(temporary,self.path)  # Publish a complete schema without clobbering a competing initializer.
        finally:temporary.unlink(missing_ok=True)

    @staticmethod
    def _create_schema(db,policy,source_revision):
            db.execute('CREATE TABLE batch(id INTEGER PRIMARY KEY CHECK(id=1),schema INTEGER,policy TEXT,source_revision TEXT,paused INTEGER,cutover TEXT,heartbeat REAL,dispatcher TEXT)')
            db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,spec TEXT NOT NULL,path TEXT UNIQUE NOT NULL,state TEXT NOT NULL,attempt INTEGER NOT NULL DEFAULT 0,automatic_retries INTEGER NOT NULL DEFAULT 0,elapsed REAL NOT NULL DEFAULT 0,started REAL,due REAL NOT NULL DEFAULT 0,lease TEXT,lease_until REAL,pid INTEGER,process_start REAL,reason TEXT,review_revision TEXT,package TEXT,resume_stages TEXT)')
            db.execute('CREATE TABLE admissions(id TEXT PRIMARY KEY,job TEXT REFERENCES jobs(id),service TEXT NOT NULL,reserved INTEGER,created REAL NOT NULL,receipt TEXT NOT NULL,origin TEXT)')
            db.execute('CREATE TABLE completion_holds(job TEXT PRIMARY KEY REFERENCES jobs(id),lease TEXT NOT NULL,unit TEXT NOT NULL,buckets TEXT NOT NULL,requested TEXT NOT NULL)')
            db.execute('CREATE TABLE groups(name TEXT NOT NULL,job TEXT NOT NULL REFERENCES jobs(id),PRIMARY KEY(name,job))')
            db.execute('CREATE TABLE claims(kind TEXT,tenant TEXT,market TEXT,code TEXT,intent TEXT,owner TEXT NOT NULL,PRIMARY KEY(kind,tenant,market,code,intent))')
            db.execute("CREATE TABLE decisions(id TEXT PRIMARY KEY,job TEXT,kind TEXT,request TEXT NOT NULL,created REAL NOT NULL,status TEXT NOT NULL DEFAULT 'completed',result TEXT)")
            db.execute('CREATE TABLE wakes(job TEXT,revision TEXT,created REAL NOT NULL,PRIMARY KEY(job,revision))')
            db.execute('CREATE TABLE prior_orders(ref TEXT PRIMARY KEY,seller TEXT NOT NULL,spec TEXT NOT NULL,path TEXT NOT NULL,adopted TEXT)')
            db.execute('CREATE TABLE alerts(id TEXT PRIMARY KEY,job TEXT,code TEXT,message TEXT,created REAL,ack TEXT)')
            db.execute('INSERT INTO batch VALUES(1,?,?,?,?,NULL,NULL,NULL)',(SCHEMA,json.dumps(policy),source_revision,0))

    def settings(self):
        with self.transaction() as db:
            row=dict(db.execute('SELECT * FROM batch WHERE id=1').fetchone());row['policy']=json.loads(row['policy']);return row

    def require_workspace(self):
        if self.path!=workspace_ledger_path():raise AdmissionDenied('Independent batch files cannot authorize spending; use the fixed workspace ledger')

    @staticmethod
    def _claim(db,kind,spec,code,key):
        params=(kind,str(spec.get('seller_id') or ''),str(spec.get('marketplace') or 'US'),str(code),'' if kind=='sku' else str(spec.get('listing_intent') or 'standard'))
        prior=db.execute('SELECT owner FROM claims WHERE kind=? AND tenant=? AND market=? AND code=? AND intent=?',params).fetchone()
        if prior and prior[0]!=key:raise ValueError(f'{kind} already belongs to another order or unreconciled prior work: {code}')
        db.execute('INSERT OR IGNORE INTO claims VALUES(?,?,?,?,?,?)',(*params,key))

    def enqueue(self,spec,job_path, *, group='default'):
        return self.enqueue_many([(spec,job_path)],group=group)[0]

    def enqueue_many(self,entries, *, group='default'):
        rows=[]
        with self.transaction() as db:
            for spec,job_path in entries:
                key=order_identity(spec)
                for name in ('max_paid_calls','budget_microunits'):
                    if name in spec and (type(spec[name]) is not int or spec[name]<0):raise ValueError('Invalid order '+name)
                prior=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
                if prior and identity(json.loads(prior['spec']))!=identity(spec):
                    raise ValueError('Order already exists with another execution revision; explicitly reconcile the original order')
                if spec.get('purpose','production')=='production':self._claim(db,'asin',spec,spec['seed_asin'],key)
                db.execute('INSERT OR IGNORE INTO jobs(id,spec,path,state,reason) VALUES(?,?,?,?,?)',
                    (key,json.dumps(spec,sort_keys=True),str(Path(job_path).resolve()),'initializing','Initialization needs reconciliation'))
                db.execute('INSERT OR IGNORE INTO groups VALUES(?,?)',(group,key))
                rows.append(dict(db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()))
        return rows

    def bind_listings(self,key,lease, *, asins,skus):
        with self.transaction() as db:
            row=self._leased_job(db,key,lease,time.time());spec=json.loads(row['spec'])
            for kind,values in (('asin',asins),('sku',skus)):
                for value in set(values):
                    if not value:raise ValueError('Empty listing claim')
                    self._claim(db,kind,spec,value,key)

    def initialized(self,key):
        with self.transaction() as db:db.execute("UPDATE jobs SET state='queued',reason='' WHERE id=? AND state='initializing'",(key,))

    def claim(self, *, ttl,key=None):
        now=time.time()
        with self.transaction() as db:
            settings=db.execute('SELECT * FROM batch WHERE id=1').fetchone();policy=json.loads(settings['policy'])
            if settings['paused'] or db.execute("SELECT COUNT(*) FROM jobs WHERE state='running'").fetchone()[0]>=policy.get('workers',1):return None
            # Due time controls eligibility; admission order controls fairness.
            # Ordering by due first lets an endless stream of new (due=0) orders
            # starve an older retry as soon as that retry becomes eligible.
            rows=db.execute("SELECT * FROM jobs WHERE state IN ('queued','retry') AND due<=? ORDER BY rowid",(now,)).fetchall()
            for row in rows:
                spec=json.loads(row['spec'])
                if key is not None and row['id']!=key:continue
                if key is None and spec.get('purpose','production')!='production':continue
                remaining=policy.get('total_job_seconds',7200)-row['elapsed']
                if remaining<=0:
                    db.execute("UPDATE jobs SET state='exception',reason='Cumulative order time exhausted' WHERE id=?",(row['id'],));continue
                lease=uuid.uuid4().hex;seconds=min(ttl,policy.get('job_timeout_seconds',7200),remaining)
                db.execute("UPDATE jobs SET state='running',lease=?,lease_until=?,started=?,attempt=attempt+1,pid=NULL,process_start=NULL WHERE id=?",(lease,now+seconds,now,row['id']))
                return dict(db.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone())
        return None

    def attach_process(self,row,pid,process_start):
        with self.transaction() as db:
            self._leased_job(db,row['id'],row['lease'],time.time())
            db.execute('UPDATE jobs SET pid=?,process_start=? WHERE id=?',(pid,process_start,row['id']))

    def complete(self,row, *, state,reason='',due=0,review_revision='',package=''):
        if state not in {'completed','delivered','exception','retry','cancelled','diagnosed'}:raise ValueError('Invalid terminal/wait state')
        with self.transaction() as db:
            current=db.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone()
            if not current or current['lease']!=row['lease'] or current['state']!='running':raise AdmissionDenied('Stale worker cannot settle another lease')
            elapsed=max(0,time.time()-(current['started'] or time.time()))
            policy=json.loads(db.execute('SELECT policy FROM batch WHERE id=1').fetchone()[0])
            if state=='retry' and current['automatic_retries']>=policy.get('max_attempts',1)-1:state='exception'
            db.execute('UPDATE jobs SET state=?,reason=?,due=?,review_revision=?,package=?,elapsed=elapsed+?,automatic_retries=automatic_retries+?,lease=NULL,lease_until=NULL WHERE id=?',
                (state,reason[:2000],due,review_revision,package,elapsed,int(state=='retry'),row['id']))
            if state=='exception':self._alert(db,row['id'],'order_exception',reason)

    def requeue(self,key, *, review_revision,explicit=False):
        with self.transaction() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
            if not row or row['state']!='exception' or not review_revision or row['review_revision']==review_revision:return False
            # A changed fingerprint implementation is not new evidence or retry permission.
            if not explicit and any(not str(value or '').startswith(REVIEW_PREFIX) for value in (row['review_revision'],review_revision)):return False
            if db.execute('SELECT 1 FROM wakes WHERE job=? AND revision=?',(key,review_revision)).fetchone():return False
            db.execute('INSERT INTO wakes VALUES(?,?,?)',(key,review_revision,time.time()))
            db.execute("UPDATE jobs SET state='queued',due=0,reason='',review_revision=? WHERE id=?",(review_revision,key));return True

    @staticmethod
    def _decision(db,decision_id,key,kind,request):
        if not decision_id or not request.get('reason'):raise ValueError('Explicit decision ID and reason required')
        digest=identity(request);old=db.execute('SELECT * FROM decisions WHERE id=?',(decision_id,)).fetchone()
        if old:
            if (old['job'],old['kind'],old['request'])!=(key,kind,digest):raise ValueError('Decision ID conflicts with its original action')
            return False
        db.execute('INSERT INTO decisions(id,job,kind,request,created) VALUES(?,?,?,?,?)',(decision_id,key,kind,digest,time.time()));return True

    def revise_order(self,key, *, spec,expected_spec,decision_id,reason):
        if order_identity(spec)!=key:raise ValueError('Execution revision cannot change business identity')
        with self.transaction() as db:
            request={'spec':spec,'expected_spec':expected_spec,'reason':reason}
            if not self._decision(db,decision_id,key,'execution_revision',request):return
            row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
            if not row or row['state'] in {'running','delivered','cancelled'} or identity(json.loads(row['spec']))!=expected_spec:raise ValueError('Stale/running order revision')
            marker='execution:'+decision_id
            db.execute('INSERT OR IGNORE INTO wakes VALUES(?,?,?)',(key,marker,time.time()))
            db.execute("UPDATE jobs SET spec=?,state='queued',reason='Execution revision explicitly reconciled',review_revision=?,due=0 WHERE id=?",(json.dumps(spec,sort_keys=True),marker,key))

    def rebind_source(self, *, expected,revision,decision_id,reason):
        with self.transaction() as db:
            if not self._decision(db,decision_id,'workspace','source_revision',{'expected':expected,'revision':revision,'reason':reason}):return
            row=db.execute('SELECT * FROM batch WHERE id=1').fetchone()
            if not row['paused'] or row['source_revision']!=expected or db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():raise ValueError('Pause and settle workers before explicit source revision')
            db.execute('UPDATE batch SET source_revision=? WHERE id=1',(revision,))

    def authorize_policy(self,policy, *, expected_revision,decision_id,reason):
        """Separate explicit budget authorization; never invoked by retries or group creation."""
        _validate_policy(policy)
        with self.transaction() as db:
            if not self._decision(db,decision_id,'workspace','budget_policy',{'policy':policy,'before':expected_revision,'reason':reason}):return
            old=db.execute('SELECT * FROM batch WHERE id=1').fetchone();previous=json.loads(old['policy'])
            if not old['paused'] or identity(previous)!=expected_revision or db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
                raise ValueError('Pause/settle workers and refresh the budget policy before authorizing')
            if previous.get('currency') and policy.get('currency')!=previous['currency']:raise ValueError('Cannot reinterpret recorded reservations in another currency')
            db.execute('UPDATE batch SET policy=? WHERE id=1',(json.dumps(policy),))

    def pause(self,paused=True):
        with self.transaction() as db:db.execute('UPDATE batch SET paused=? WHERE id=1',(int(paused),))

    def rows(self):
        with self.transaction() as db:return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY id')]

    @staticmethod
    def _leased_job(db,key,lease,now):
        row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
        if not row or row['state']!='running' or row['lease']!=lease or row['lease_until']<=now:raise AdmissionDenied('No current worker lease; no request sent')
        return row

    def worker(self,key,lease, *, job_path=None):
        with self.transaction() as db:
            row=self._leased_job(db,key,lease,time.time())
            if job_path is not None and Path(row['path']).resolve()!=Path(job_path).resolve():raise AdmissionDenied('Worker lease belongs to another job')
            return dict(row)

    @staticmethod
    def _completion_holds(db,now):
        return [{**dict(row),'buckets':json.loads(row['buckets'])} for row in db.execute(
            "SELECT h.* FROM completion_holds h JOIN jobs j ON j.id=h.job WHERE j.state='running' AND j.lease=h.lease AND j.lease_until>?",(now,))]

    @staticmethod
    def _held_totals(holds):
        return (sum(b['calls'] for h in holds for b in h['buckets'].values()),
                sum(b['calls']*b['price'] for h in holds for b in h['buckets'].values()))

    def reserve_completion(self,*,key,lease,unit,stages):
        """Earmark unused capacity in this same domain; never create spending credit."""
        if not isinstance(unit,str) or not unit or not isinstance(stages,dict) or set(stages)-COMPLETION_SERVICES.keys() or any(type(v) is not int or not 0<=v<=10000 for v in stages.values()):
            raise ValueError('Invalid work-unit closing estimate')
        with self.transaction() as db:
            row=self._leased_job(db,key,lease,time.time());policy=json.loads(db.execute('SELECT policy FROM batch WHERE id=1').fetchone()[0]);spec=json.loads(row['spec'])
            existing=db.execute('SELECT * FROM completion_holds WHERE job=?',(key,)).fetchone()
            if existing and existing['lease']==lease:
                if existing['unit']!=unit:raise AdmissionDenied('Finish/release the original work unit before reserving another')
                if json.loads(existing['requested'])!=stages:raise ValueError('Work-unit estimate changed inside an active reservation')
                buckets=json.loads(existing['buckets'])
            else:
                holds=self._completion_holds(db,time.time());held_calls,held_money=self._held_totals(holds)
                count,amount,unknown=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions').fetchone()
                own,own_amount,own_unknown=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions WHERE job=?',(key,)).fetchone()
                available=max(0,min(policy['max_paid_calls']-count-held_calls,spec.get('max_paid_calls',policy['max_paid_calls'])-own))
                caps=[]
                if policy.get('budget_microunits') is not None:caps.append(0 if unknown else policy['budget_microunits']-amount-held_money)
                if spec.get('budget_microunits') is not None:caps.append(0 if own_unknown else spec['budget_microunits']-own_amount)
                money=max(0,min(caps)) if caps else float('inf');prices=policy.get('request_upper_bounds') or {};buckets={}
                # Under a shortfall protect closure before opening another upstream request.
                for stage in reversed(COMPLETION_SERVICES):
                    if stage not in stages:continue
                    wanted=stages[stage]
                    price=max([0,*[prices[s] for s in COMPLETION_SERVICES[stage] if s in prices]])
                    allocated=min(wanted,available,int(money//price) if price and money!=float('inf') else available)
                    buckets[stage]={'calls':allocated,'price':price};available-=allocated;money-=allocated*price
                db.execute('INSERT OR REPLACE INTO completion_holds VALUES(?,?,?,?,?)',(key,lease,unit,json.dumps(buckets),json.dumps(stages)))
            calls,amount=self._held_totals([{'buckets':buckets}])
            return {'unit':unit,'held_calls':calls,'held_microunits':amount,'requested_calls':sum(stages.values()),
                    'shortfall_calls':max(0,sum(stages.values())-calls),'buckets':buckets,'spending_limit_changed':False}

    def release_completion(self,*,key,lease,unit,stage=None):
        """Release only unused earmarks; admitted calls and amounts are immutable."""
        with self.transaction() as db:
            self._leased_job(db,key,lease,time.time())
            row=db.execute('SELECT * FROM completion_holds WHERE job=? AND lease=? AND unit=?',(key,lease,unit)).fetchone()
            if not row:return
            if stage is None:db.execute('DELETE FROM completion_holds WHERE job=?',(key,))
            else:
                buckets=json.loads(row['buckets']);buckets.pop(stage,None)
                db.execute('UPDATE completion_holds SET buckets=? WHERE job=?',(json.dumps(buckets),key))

    def reserve(self, *, key,lease,service,request_id,receipt='',unit='',stage=''):
        now=time.time()
        with self.transaction() as db:
            settings=db.execute('SELECT * FROM batch WHERE id=1').fetchone();row=self._leased_job(db,key,lease,now)
            if settings['paused']:raise AdmissionDenied('Workspace paused; no paid request sent')
            policy=json.loads(settings['policy']);spec=json.loads(row['spec'])
            count,reserved,unknown=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions').fetchone()
            own=db.execute('SELECT COUNT(*) FROM admissions WHERE job=?',(key,)).fetchone()[0]
            if count>=policy['max_paid_calls'] or own>=spec.get('max_paid_calls',policy['max_paid_calls']):raise AdmissionDenied('Workspace/order paid request limit exhausted','request_budget_exhausted')
            price=(policy.get('request_upper_bounds') or {}).get(service);cap=policy.get('budget_microunits')
            own_amount,own_unknown=db.execute('SELECT COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions WHERE job=?',(key,)).fetchone()
            own_cap=spec.get('budget_microunits',cap)
            holds=self._completion_holds(db,now);own_hold=next((h for h in holds if h['job']==key),None)
            if unit and own_hold and own_hold['unit']!=unit:raise AdmissionDenied('Request belongs to another reserved work unit')
            bucket=(own_hold or {}).get('buckets',{}).get(stage)
            if unit and own_hold and bucket and service in COMPLETION_SERVICES.get(stage,set()) and bucket['calls']:
                bucket['calls']-=1
            held_calls,held_money=self._held_totals(holds)
            own_held_calls,own_held_money=self._held_totals([own_hold] if own_hold else [])
            if count+1+held_calls>policy['max_paid_calls'] or own+1+own_held_calls>spec.get('max_paid_calls',policy['max_paid_calls']):
                raise AdmissionDenied('Remaining calls are earmarked for active unit completion','completion_capacity_reserved')
            if (cap is not None and price is not None and reserved+price+held_money>cap) or (own_cap is not None and price is not None and own_amount+price+own_held_money>own_cap):
                raise AdmissionDenied('Remaining money is earmarked for active unit completion','completion_capacity_reserved')
            if own_cap is not None and (own_unknown or price is None or own_amount+price>own_cap or not policy.get('currency')):
                raise AdmissionDenied('Order monetary bound unavailable or exhausted','order_money_blocked')
            if cap is not None and (unknown or price is None or reserved+price>cap):raise AdmissionDenied('Unpriced prior consumption, missing cost bound or monetary budget exhausted','workspace_money_blocked')
            try:db.execute('INSERT INTO admissions VALUES(?,?,?,?,?,?,NULL)',(request_id,key,service,price,now,receipt or request_id))
            except sqlite3.IntegrityError as exc:raise AdmissionDenied('Request already reserved; recover its original receipt') from exc
            if own_hold:db.execute('UPDATE completion_holds SET buckets=? WHERE job=?',(json.dumps(own_hold['buckets']),key))

    def free_capacity_available(self,*,key,services=()):
        """Read-only unearmarked headroom; no request or permission is created."""
        with self.transaction() as db:
            policy=json.loads(db.execute('SELECT policy FROM batch WHERE id=1').fetchone()[0])
            count,amount,unknown=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions').fetchone()
            calls,money=self._held_totals(self._completion_holds(db,time.time()))
            cap=policy.get('budget_microunits')
            if count+calls>=policy['max_paid_calls'] or cap is not None and (unknown or amount+money>=cap):return False
            row=db.execute('SELECT spec FROM jobs WHERE id=?',(key,)).fetchone()
            if not row:return False
            spec=json.loads(row['spec'])
            own,spent,unpriced=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),COALESCE(SUM(reserved IS NULL),0) FROM admissions WHERE job=?',(key,)).fetchone()
            if own>=spec.get('max_paid_calls',policy['max_paid_calls']):return False
            own_cap=spec.get('budget_microunits',cap)
            if own_cap is not None and (unpriced or spent>=own_cap):return False
            prices=policy.get('request_upper_bounds') or {}
            return any((cap is None and own_cap is None) or service in prices
                       and (cap is None or amount+money+prices[service]<=cap)
                       and (own_cap is None or spent+prices[service]<=own_cap) for service in services) if services else True

    def cost(self):
        with self.transaction() as db:
            count,amount,unknown=db.execute('SELECT COUNT(*),COALESCE(SUM(reserved),0),SUM(reserved IS NULL) FROM admissions').fetchone()
            held_calls,held_money=self._held_totals(self._completion_holds(db,time.time()))
            return {'admitted_requests':count,'reserved_microunits':amount,'unpriced_requests':unknown or 0,'actual_cost':None,'settlement':'provider_invoice_not_reconciled',
                    'closing_held_calls':held_calls,'closing_held_microunits':held_money}

    @staticmethod
    def _alert(db,key,code,message):
        tag=identity([key,code,message]);db.execute('INSERT OR IGNORE INTO alerts VALUES(?,?,?,?,?,NULL)',(tag,key,code,str(message)[:2000],time.time()))

    def begin_action(self,key,decision_id,request):
        if not decision_id or not request.get('reason'):raise ValueError('Decision ID and reason required')
        with self.transaction() as db:
            prior=db.execute('SELECT * FROM decisions WHERE id=?',(decision_id,)).fetchone()
            digest=identity(request)
            if prior:
                if prior['job']!=key or prior['request']!=digest or prior['kind']!='console_action':raise ValueError('Decision ID reused with another action')
                return json.loads(prior['result']) if prior['result'] else {'status':'pending_reconciliation','requests_sent':0}
            db.execute("INSERT INTO decisions(id,job,kind,request,created,status) VALUES(?,?,'console_action',?,?,'pending')",(decision_id,key,digest,time.time()))
        return None

    def finish_action(self,decision_id,result):
        with self.transaction() as db:
            db.execute("UPDATE decisions SET status='completed',result=? WHERE id=? AND status='pending'",(json.dumps(result),decision_id))

    def cancel_order(self,key, *, decision_id,reason):
        with self.transaction() as db:
            if not self._decision(db,decision_id,key,'cancel',{'reason':reason}):return
            row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
            if not row or row['state'] in {'running','delivered'}:raise ValueError('Pause and settle active work before cancellation; no refund or interruption is implied')
            db.execute("UPDATE jobs SET state='cancelled',reason=? WHERE id=?",(reason,key))

    def publication_refresh(self,key, *, decision_id,reason):
        with self.transaction() as db:
            if not self._decision(db,decision_id,key,'publication_refresh',{'reason':reason}):return
            row=db.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
            if not row or row['state'] in {'running','cancelled','initializing'} or not row['package']:
                raise ValueError('Only an idle previously delivered order can refresh publication')
            marker='publication:'+decision_id
            db.execute('INSERT OR IGNORE INTO wakes VALUES(?,?,?)',(key,marker,time.time()))
            db.execute("UPDATE jobs SET state='queued',due=0,review_revision=?,resume_stages=?,reason='Publication-only refresh authorized; no image regeneration' WHERE id=?",
                (marker,json.dumps(['publish','template']),key))

    def record_alert(self,key,code,message):
        with self.transaction() as db:self._alert(db,key,code,message)

    def heartbeat(self,dispatcher):
        with self.transaction() as db:db.execute('UPDATE batch SET heartbeat=?,dispatcher=? WHERE id=1',(time.time(),dispatcher))

    def alerts(self):
        with self.transaction() as db:return [dict(r) for r in db.execute('SELECT * FROM alerts ORDER BY created DESC')]

    def acknowledge(self,alert_id, *, decision_id,reason):
        with self.transaction() as db:
            if not self._decision(db,decision_id,alert_id,'acknowledge',{'reason':reason}):return
            if db.execute('UPDATE alerts SET ack=? WHERE id=?',(decision_id,alert_id)).rowcount!=1:raise ValueError('Unknown alert')


def admit_paid_request(service,request_id=None, *, receipt_path=None):
    from .service_response import current_request_admission,ServiceOutcomeUnknown
    context=current_request_admission()
    if context and context['admitted']:raise ServiceOutcomeUnknown('Original physical request already admitted; never submit twice')
    attempt=context['id'] if context else request_id
    path,key,lease=(os.environ.get(k) for k in ('FACTORY_BATCH_DB','FACTORY_BATCH_JOB','FACTORY_BATCH_LEASE'))
    if not path or not key or not lease or not attempt:raise AdmissionDenied('Paid request requires an enrolled worker and durable receipt')
    ledger=BatchLedger(path)
    try:
        ledger.require_workspace();worker=ledger.worker(key,lease)
        from .production_batch import production_revision
        from .io import assert_execution_environment
        assert_execution_environment()
        if ledger.settings()['source_revision']!=production_revision():
            raise AdmissionDenied('Execution source changed before paid admission; reconcile the original workspace revision')
        owned=context['receipt_path'] if context else receipt_path
        if not owned:raise AdmissionDenied('Detached request ID has no durable receipt')
        receipt=Path(owned).resolve()
        if not receipt.is_file() or not receipt.is_relative_to(Path(worker['path']).resolve()):raise AdmissionDenied('Receipt does not belong to enrolled job')
        ledger.reserve(key=key,lease=lease,service=service,request_id=attempt,receipt=str(receipt),
                       unit=os.environ.get('FACTORY_WORK_UNIT',''),stage=os.environ.get('FACTORY_WORK_STAGE',''))
    except AdmissionDenied as exc:
        exc.service=service
        try:
            if ledger.path==workspace_ledger_path():ledger.record_alert(key,exc.reason_code,str(exc))
        except (OSError,ValueError,sqlite3.Error):pass
        raise
    except (OSError,sqlite3.Error,KeyError,ValueError) as exc:raise AdmissionDenied(f'Workspace unavailable before submission: {type(exc).__name__}') from exc
    if context:context['admitted']=True
    return attempt

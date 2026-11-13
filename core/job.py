from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .io import read_json, safe_path_component, utc_now, write_json, file_sha256
from .paths import JOBS_ROOT
from .plugin import ProductPlugin


class JobError(RuntimeError):
    pass


_MAX_JOB_COLLISIONS = 1000
JOB_PROTOCOL_VERSION = "6.0"

_REQUIRED_JOB_FIELDS = ("category_id", "product_type", "seed_asin", "brand", "sku_prefix", "image_root", "r2_prefix")


def slug(value: str) -> str:
    return safe_path_component(value, fallback="job")


def create_job(
    *,
    plugin: ProductPlugin,
    seed_asin: str,
    brand: str,
    sku_prefix: str,
    template_path: str = "",
    marketplace: str = "US",
    config_path: str = "",
    manufacturer: str = "",
    country: str = "",
    condition: str = "",
    quantity: str = "",
    fulfillment: str = "",
    list_price: str = "",
    shipping_template: str = "",
    gtin_exempt: bool | None = None,
    product_id_type: str = "",
    product_id: str = "",
    out_root: str | Path = JOBS_ROOT,
    timestamp: str | None = None,
    design_pack_path: str = "",
    brand_brief_path: str = "",
    business_input_path: str = "",
    seller_id: str = "",
    listing_intent: str = "standard",
    max_family_members: int | None = None,
    execution_policy: str = 'progressive',
    initialization_key: str = '',
    reserved_path: str | Path | None = None,
) -> Path:
    seed_asin = str(seed_asin).strip().upper()
    marketplace = str(marketplace).strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{10}', seed_asin):
        raise JobError('seed_asin must contain exactly ten letters/digits')
    if marketplace != 'US':
        raise JobError('Production listing contracts currently support US only')
    if not str(brand).strip() or not str(sku_prefix).strip():
        raise JobError('Brand and SKU prefix must be explicit')
    if execution_policy not in {'strict', 'progressive'}:
        raise JobError('execution_policy must be strict or progressive')
    if max_family_members is not None and (type(max_family_members) is not int or max_family_members < 1):
        raise JobError('max_family_members must be a positive candidate selection limit')
    if gtin_exempt is not None and type(gtin_exempt) is not bool:
        raise JobError('GTIN exemption must be a boolean or unresolved')
    if quantity not in (None, '') and not re.fullmatch(r'\d+', str(quantity).strip()):
        raise JobError('Inventory quantity must be an explicit nonnegative integer')
    scope={'seed_asin':seed_asin,'brand':brand,'marketplace':marketplace,'category_id':plugin.category_id,'seller_id':seller_id}
    business_input_path=business_input_path or default_business_input(scope)
    business = read_business_input(business_input_path,scope) if business_input_path else None
    stamp = timestamp or _timestamp_slug()
    safe_seed = slug(seed_asin)
    base_name = f"{safe_seed}_{stamp}"
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    for counter in range(1, _MAX_JOB_COLLISIONS + 1):
        job_name = base_name if counter == 1 else f"{base_name}_{counter}"
        job_dir = root / job_name
        if reserved_path is not None and (counter != 1 or job_dir.resolve() != Path(reserved_path).resolve()):
            raise JobError('Reserved initializer path differs from the admitted order')
        try:
            job_dir.mkdir(exist_ok=False)
            break
        except FileExistsError:
            if reserved_path is not None:
                if job_dir.is_symlink() or not job_dir.is_dir() or any(job_dir.iterdir()):
                    raise JobError('Reserved initializer directory contains unknown content')
                break  # The ledger owns this empty allocation, not arbitrary existing files.
            continue
    else:
        raise JobError(f"Unable to allocate unique job directory after {_MAX_JOB_COLLISIONS} attempts: {base_name}")
    job = {
        "protocol_version": JOB_PROTOCOL_VERSION,
        "category_id": plugin.category_id,
        "product_type": plugin.product_type,
        "seed_asin": seed_asin,
        "brand": brand,
        "seller_id": seller_id,
        "listing_intent": listing_intent,
        **({'max_family_members': max_family_members} if max_family_members is not None else {}),
        'execution_policy': execution_policy,
        "manufacturer": manufacturer,
        "sku_prefix": sku_prefix,
        "marketplace": marketplace,
        "template_path": str(Path(template_path).resolve()) if template_path else "",
        "config_path": str(Path(config_path).resolve()) if config_path else "",
        "child_sku_source": "generated",
        "gtin_exempt": gtin_exempt,
        "product_id_type": product_id_type,
        "product_id": product_id,
        "country": country,
        "condition": condition,
        "quantity": quantity,
        "fulfillment": fulfillment,
        "shipping_template": shipping_template,
        "list_price": list_price,
        "image_root": str(job_dir / "images"),
        "r2_prefix": f"amazon-listing/generated/original/{plugin.category_id}/{job_name}",
        "created_at": utc_now(),
        "upload_encoding": "jpeg-q95-444-v1",
        "plugin_root": str(plugin.root),
    }
    if business:
        for key, value in business['values'].items():
            if job.get(key) is None or job.get(key) == '':
                job[key] = value
        job['business_input'] = business
    status = {
        "schema_version": 8,
        "job_id": job_name,
        "stage": "created",
        "status": "pending",
        "updated_at": job["created_at"],
        "errors": [],
        "invalidated_errors": [],
        "warnings": [],
        "artifacts": {"job": str(job_dir / "job.json")},
        "stages": {},
        "tasks": {},
        "task_history": [],
    }
    inputs = {kind: {'path': str(Path(value).resolve()), 'sha256': file_sha256(Path(value))}
              for kind, value in (('pack_path', design_pack_path), ('brief_path', brand_brief_path)) if value}
    write_json(job_dir/'initialization.json', {'schema':'job-initialization-v1','key':initialization_key,
               'job':job,'state':status,'inputs':inputs})
    return resume_job_initialization(job_dir, expected_key=initialization_key)


def resume_job_initialization(job_dir: str | Path, *, expected_key: str) -> Path:
    """Finish this allocation's immutable intent; never erase an unknown directory."""
    from .design_reference_library import import_design_inputs
    from .status import input_revision_id
    job_dir=Path(job_dir).resolve();path=job_dir/'initialization.json'
    intent=read_json(path)
    if intent.get('schema')!='job-initialization-v1' or intent.get('key')!=expected_key:
        raise ValueError('Initialization belongs to a different admitted input')
    job=dict(intent['job']);inputs=intent['inputs']
    for item in inputs.values():
        if file_sha256(Path(item['path']))!=item['sha256']:raise ValueError('Initialization design input changed')
    for child in ('source','source/apify_raw','images','template','reports'):
        (job_dir/child).mkdir(parents=True,exist_ok=True)
    job['design_inputs']=import_design_inputs(job_dir,category=job['category_id'],**{k:v['path'] for k,v in inputs.items()})
    allowed={'initialization.json','job_state.json','job.json',*[r['path'] for r in job['design_inputs']['references']]}
    if any(p.is_file() and p.relative_to(job_dir).as_posix() not in allowed for p in job_dir.rglob('*')):
        raise ValueError('Initialization contains unknown files; only this order is paused')
    for name,value in (('job_state.json',intent['state']),('job.json',job)):
        target=job_dir/name
        if target.is_file():
            if input_revision_id(read_json(target))!=input_revision_id(value):raise ValueError('Initialization has unrelated later writes')
        else:write_json(target,value)
    return job_dir


def load_job(job_dir: str | Path) -> dict[str, Any]:
    path = Path(job_dir) / "job.json"
    data = read_json(path)
    if not isinstance(data, dict):
        raise JobError(f"Job file is not an object: {path}")
    if str(data.get("protocol_version") or "") != JOB_PROTOCOL_VERSION:
        raise JobError(f"Unsupported job protocol in {path}. Create a new job; historical jobs are not migrated.")
    required = _REQUIRED_JOB_FIELDS
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise JobError(f"Job file is missing required field(s): {', '.join(missing)} ({path})")
    return data


BUSINESS_FIELDS = {'manufacturer','country','condition','fulfillment','shipping_template','dangerous_goods',
    'batteries_required','batteries_included','contains_battery','is_fragile','package_level','gtin_exempt','publication_policy'}
SKU_PRODUCT_DECLARATIONS = {'model_number', 'model_name', 'required_product_compliance_certificate'}
SKU_BUSINESS_FIELDS = {'quantity','inventory_available','selling_price','list_price','price_policy','product_id','product_id_type'} | SKU_PRODUCT_DECLARATIONS


def default_business_input(job, *, seller_wide=False):
    """Prefer the exact category. A seller-wide product declaration is scoped on read."""
    from .paths import FACTORY_ROOT
    category, general = [], []
    if not job.get('seller_id'):return ''
    for path in (FACTORY_ROOT/'configs/business_profiles').glob('*.json'):
        scope=read_json(path).get('scope',{})
        if scope.get('seller_id')!=job['seller_id']:continue
        if any(str(scope.get(k,'')).casefold()!=str(job.get(k,'')).casefold() for k in ('brand','marketplace')):continue
        if scope.get('seed_asin') and scope['seed_asin']!=job.get('seed_asin'):continue
        if scope.get('category_id') == '*':
            general.append(path)
        elif not seller_wide and str(scope.get('category_id','')).casefold() == str(job.get('category_id','')).casefold():
            category.append(path)
    matches = category or general
    if len(matches)>1:raise JobError('Multiple approved business profiles match; choose an explicit input')
    return str(matches[0]) if matches else ''


def read_business_input(path: str | Path, job: dict[str, Any]) -> dict[str, Any]:
    """Explicit operator evidence, snapshotted once; never infer physical product facts."""
    import hashlib,json
    def read_scoped(file):
        raw = Path(file).read_bytes()
        data = json.loads(raw.decode('utf-8-sig'))
        if data.get('scope', {}).get('category_id') == '*':
            if (not data['scope'].get('seller_id') or set(data['scope']) != {'seller_id','brand','marketplace','category_id'}
                    or set(data.get('values', {})) != {'batteries_required'} or data.get('sku_values') or data.get('sku_defaults')):
                raise JobError('Only an exact seller, brand and site battery declaration can cover all categories')
            data['scope']['category_id'] = job['category_id']
        _validate_business_input(data, job)
        return raw, data
    raw, data = read_scoped(path)
    digest = hashlib.sha256(raw).hexdigest()
    if 'batteries_required' not in data['values']:
        standing = default_business_input(job, seller_wide=True)
        if standing and Path(standing).resolve() != Path(path).resolve():
            policy_bytes, policy = read_scoped(standing)
            if 'batteries_required' in policy['values']:
                from .status import input_revision_id
                policy_sha = hashlib.sha256(policy_bytes).hexdigest()
                data['values']['batteries_required'] = policy['values']['batteries_required']
                data['source'] += f" | Battery requirement from {Path(standing).name} ({policy_sha}). Submitted profile {digest}."
                digest = input_revision_id({'submitted':digest,'battery_declaration':policy_sha})
    return {**data,'input_sha256':digest,'authority':'operator_provided'}


def _validate_business_input(data,job):
    from datetime import datetime,timezone
    from decimal import Decimal,InvalidOperation
    required={'schema','scope','source','values'}
    if not isinstance(data,dict) or not required<=set(data) or set(data)-required-{'sku_values','sku_defaults','maintenance','valid_until','input_sha256','authority'} or data['schema']!='business-input-v2':
        raise JobError('Current business-input-v2 requires scoped values; retired family inventory inputs are not migrated')
    scope,values,skus=data['scope'],data['values'],data.get('sku_values',{})
    defaults=data.get('sku_defaults',{});maintenance=data.get('maintenance','dated')
    if maintenance not in {'dated','operator_managed'}:raise JobError('Unknown business maintenance policy')
    if not isinstance(scope,dict) or set(scope)-{'brand','marketplace','category_id','seed_asin','seller_id'}:
        raise JobError('Invalid business input scope')
    for field in ('brand','marketplace','category_id'):
        if not str(scope.get(field) or '').strip() or str(scope[field]).strip().casefold()!=str(job.get(field) or '').strip().casefold():
            raise JobError('Business input belongs to another '+field)
    if scope.get('seed_asin') and scope['seed_asin']!=job['seed_asin']:raise JobError('Business input belongs to another source family')
    if scope.get('seller_id') and scope['seller_id']!=job.get('seller_id'):raise JobError('Business input belongs to another seller')
    if not isinstance(values,dict) or set(values)-BUSINESS_FIELDS or not isinstance(skus,dict) or not isinstance(defaults,dict) or set(defaults)-SKU_BUSINESS_FIELDS or not(values or skus or defaults):
        raise JobError('Business input contains unsupported or empty values')
    if not isinstance(data['source'],str) or not data['source'].strip():raise JobError('Explicit evidence source required')
    if skus and (scope.get('seed_asin')!=job['seed_asin'] or not scope.get('seller_id') or scope['seller_id']!=job.get('seller_id')):
        raise JobError('Inventory evidence must name the exact family, seller and SKU')
    if (defaults or maintenance=='operator_managed') and (not scope.get('seller_id') or scope['seller_id']!=job.get('seller_id')):
        raise JobError('Standing defaults/maintenance responsibility require the exact seller scope')
    expiry=data.get('valid_until')
    if (skus or defaults) and not expiry and maintenance!='operator_managed':
        raise JobError('Stock/price evidence needs a valid_until or explicit operator-managed responsibility')
    if expiry:
        try:expires=datetime.fromisoformat(expiry)
        except (TypeError,ValueError) as exc:raise JobError('Invalid business evidence expiry') from exc
        if expires.tzinfo is None or expires<=datetime.now(timezone.utc):raise JobError('Business evidence expired or has no timezone')
    booleans={'inventory_available','batteries_required','batteries_included','contains_battery','is_fragile','gtin_exempt'}
    def check(fields):
        for field,value in fields.items():
            if field=='publication_policy':
                from .publish import validate_publication_policy
                validate_publication_policy(value)
                continue
            if field in booleans:
                if type(value) is not bool:raise JobError(field+' must be a JSON boolean')
            elif field=='quantity':
                if type(value) is not int or value<0:raise JobError('Inventory quantity must be a nonnegative integer')
            elif field in {'list_price','selling_price'}:
                try:number=Decimal(str(value))
                except InvalidOperation as exc:raise JobError('Invalid explicit price') from exc
                if not number.is_finite() or number<0 or field=='selling_price' and number==0:
                    raise JobError('Prices must be finite; only List Price may be zero')
            elif not isinstance(value,str) or not value.strip():raise JobError(field+' needs an explicit nonempty value')
            if field=='price_policy' and value not in {'explicit','use_source_list_price','same_as_list_price'}:raise JobError('Unknown price policy')
    if {'product_id','product_id_type'} & set(defaults):
        raise JobError('Product identifiers must be scoped to one SKU, never shared defaults')
    if SKU_PRODUCT_DECLARATIONS & set(defaults):
        raise JobError('Model and certificate declarations must identify the exact SKU')
    check(values);check(defaults)
    identifiers = set()
    for sku,fields in skus.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',str(sku)) or not isinstance(fields,dict) or not fields or set(fields)-SKU_BUSINESS_FIELDS:
            raise JobError('Invalid SKU-scoped business input')
        check(fields)
        if {'product_id','product_id_type'} & set(fields):
            kind, value = fields.get('product_id_type'), fields.get('product_id', '')
            lengths = {'UPC': (12,), 'EAN': (13,), 'GTIN': (14,), 'ISBN': (10,13)}
            if kind not in lengths or len(value) not in lengths[kind] or not re.fullmatch(r'\d+[\dX]?',value):
                raise JobError('SKU product identifier requires an explicit supported type and matching format')
            canonical = value.lstrip('0')
            if canonical in identifiers:raise JobError('Different SKUs cannot reuse one product identifier')
            identifiers.add(canonical)


def business_for_sku(job,sku, *, submit_ready):
    """Apply explicit scoped defaults, then exact SKU overrides; never invent stock."""
    result=dict(job);business=job.get('business_input')
    if submit_ready:
        for field in SKU_BUSINESS_FIELDS - {'product_id','product_id_type'}:result[field]=''
        if any('product_id' in values for values in (business or {}).get('sku_values',{}).values()):
            result.update(product_id='', product_id_type='')
    if business:
        _validate_business_input(business,job)
        result.update(business.get('sku_defaults') or {})
        result.update((business.get('sku_values') or {}).get(sku,{}))
    return result


def update_business_inputs(job_dir: str | Path, input_path: str | Path, *, expected_job_sha256: str,
                           decision_id: str, reason: str) -> dict[str, Any]:
    """One locked, idempotent business decision; never changes production state or budgets."""
    from .status import job_run_lock, input_revision_id
    if not decision_id.strip() or not reason.strip():raise JobError('A decision ID and reason are required')
    root=Path(job_dir).resolve();path=root/'job.json'
    with job_run_lock(root):
        job=load_job(root);business=read_business_input(input_path,job)
        request=input_revision_id({'before':expected_job_sha256,'input':business['input_sha256'],'reason':reason})
        decisions=job.get('business_decisions') or []
        previous=next((r for r in decisions if r['id']==decision_id),None)
        if previous:
            if previous['request']!=request:raise JobError('Business decision ID reused with different content')
            return {'status':'already_applied','job_sha256':file_sha256(path),'requests_sent':0}
        if file_sha256(path)!=expected_job_sha256:raise JobError('Job inputs changed; refresh before applying this decision')
        job.update(business['values'])
        job['business_input']=business
        job['business_decisions']=[*decisions,{'id':decision_id,'request':request,'source':business['source'],
            'input_sha256':business['input_sha256'],'before_job_sha256':expected_job_sha256,'reason':reason,'at':utc_now()}]
        write_json(path,job)
    return {'status':'applied','job_sha256':file_sha256(path),'requests_sent':0}


def _timestamp_slug() -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", utc_now())[:21]

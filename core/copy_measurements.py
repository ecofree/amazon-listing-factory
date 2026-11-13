"""Measurement support checks inside CopyWriter, consuming its existing effective facts."""
from __future__ import annotations
import re
from typing import Any
from .text_evidence import normalize_text,extract_measurements,measurement_qualifiers,measurement_values_match

_AXES={'l':'length','length':'length','long':'length','w':'width','width':'width','wide':'width',
       'h':'height','height':'height','high':'height','tall':'height','d':'depth','depth':'depth','deep':'depth',
       'thickness':'thickness','thick':'thickness','diameter':'diameter'}
_AXIS_RE=re.compile(r'\b('+ '|'.join(_AXES)+r')\b',re.I)
_OWNERS=((r'\bmattress\b','mattress'),(r'\b(?:under[- ]bed\s+|floor\s+|ground\s+)?clearance\b','clearance'),(r'\b(?:package|packaging|shipping|carton)\b','package'),
         (r'\bshel(?:f|ves)\b','shelf'),(r'\bdrawers?\b','drawer'),(r'\bdoors?\b','door'),
         (r'\b(?:pots?|planters?)\b','pot'),(r'\btrunk\b','trunk'),(r'\b(?:leaves|leaf|branches?|branch)\b','foliage'),(r'\blegs?\b','leg'),
         *((r'\b'+part+r's?\b',part) for part in ('blade','needle','slat','rail','handle','panel','stand')))


def _owner(text):
    return next((owner for pattern,owner in _OWNERS if re.search(pattern,text,re.I)),'product')


def _near_owner(before,after):
    choices=[]
    patterns=(*_OWNERS,(r'\b(?:cabinet|bed[- ]frame|frame|bed|tree|product|unit)\b','product'))
    for pattern,owner in patterns:
        choices.extend((len(before)-m.end(),owner) for m in re.finditer(pattern,before,re.I))
        choices.extend((m.start(),owner) for m in re.finditer(pattern,after,re.I))
    return min(choices,key=lambda row:row[0])[1] if choices else 'product'


def _axis(text):
    values={_AXES[m[0].lower()] for m in _AXIS_RE.finditer(text)}
    return next(iter(values)) if len(values)==1 else ''


def _relations(context,field,before):
    result=set(measurement_qualifiers(context))
    # Field-qualified limits are facts; unrelated 'maximum storage' prose is not a numeric bound.
    relation_context=field if field else before
    bound_parameter=r'\s+(?:\w+\s+){0,3}(?:height|width|length|depth|thickness|diameter|size)\s*(?:is|of|:)?\s*(?:(?:up to|at most|at least|no more than)\s+)?$'
    for pattern,label in ((r'recommend(?:ed|ation)?','recommended'),(r'max|maximum','upper_inclusive'),(r'min|minimum','lower_inclusive')):
        if (field and re.search(r'\b(?:'+pattern+r')\b',field,re.I)) or (not field and re.search(r'\b(?:'+pattern+r')'+bound_parameter,relation_context,re.I)):
            result.add(label)
    return result


def _groups(value):
    text=normalize_text(value);rows=extract_measurements(text)
    raw_values=list(dict.fromkeys(row['raw_text'] for row in rows if row['kind']=='length_mm'))
    groups=[]
    for raw in raw_values:
        values=[r for r in rows if r['raw_text']==raw and r['kind']=='length_mm']
        # Repeated raw expressions have identical quantities but may have different subjects.
        seen=set();quantities=[]
        for r in values:
            key=(r['canonical_value'],r.get('axis_hint'))
            if key not in seen:seen.add(key);quantities.append(r)
        for match in re.finditer(re.escape(raw),text):groups.append((match.start(),match.end(),raw,quantities))
    return text,sorted(groups,key=lambda row:row[0])


def _records(value,*,field=''):
    text,groups=_groups(value);result=[]
    boundaries=[m for m in re.finditer(r'[;:\n,]|(?<!\d)\.(?!\d)|\b(?:and|with|while)\b',text,re.I)
                if m[0] != ':' or not re.search(r'\b(?:'+'|'.join(_AXES)+r')\s*$',text[:m.start()],re.I)]
    for index,(start,end,raw,quantities) in enumerate(groups):
        left=max([0,*[m.end() for m in boundaries if m.end()<=start],groups[index-1][1] if index else 0])
        right=min([len(text),*[m.start() for m in boundaries if m.start()>=end],groups[index+1][0] if index+1<len(groups) else len(text)])
        context=(field+' '+text[left:right]).strip()
        owner=_owner(field) if field else _near_owner(text[left:start],text[end:right])
        relations=_relations(context,field,text[left:start])
        explicit=_axis(field)
        suffix=re.match(r'\s*(?:in\s+)?('+ '|'.join(_AXES)+r')\b',text[end:right],re.I)
        prefix=re.search(r'\b('+ '|'.join(_AXES)+r')\s*(?:is|of|:|=)?\s*$',text[left:start],re.I)
        nearby=_AXES[(suffix or prefix)[1].lower()] if suffix or prefix else _axis(context)
        if 'range' in relations:
            result.append({'owner':owner,'axis':explicit or nearby,'text':raw,'relations':relations})
        else:
            for q in quantities:
                axis=_AXES.get(str(q.get('axis_hint') or '').lower(),'') or explicit or nearby
                if not field and len(quantities)>1 and not q.get('axis_hint'):
                    axis='unbound dimension order; label each axis'
                result.append({'owner':owner,'axis':axis,'text':q['text'],'relations':relations})
    return result


def bind_copy_quantity_claims(fields: dict[str,str], facts: dict[str, Any], *, category: str) -> dict:
    """Bind actual high-risk output spans to facts, never model-claimed IDs.

    Sale counts have a typed per-package contract. Other distributive component
    claims may only preserve a complete structured source statement; unsupported
    paraphrases stay explicit issues rather than acquiring an invented owner.
    Physical measurements remain with the existing measurement validator.
    """
    from products.generic_extractors import product_pack_counts
    words=dict(zip('one two three four five six seven eight nine ten eleven twelve'.split(),map(str,range(1,13))))
    def normalized(text):
        text=normalize_text(text).casefold()
        text=re.sub(r'\b('+'|'.join(words)+r')\b',lambda m:words[m[0]],text)
        return re.sub(r'\s+',' ',text).strip(' .;:')
    import hashlib,json
    evidence=[]
    def visit(value,depth=0,path='spec'):
        if depth>5:return
        if isinstance(value,dict):
            for key,item in value.items():
                if not str(key).startswith(('_','source')) and not any(k in str(key).lower() for k in ('description','bullet','review')):
                    visit(item,depth+1,path+'.'+str(key))
        elif isinstance(value,list):
            for index,item in enumerate(value):visit(item,depth+1,path+'.'+str(index))
        elif isinstance(value,str):evidence.append((normalized(value),path,value))
    visit(facts)
    issues=[];bindings=[]
    facts_sha=hashlib.sha256(json.dumps(facts,sort_keys=True,default=str).encode()).hexdigest()
    for field,text in fields.items():
        offset=0
        for clause in re.split(r'([;\n]|,(?!\d)|(?<!\d)[.!?](?!\d))',str(text)):
            start_offset=offset;offset+=len(clause)
            if not re.search(r'\b(?:each|every|per)\b',clause,re.I):continue
            value=normalized(clause.rsplit(':',1)[-1])
            quantifier=re.search(r'\b(?:each|every)\b',value)
            start=quantifier.end() if quantifier else 0
            counts=[m for m in re.finditer(r'\b\d+(?:\.\d+)?\b',value)
                if m.start()>=start and not re.match(r'\s*[- ]?\s*(?:["″]|(?:in(?:ch(?:es)?)?|ft|feet|foot|cm|mm|lbs?|pounds?|kg|oz|ounces?)\b)',value[m.end():])]
            if not counts:continue  # Physical measurements have their own property/owner checks.
            pack=bool(re.search(r'\b(?:each|every|per)\s+(?:package|pack|set|bundle)\b',value))
            sold=facts.get('sold_unit_count')
            base={'field':field,'span':[start_offset,offset],'text':clause,'facts_sha256':facts_sha}
            if pack and len(counts)==1 and str(sold).isdigit() and int(sold)>0 and product_pack_counts(value,title=category.replace('_',' '))=={int(sold)}:
                bindings.append({**base,'fact_id':'spec.sold_unit_count','owner':'sale_package',
                    'property':'sold_unit_count','value':int(sold),'unit':'item','scope':'per_package'})
                continue
            matched=next(((path,raw) for statement,path,raw in evidence if value and value==statement),None)
            if matched:
                bindings.append({**base,'fact_id':matched[0],'owner':'source_statement','property':'quantified_statement',
                    'value':matched[1],'unit':'text','scope':'verbatim_only',
                    'source_sha256':hashlib.sha256(matched[1].encode()).hexdigest()})
                continue
            issues.append('unsupported quantity scope: '+clause.strip())
    return {'schema':'copy-quantity-bindings-v1','bindings':bindings,'issues':list(dict.fromkeys(issues))}


def copy_measurement_issues(fields: list[str], facts: dict[str,Any]) -> list[str]:
    known=[]
    def visit(value,context='',depth=0):
        if depth>5:return
        if isinstance(value,dict):
            for key,item in value.items():
                name=str(key).lower()
                if name.startswith('_') or name.endswith('_unit') or any(term in name for term in ('source','description','bullet','review')):continue
                label=(context+' '+name.replace('_',' ')).strip()
                if isinstance(item,(dict,list)):visit(item,label,depth+1);continue
                if item is None or isinstance(item,bool):continue
                unit=value.get(str(key)+'_unit')
                raw=str(item) if extract_measurements(item) or not unit else f'{item} {unit}'
                if re.search(r'\b(?:size|dimensions?|length|width|height|depth|thickness|diameter|clearance|spacing|distance|gap)\b',label):
                    known.extend(_records(raw,field=label))
        elif isinstance(value,list):
            for item in value:visit({'value':item},context,depth+1)
    visit(facts)
    issues=[]
    for field in fields:
        for claim in _records(field):
            valid=[k for k in known if k['owner']==claim['owner'] and (not claim['axis'] or claim['axis']==k['axis'])
                   and k['relations']==claim['relations'] and measurement_values_match(k['text'],claim['text'])]
            if not valid:issues.append(f"unsupported measurement ({claim['owner']}/{claim['axis'] or 'unspecified axis'}): {claim['text']}")
    return list(dict.fromkeys(issues))

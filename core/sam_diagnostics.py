"""Non-semantic SAM process diagnostics and narrowly owned computation identity."""
from __future__ import annotations
import ast,json,os,subprocess,time
from pathlib import Path
from .io import write_json,utc_now
from .status import input_revision_id


class _WithoutStages(ast.NodeTransformer):
    def visit_Expr(self,node):
        call=node.value
        if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='_stage':return None
        return self.generic_visit(node)


def geometry_revision(region_path,worker_path):
    """Hash algorithm AST, not logger/process-launcher bytes or Python formatting."""
    region=ast.parse(Path(region_path).read_text(encoding='utf-8'))
    transport={'__init__','close','_backend','_receive','_start','_infer'}
    body=[n for n in region.body if isinstance(n,ast.FunctionDef) and n.name!='region_runtime_binding']
    owner=next(n for n in region.body if isinstance(n,ast.ClassDef) and n.name=='ProductRegions')
    body.extend(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name not in transport)
    worker=ast.parse(Path(worker_path).read_text(encoding='utf-8'))
    main=next(n for n in worker.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    # The inference context contains model loading, exact epsilons, crop/point
    # transforms, encoding, thresholds, ownership, original-size projection.
    work=[n for n in ast.walk(main) if isinstance(n,ast.With) and any(
        isinstance(i.context_expr,ast.Call) and isinstance(i.context_expr.func,ast.Attribute)
        and i.context_expr.func.attr=='inference_mode' for i in n.items)]
    if len(work)!=1:raise ValueError('SAM computation ownership changed; update its explicit identity contract')
    options=[n for n in main.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='argv' for t in n.targets)]
    tree=_WithoutStages().visit(ast.Module(body=[*body,*options,*work],type_ignores=[]))
    return input_revision_id(ast.dump(tree,include_attributes=False))


def worker_status(directory,stage,**fields):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    row={'at':utc_now(),'stage':stage,**fields}
    with (directory/'worker_events.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    write_json(directory/'worker_status.json',row)


def terminate_tree(process):
    """Kill the owned launcher AND its interpreter, not just the tiny venv shim."""
    if process.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10,check=False)
    if process.poll() is None:process.kill()
    process.wait(timeout=5)

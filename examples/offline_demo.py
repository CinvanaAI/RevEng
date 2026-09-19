"""Run the real static workflow on a tiny included Python repository."""
from __future__ import annotations
import argparse,json,os,tempfile
from pathlib import Path


def demonstrate(out):
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ['REVENG_DB']=str(out/'demo-state.db')
    from reveng.storage.system_db import ensure_system_db_ready
    from reveng.coordination.host_composition import build_default_host
    from reveng.framework.permissions import trusted_local_capability_check
    from reveng.analysis_engine.workflows.repo_analysis import WORKFLOW_ID
    ensure_system_db_ready(Path(os.environ['REVENG_DB']))
    source=Path(__file__).resolve().parent/'tiny_repository'
    result=build_default_host().run_workflow(WORKFLOW_ID,inputs={'repo_path':str(source)},output_dir=out,run_id='synthetic-first-analysis',permission_check=trusted_local_capability_check)
    from reveng.storage.db_connection import close_db_connections
    close_db_connections()
    return {'mode':'Actual static analysis; included synthetic source','file_count':result.outputs['file_count'],'source_files':sorted(x.name for x in source.glob('*.py')),'artifacts':{k:str(Path(v).relative_to(out)) for k,v in result.outputs.items() if k.endswith('_path') and isinstance(v,str) and Path(v).is_relative_to(out)},'model_calls':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path);args=parser.parse_args()
    if args.out:print(json.dumps(demonstrate(args.out),indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix='reveng-demo-') as scratch:print(json.dumps(demonstrate(Path(scratch)/'analysis'),indent=2))

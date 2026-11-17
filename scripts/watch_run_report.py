"""One batch's read-only report worker. Exits when that batch terminates."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.audit_run import audit
from workfactory.reporting.batch import report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root.resolve()
    while True:
        pricing=root/'pricing.json'
        audit(root,json.loads(pricing.read_text()) if pricing.exists() else None)
        states=[json.loads(s.read_text()) for s in root.glob('*/*/status.json') if (s.parent/'seed.json').exists()]
        expected=sum(len(json.loads(p.read_text())) for p in root.glob('*/seeds.json'))
        if len(states)==expected and states and all(x.get('state') in ('candidate_complete','needs_review','error') for x in states):
            for p in root.glob('*/status.json'):
                status=json.loads(p.read_text());tasks={s.parent.name:json.loads(s.read_text()) for s in p.parent.glob('*/status.json') if (s.parent/'seed.json').exists()}
                completed=sum(x.get('state')=='candidate_complete' for x in tasks.values())
                status.update(state='candidates_complete' if completed==len(tasks) else 'needs_review',completed=completed,tasks=tasks)
                from datetime import datetime,timezone
                status['updated_at']=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                p.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
            report(root);audit(root,json.loads(pricing.read_text()) if pricing.exists() else None);break
        time.sleep(30)

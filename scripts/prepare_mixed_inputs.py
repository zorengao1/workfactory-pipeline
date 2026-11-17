"""Build occupation-anchored candidates using the entire current skills pool."""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workfactory.core.contracts import ROOT
from workfactory.models.client import save


def match_skills(occupation,skills,count=3):
    stop=set('the and for with that this from your you are have can use skill skills all will when into not as to of in a is be or on an by it at if'.split())
    def tokens(text):return Counter(t for t in re.findall(r'[a-z][a-z-]{2,}',text.lower()) if t not in stop)
    eligible=[s for s in skills if s.get('eligible_for_composition',True)]
    docs=[tokens(s['name']+' '+s['content']) for s in eligible];query=tokens(occupation)
    df=Counter(t for doc in docs for t in doc)
    def vector(doc):
        v={t:(1+math.log(n))*math.log(1+len(docs)/(1+df[t])) for t,n in doc.items()}
        norm=math.sqrt(sum(x*x for x in v.values())) or 1
        return {t:x/norm for t,x in v.items()}
    q=vector(query)
    ranked=sorted(zip(eligible,docs),key=lambda pair:sum(q.get(t,0)*v for t,v in vector(pair[1]).items()),reverse=True)
    selected=[];hashes=set()
    for skill,_ in ranked:
        if skill['sha256'] in hashes:continue
        hashes.add(skill['sha256']);selected.append(skill)
        if len(selected)==count:break
    if len(selected)!=count:raise ValueError('Insufficient distinct skill documents')
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--occupations',nargs='+',required=True,help='Exact O*NET codes such as 13-1151.00')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--skills',type=Path,default=ROOT/'data/source_pools/skills.json')
    a=p.parse_args();cases=json.loads((ROOT/'data/source_pools/cases.json').read_text());skills=json.loads(a.skills.read_text())
    result=[]
    for code in a.occupations:
        found=[c for c in cases if c['task_id']=='onet-'+code.replace('.','-')]
        if len(found)!=1:raise ValueError('Unknown occupation '+code)
        case=json.loads(json.dumps(found[0]));case['task_id']='mixed-'+code.replace('.','-')
        related=match_skills(case['source_materials'][0]['content'],skills)
        case['source_materials'] += [{'source_id':s['source_id'],'provenance':s['url']+'; '+s['representation'],
            'url':s['url'],'sha256':s['sha256'],'content':s['content'],'snapshot':s['source_snapshot']} for s in related]
        case['source_metadata'].update(mixed_inputs=['occupation','skills'],skills_pool_size=len(skills),
            skill_ids=[s['source_id'] for s in related],skill_selection='TF-IDF candidates over whole pool; model must validate actual applicability')
        case['constraints']['scope']+=' Use relevant skill documents alongside the occupational source. New source research will be frozen before intent synthesis. Design digitally executable professional work without physical site visits or unauthorized approvals.'
        result.append(case)
    a.output.parent.mkdir(parents=True,exist_ok=True);save(a.output,result)
    print('Mixed candidates',len(result),'skills considered',len(skills))


if __name__=='__main__':main()

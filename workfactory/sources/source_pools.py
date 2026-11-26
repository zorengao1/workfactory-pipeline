"""Fetch auditable occupation snapshots and build intent inputs for the four routes.

Only public documents are read. Skill instructions are data, never activated or run.
Missing sources fail explicitly; no alternative provider is selected automatically.
"""
import argparse
import copy
import csv
import hashlib
import json
import random
import shutil
import re
import urllib.request
import urllib.error
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from workfactory.paths import ROOT
DATA=ROOT/'data/source_pools'
ONET_FILES=('occupation_data','task_statements','essential_skills','transferable_skills','work_activities','content_model_reference')


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(path)


def fetch(url,path):
    path=Path(path)
    if path.exists():
        meta=path.with_suffix(path.suffix+'.source.json')
        if not meta.exists():raise ValueError('Cached source has no provenance '+str(path))
        info=json.loads(meta.read_text())
        if info['url']!=url or info['sha256']!=hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Cached source URL or hash changed '+str(path))
        return path.read_bytes()
    request=urllib.request.Request(url,headers={'User-Agent':'WorkFactory-SourceCollector/1.0'})
    with urllib.request.urlopen(request,timeout=120) as response:
        body=response.read();final=response.url
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
    save(path.with_suffix(path.suffix+'.source.json'),{'url':url,'resolved_url':final,
        'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)})
    return body


def rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:return list(csv.DictReader(handle))


def fetch_onet(version):
    folder=DATA/('onet-'+version)/'raw'
    base='https://www.onetcenter.org/dl_files/database/db_'+version.replace('.','_')+'_csv/'
    def one(name):fetch(base+name+'.csv',folder/(name+'.csv'))
    with ThreadPoolExecutor(4) as pool:list(pool.map(one,ONET_FILES))
    occupations=rows(folder/'occupation_data.csv');tasks=defaultdict(list);ratings=defaultdict(list)
    for row in rows(folder/'task_statements.csv'):
        tasks[row['O*NET-SOC Code']].append({'id':row['Task ID'],'text':row['Task'],'type':row['Task Type']})
    definitions={r['Element ID']:r['Description'] for r in rows(folder/'content_model_reference.csv')}
    for name in ('essential_skills','transferable_skills','work_activities'):
        for row in rows(folder/(name+'.csv')):
            if row['Scale ID']!='IM' or row['Recommend Suppress']=='Y':continue
            ratings[row['O*NET-SOC Code']].append({'category':name,'id':row['Element ID'],
                'name':row['Element Name'],'definition':definitions.get(row['Element ID'],''),
                'importance':float(row['Data Value'])})
    result=[]
    for row in occupations:
        code=row['O*NET-SOC Code'];soc=code.split('.')[0]
        result.append({'source_id':'onet-'+version+'-'+code,'version':version,'onet_code':code,
            'soc_code':soc,'soc_major':soc[:2]+'-0000','title':row['Title'],'description':row['Description'],
            'tasks':tasks[code],'skills_and_activities':sorted(ratings[code],key=lambda r:(-r['importance'],r['id'])),
            'url':'https://www.onetonline.org/link/summary/'+code,
            'attribution':'O*NET '+version+' Database, U.S. Department of Labor, Employment and Training Administration; CC BY 4.0',
            'license_url':'https://www.onetcenter.org/license_db.html','source_snapshot':str(folder.relative_to(ROOT))})
    save(DATA/'occupations.json',result)
    return result


SOC_URL='https://www.bls.gov/soc/2018/major_groups.htm'


class SOCParser(HTMLParser):
    def __init__(self):
        super().__init__();self.stack=[];self.records={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='li':
            parent=None
            if self.stack:
                match=re.match(r'\s*(\d{2}-\d{4})', ''.join(self.stack[-1]['title']))
                if match:parent=match.group(1)
            self.stack.append({'title':[],'description':[],'mode':'title','parent_code':parent})
        elif self.stack and tag=='ul':self.stack[-1]['mode']='ignore'
        elif self.stack and tag=='div' and 'answer' in attrs.get('class','').split():self.stack[-1]['mode']='description'
        elif self.stack and tag=='p' and self.stack[-1]['mode']=='description':self.stack[-1]['description'].append('\n')
    def handle_data(self,data):
        if self.stack and self.stack[-1]['mode']!='ignore':self.stack[-1][self.stack[-1]['mode']].append(data)
    def handle_endtag(self,tag):
        if tag!='li' or not self.stack:return
        record=self.stack.pop();text=' '.join(''.join(record['title']).split())
        match=re.match(r'^(\d{2}-\d{4})\s+(.+)$',text)
        if not match:return
        code,title=match.groups()
        self.records[code]={'code':code,'title':title,'description':''.join(record['description']).strip(),
            'parent_code':record['parent_code'] or (None if code.endswith('-0000') else code[:2]+'-0000'),
            'major_code':code[:2]+'-0000','url':SOC_URL}


def fetch_soc(import_html=None):
    path=DATA/'soc-2018/raw/major_groups.html'
    bundled=ROOT/'resources/soc-2018/major_groups.html'
    if not path.exists() and not import_html and bundled.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(bundled,path)
        shutil.copy2(bundled.with_suffix('.html.source.json'),path.with_suffix('.html.source.json'))
    if import_html:
        body=Path(import_html).read_bytes()
        # Chrome's saved-source comment preserves the exact original URL.
        if SOC_URL.encode() not in body or b'2018 Standard Occupational Classification' not in body:
            raise ValueError('HTML does not identify the exact BLS SOC source')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        save(path.with_suffix('.html.source.json'),{'url':SOC_URL,'resolved_url':SOC_URL,
            'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(body).hexdigest(),
            'bytes':len(body),'method':'Explicit import of browser-saved official HTML; direct script access received HTTP 403'})
    else:
        try:body=fetch(SOC_URL,path)
        except urllib.error.HTTPError as exc:
            if exc.code!=403:raise
            raise RuntimeError('BLS denied automated retrieval with HTTP 403. Open '+SOC_URL+
                ' in a normal browser, save HTML only, then run fetch-soc --import-html /path/major_groups.html. No alternate source is used.') from None
    parser=SOCParser();parser.feed(body.decode('utf-8-sig'));result=list(parser.records.values())
    majors=[r for r in result if r['code'].endswith('-0000')]
    details=[r for r in result if not r['code'].endswith('0')]
    if len(majors)!=23 or len(details)<800:raise ValueError('SOC source is incomplete or parser failed')
    save(DATA/'soc.json',result);return result


def balanced(items,seed):
    groups=defaultdict(list);rng=random.Random(seed)
    for item in items:groups[item['soc_major']].append(item)
    queues={k:deque(rng.sample(v,len(v))) for k,v in sorted(groups.items())}
    result=[]
    while any(queues.values()):
        for queue in queues.values():
            if queue:result.append(queue.popleft())
    return result


def occupation_filter(path,levels):
    """Two independent flags: digitizable gates every route, mixed_route gates skill recall."""
    path=Path(path)
    if not path.is_absolute():path=ROOT/path
    table={r['onet_code']:r for r in rows(path)}
    for r in table.values():
        if r['digitizable'] not in ('yes','limited','no') or r['mixed_route'] not in ('yes','no'):
            raise ValueError('Invalid occupation filter row '+r['onet_code'])
    return set(table),{code:{'digitizable':r['digitizable'],'digitizable_reason':r['digitizable_reason'],
                  'mixed_route':r['mixed_route']=='yes' and r['digitizable'] in levels,
                  'supplemental_search':r.get('supplemental_search','')}
            for code,r in table.items() if r['digitizable'] in levels}


SCOPES={
 'occupation':'Select a coherent professional work objective supported by the supplied occupational duties. Use a diverse subset of activities rather than forcing all duties into one task. The work must be executable digitally. Label synthetic business context and data. Choose file carriers according to information needs; no fixed formats or counts. Only attribute actual downloaded sources; do not invent retrieval.',
 'skill':'Analyze the supplied skill documents as reference data. Derive a work situation and objective from their purpose, applicability, prerequisites and operations. Combine skills only where one output genuinely supplies another input. Generate a digital professional task with meaningful deliverables. Mark synthesized context. Choose file formats by task needs.',
 'deliverable':'Use the supplied real deliverable as the cue. Analyze its likely use, audience, content and implied production process, then derive an intent to produce, update, review or compare such an artifact. Distinguish what the artifact shows from newly synthesized context. Do not hand the existing artifact to the solver as the finished answer. Choose file formats by task needs.'}


def build_cases(limit,skill_cases,seed,mixed_cases=0,filter_path=None,levels=('yes',),deliverable_cases=0,
                index_dir=None,deliverable_manifest=None):
    """Four routes: occupation, skill, deliverable, and mixed (occupation plus recalled skills plus a deliverable)."""
    occupations=json.loads((DATA/'occupations.json').read_text())
    allowed=None
    if filter_path:
        known,allowed=occupation_filter(filter_path,levels)
        unknown=[o['onet_code'] for o in occupations if o['onet_code'] not in known]
        if unknown:raise ValueError('Occupations missing from filter table '+', '.join(unknown[:5]))
        occupations=[o for o in occupations if o['onet_code'] in allowed]
    soc_path=DATA/'soc.json'
    if not soc_path.exists():raise ValueError('SOC snapshot missing; fetch-soc first')
    soc={x['code']:x for x in json.loads(soc_path.read_text())}
    selected=balanced(occupations,seed)
    if limit:selected=selected[:limit]
    base=[]
    for o in selected:
        spec={'occupation':o['title'],'description':o['description'],'tasks':o['tasks'],
              'skills_and_activities':o['skills_and_activities'],'soc_code':o['soc_code'],'onet_code':o['onet_code']}
        materials=[{'source_id':o['source_id'],'provenance':o['attribution']+'; '+o['url'],
                    'content':json.dumps(spec,ensure_ascii=False),'url':o['url'],'sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()}]
        matched=soc.get(o['soc_code']);major=soc.get(o['soc_major'])
        if matched:materials.append({'source_id':'soc-2018-'+matched['code'],'provenance':matched['url'],'content':json.dumps({'detailed_occupation':matched,'major_group':major},ensure_ascii=False)})
        base.append(({'task_id':'onet-'+o['onet_code'].replace('.','-'),'stage':'01a_occupation',
            'source_materials':materials,'source_metadata':{'soc_major':o['soc_major'],'onet_version':o['version'],'onet_code':o['onet_code'],'route':'occupation',
                **({'digitizable':allowed[o['onet_code']]['digitizable'],'supplemental_search':allowed[o['onet_code']]['supplemental_search']} if allowed else {})},
            'constraints':{'synthesis_allowed':True,'scope':SCOPES['occupation']}},o))
    def take(pool,count,what):
        if count>len(pool):raise ValueError('Only '+str(len(pool))+' occupations are available for '+what)
        return pool if count<0 else pool[:count]
    # Mixed route: the same occupation material, joined at run time by recalled skills and a real deliverable.
    if mixed_cases and not allowed:raise ValueError('Mixed cases need the occupation filter table')
    eligible=[x for x in base if allowed and allowed[x[1]['onet_code']]['mixed_route']]
    mixed=take(eligible,mixed_cases,'the mixed route')
    # Occupations in the mixed route stay in the occupation route; each source yields more than one task.
    result=[c for c,_ in base]
    occupation_count=len(result)
    for c,_ in mixed:
        m=copy.deepcopy(c);m['task_id']='mixed-'+c['task_id'][len('onet-'):];m['source_metadata']['route']='mixed'
        result.append(m)
    # Skill route: one anchor skill from the local index; related skills are recalled and composed at run time.
    if skill_cases:
        if not index_dir:raise ValueError('Skill cases need skill_index_dir')
        from workfactory.sources.skill_index import sample_anchors,read_documents,material
        folder=Path(index_dir) if Path(index_dir).is_absolute() else ROOT/index_dir
        anchors=sample_anchors(folder,skill_cases,seed);docs=read_documents(folder,anchors)
        for sid in anchors:
            d=material(docs[sid])
            result.append({'task_id':'skill-'+sid,'stage':'01b_skill',
                'source_materials':[{k:d[k] for k in ('source_id','provenance','url','sha256','content')}],
                'source_metadata':{'route':'skill','anchor_skill_id':sid,'skill_name':d['name']},
                'constraints':{'synthesis_allowed':True,'scope':SCOPES['skill']}})
    # Deliverable route: a real artifact is the only intent material. The occupation is a search cue, not a source.
    seeds=take(base,deliverable_cases,'the deliverable route')
    for c,o in seeds:
        cue={'occupation':o['title'],'description':o['description'],'typical_work':[t['text'] for t in o['tasks'][:6]]}
        result.append({'task_id':'deliverable-'+c['task_id'][len('onet-'):],'stage':'01c_deliverable','source_materials':[],
            'source_metadata':{'route':'deliverable','soc_major':o['soc_major'],'search_cue_onet_code':o['onet_code'],
                'deliverable_search':[{'source_id':'search-cue-'+o['onet_code'],'content':json.dumps(cue,ensure_ascii=False)}]},
            'constraints':{'synthesis_allowed':True,'scope':SCOPES['deliverable']}})
    listed=json.loads(Path(deliverable_manifest).read_text()) if deliverable_manifest else []
    for item in listed:
        if not str(item.get('url','')).startswith('https://'):raise ValueError('Deliverable manifest entries need a public HTTPS url')
        result.append({'task_id':'deliverable-url-'+hashlib.sha256(item['url'].encode()).hexdigest()[:12],'stage':'01c_deliverable','source_materials':[],
            'source_metadata':{'route':'deliverable','deliverable_url':item['url'],'deliverable_title':item.get('title',''),'publisher':item.get('publisher','')},
            'constraints':{'synthesis_allowed':True,'scope':SCOPES['deliverable']}})
    if not result:raise ValueError('No source-backed cases built')
    if len({c['task_id'] for c in result})!=len(result):raise ValueError('Duplicate task IDs built')
    save(DATA/'cases.json',result)
    routes=defaultdict(int);majors=defaultdict(int)
    for c in result:
        routes[c['source_metadata']['route']]+=1
        if c['source_metadata']['route']=='occupation':majors[c['source_metadata']['soc_major']]+=1
    report={'case_count':len(result),'cases_by_route':dict(routes),'occupation_cases':occupation_count,'mixed_cases':len(mixed),
        'mixed_eligible_occupations':len(eligible),'skill_cases':skill_cases,'deliverable_cases':len(seeds)+len(listed),
        'occupation_records_after_filter':len(occupations),'soc_records':len(soc),
        'occupation_task_statements':sum(len(o['tasks']) for o in occupations),
        'occupation_filter':str(filter_path) if filter_path else None,'digitizable_levels':list(levels),
        'skill_index':str(index_dir) if skill_cases else None,'selected_major_groups':dict(majors),'seed':seed,
        'sampling':'Round-robin SOC major groups over digitizable occupations; skill anchors round-robin over repositories in the local index; skills and deliverables are recalled and judged at run time. One case per occupation per route. Not paper frequency replication.',
        'pending':['Several distinct cases per occupation or anchor for larger batches','Shared deliverable cache across tasks']}
    save(DATA/'statistics.json',report);return report


def main():
    settings=json.loads((ROOT/'config/source-pools.json').read_text())
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('fetch-onet');a.add_argument('--version',default=settings['onet_version'])
    a=sub.add_parser('fetch-soc');a.add_argument('--import-html')
    a=sub.add_parser('build');a.add_argument('--occupations',type=int,default=settings['occupation_limit']);a.add_argument('--skill-cases',type=int,default=settings['skill_case_count']);a.add_argument('--seed',type=int,default=settings['sampling_seed'])
    a.add_argument('--mixed-cases',type=int,default=settings.get('mixed_case_count',0),help='Mixed-route cases; -1 for every eligible occupation')
    a.add_argument('--occupation-filter',default=settings.get('occupation_filter'));a.add_argument('--deliverable-cases',type=int,default=settings.get('deliverable_case_count',0),help='Deliverable-route cases; -1 for every selected occupation');a.add_argument('--deliverable-manifest',help='JSON list of {url,title,publisher} for known real deliverables');a.add_argument('--skill-index',default=settings.get('skill_index_dir'));a.add_argument('--digitizable',nargs='+',default=settings.get('digitizable_levels',['yes']),choices=['yes','limited'])
    args=p.parse_args()
    if args.action=='fetch-onet':print('Occupation records',len(fetch_onet(args.version)))
    elif args.action=='fetch-soc':print('SOC records',len(fetch_soc(args.import_html)))
    else:print(json.dumps(build_cases(args.occupations,args.skill_cases,args.seed,args.mixed_cases,args.occupation_filter,tuple(args.digitizable),args.deliverable_cases,args.skill_index,args.deliverable_manifest),indent=2))


if __name__=='__main__':main()

"""Fetch auditable source snapshots and build occupation/skill intent inputs.

Only public documents are read. Skill instructions are data, never installed or run.
Missing sources fail explicitly; no alternative provider is selected automatically.
"""
import argparse
import csv
import hashlib
import html
import json
import random
import shutil
import math
from collections import Counter
import re
import urllib.request
import urllib.error
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT=Path(__file__).resolve().parent
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


class SkillText(HTMLParser):
    def __init__(self):
        super().__init__();self.seen_marker=False;self.depth=0;self.capture=False;self.text=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.capture and tag=='div':self.depth+=1
        elif self.seen_marker and tag=='div' and 'prose' in attrs.get('class','').split():
            self.capture=True;self.depth=1;self.seen_marker=False
        if self.capture and tag in {'p','li','h1','h2','h3','pre','br','tr'}:self.text.append('\n')
    def handle_endtag(self,tag):
        if self.capture and tag=='div':
            self.depth-=1
            if self.depth==0:self.capture=False
    def handle_data(self,data):
        if data.strip()=='SKILL.md' and not self.text:self.seen_marker=True
        elif self.capture:self.text.append(data)


def skill_links(body):
    return list(dict.fromkeys(html.unescape(x) for x in re.findall(r'href=["\']([^"\']+)',body)
        if re.fullmatch(r'/[^/?]+/[^/?]+/[^/?]+',x) and not x.startswith('/site/')))


def fetch_skills(limit,per_repo):
    snapshot=DATA/'skills-sh/raw'
    catalogs=json.loads((ROOT/'config/source-pools.json').read_text())['skills_catalogs']
    links=[]
    for url in catalogs:
        name='index' if url.rstrip('/')=='https://www.skills.sh' else 'catalog-'+url.rstrip('/').rsplit('/',1)[-1]
        links.extend(skill_links(fetch(url,snapshot/(name+'.html')).decode()))
    repositories=defaultdict(list)
    for link in dict.fromkeys(links):repositories['/'.join(link.split('/')[1:3])].append(link)
    selected=[]
    for index in range(per_repo):
        for entries in repositories.values():
            if index<len(entries):selected.append(entries[index])
            if len(selected)>=limit:break
        if len(selected)>=limit:break
    if not selected:raise ValueError('No skill entries discovered in skills.sh directory')
    def one(link):
        parts=link.strip('/').split('/');slug='__'.join(parts)
        body=fetch('https://www.skills.sh'+link,snapshot/(slug+'.html')).decode()
        parser=SkillText();parser.feed(body);text=''.join(parser.text).strip()
        if not text:raise ValueError('No rendered SKILL.md body '+link)
        github=list(dict.fromkeys(re.findall(r'href="(https://github.com/[^"?#]+)',body)))
        return {'source_id':'skills-sh-'+slug,'name':parts[-1],'repository':'/'.join(parts[:2]),
            'url':'https://www.skills.sh'+link,'repository_url':github[0] if github else None,
            'content':text,'eligible_for_composition':len(text)>=300,'sha256':hashlib.sha256(text.encode()).hexdigest(),
            'source_snapshot':str((snapshot/(slug+'.html')).relative_to(ROOT)),
            'representation':'Rendered SKILL.md documentation from skills.sh, not an installed skill',
            'license':'Upstream license not inferred; consult original repository'}
    # Stop on missing docs rather than replace them with descriptions or synthetic skills.
    with ThreadPoolExecutor(4) as pool:result=list(pool.map(one,selected))
    save(DATA/'skills.json',result)
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
            'parent_code':record['parent_code'],'major_code':code[:2]+'-0000','url':SOC_URL}


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


def related_skill_bundles(skills,limit,seed):
    skills=[s for s in skills if s.get('eligible_for_composition',True)]
    if len(skills)<2:raise ValueError('At least two substantial skill documents are required')
    stop=set('the and for with that this from your you are have can use skill skills all will when into not as to of in a is be or on an by it at if'.split())
    tokens=[Counter(t for t in re.findall(r'[a-z][a-z-]{2,}',s['name']+' '+s['content'].lower()) if t not in stop) for s in skills]
    df=Counter(t for doc in tokens for t in doc)
    vectors=[]
    for doc in tokens:
        vector={t:(1+math.log(n))*math.log(1+len(skills)/(1+df[t])) for t,n in doc.items()}
        norm=math.sqrt(sum(v*v for v in vector.values())) or 1
        vectors.append({t:v/norm for t,v in vector.items()})
    order=list(range(len(skills)));random.Random(seed).shuffle(order)
    bundles=[]
    for i in order[:limit]:
        def score(j):return sum(v*vectors[j].get(t,0) for t,v in vectors[i].items())
        neighbors=sorted((j for j in range(len(skills)) if j!=i),key=score,reverse=True)[:2]
        bundles.append([skills[j] for j in [i,*neighbors]])
    return bundles


def build_cases(limit,skill_cases,seed):
    occupations=json.loads((DATA/'occupations.json').read_text());skills=json.loads((DATA/'skills.json').read_text())
    soc_path=DATA/'soc.json'
    if not soc_path.exists():raise ValueError('SOC snapshot missing; fetch-soc first')
    soc={x['code']:x for x in json.loads(soc_path.read_text())} if soc_path.exists() else {}
    result=[];selected=balanced(occupations,seed)
    if limit:selected=selected[:limit]
    for o in selected:
        spec={'occupation':o['title'],'description':o['description'],'tasks':o['tasks'],
              'skills_and_activities':o['skills_and_activities'],'soc_code':o['soc_code'],'onet_code':o['onet_code']}
        materials=[{'source_id':o['source_id'],'provenance':o['attribution']+'; '+o['url'],
                    'content':json.dumps(spec,ensure_ascii=False),'url':o['url'],'sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()}]
        if soc:
            matched=soc.get(o['soc_code']);major=soc.get(o['soc_major'])
            if matched:materials.append({'source_id':'soc-2018-'+matched['code'],'provenance':matched['url'],'content':json.dumps({'detailed_occupation':matched,'major_group':major},ensure_ascii=False)})
        result.append({'task_id':'onet-'+o['onet_code'].replace('.','-'),'stage':'01a_occupation',
            'source_materials':materials,'source_metadata':{'soc_major':o['soc_major'],'onet_version':o['version'],'route':'occupation'},
            'constraints':{'synthesis_allowed':True,'scope':'Select a coherent professional work objective supported by the supplied occupational duties. Use a diverse subset of activities rather than forcing all duties into one task. The work must be executable digitally. Label synthetic business context and data. Choose file carriers according to information needs; no fixed formats or counts. Do not claim web retrieval.'}})
    # Lexical retrieval proposes candidates; the LLM must verify actual I/O compatibility.
    bundles=related_skill_bundles(skills,skill_cases,seed)
    for i,bundle in enumerate(bundles):
        result.append({'task_id':f'skill-source-{i+1:04d}','stage':'01b_skill',
            'source_materials':[{'source_id':s['source_id'],'provenance':s['url']+'; '+s['representation'],
                'content':s['content'],'url':s['url'],'sha256':s['sha256']} for s in bundle],
            'source_metadata':{'route':'skill','skill_ids':[s['source_id'] for s in bundle]},
            'constraints':{'synthesis_allowed':True,'scope':'Analyze the supplied skill documents as reference data. Select skills with genuine input/output compatibility. Reject if they cannot form coherent professional work; do not invent a connection. Generate a digital professional task with meaningful deliverables. Mark synthesized context. Choose file formats by task needs.'}})
    if not result:raise ValueError('No source-backed cases built')
    save(DATA/'cases.json',result)
    majors=defaultdict(int)
    for c in result:
        if c['stage']=='01a_occupation':majors[c['source_metadata']['soc_major']]+=1
    report={'occupation_records':len(occupations),'onet_major_groups':len({o['soc_major'] for o in occupations}),
        'soc_records':len(soc),'soc_detailed_occupations':sum(not code.endswith('0') for code in soc),
        'occupation_task_statements':sum(len(o['tasks']) for o in occupations),
        'skill_repositories':len({s['repository'] for s in skills}),'skill_documents':len(skills),'skills_eligible_for_composition':sum(s.get('eligible_for_composition',True) for s in skills),'case_count':len(result),'occupation_cases':len(selected),
        'skill_cases':sum(c['stage']=='01b_skill' for c in result),'selected_major_groups':dict(majors),
        'seed':seed,'sampling':'Round-robin SOC major groups; TF-IDF related skill documents followed by LLM I/O compatibility validation. Not paper frequency replication.',
        'pending':['Real-deliverable source pool','Dynamic profession-context search agent','Learned semantic skill retrieval; current candidates use TF-IDF and LLM validation']}
    save(DATA/'statistics.json',report);return report


def main():
    settings=json.loads((ROOT/'config/source-pools.json').read_text())
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('fetch-onet');a.add_argument('--version',default=settings['onet_version'])
    a=sub.add_parser('fetch-skills');a.add_argument('--limit',type=int,default=settings['skills_limit']);a.add_argument('--per-repo',type=int,default=settings['skills_per_repository'])
    a=sub.add_parser('fetch-soc');a.add_argument('--import-html')
    a=sub.add_parser('build');a.add_argument('--occupations',type=int,default=settings['occupation_limit']);a.add_argument('--skill-cases',type=int,default=settings['skill_case_count']);a.add_argument('--seed',type=int,default=settings['sampling_seed'])
    args=p.parse_args()
    if args.action=='fetch-onet':print('Occupation records',len(fetch_onet(args.version)))
    elif args.action=='fetch-skills':print('Skill documents',len(fetch_skills(args.limit,args.per_repo)))
    elif args.action=='fetch-soc':print('SOC records',len(fetch_soc(args.import_html)))
    else:print(json.dumps(build_cases(args.occupations,args.skill_cases,args.seed),indent=2))


if __name__=='__main__':main()

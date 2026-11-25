"""Agent runtime with optional isolated Docker code execution.

Fixed document adapters execute trusted code on the controller. Model-supplied
commands run only inside disposable Docker containers with scoped mounts.
"""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from contracts import ROOT, STAGES, output_errors, render
from pilot import complete, save

def fn(name, description, fields, required):
    return {'type':'function','function':{'name':name,'description':description,
        'parameters':{'type':'object','properties':fields,'required':required,'additionalProperties':False}}}


S = {'type':'string'}
NUMBER_FORMATS={'General','@','0','0.0','0.00','0.000','0.0000','0.00000000','#,##0','#,##0.0','#,##0.00','#,##0.000','#,##0.0000','0%','0.0%','0.00%',
                'yyyy-mm-dd','yyyy-mm-dd hh:mm','yyyy-mm-dd hh:mm:ss'}
TOOLS = [
    fn('list_files', 'List visible files in this task directory.', {}, []),
    fn('read_text', 'Read a UTF-8 task text file.', {'path':S}, ['path']),
    fn('write_text', 'Write a UTF-8 task text file in the allowed writable area.', {'path':S,'text':S}, ['path','text']),
    fn('read_workbook', 'Open the actual XLSX and inspect sheets, cells and formula errors.', {'path':S}, ['path']),
    fn('create_workbook', 'Create or replace an XLSX. sheets_json is an array of sheet objects with name, rows (rectangular cell matrices), optional widths (Excel units), formulas [{cell,formula}], formats [{range,format}]. formats are numeric/date display codes only: General, @, 0, 0.0, 0.00, #,##0, #,##0.0, #,##0.00, 0%, 0.0%, 0.00%, yyyy-mm-dd, yyyy-mm-dd hh:mm, yyyy-mm-dd hh:mm:ss. Wrapping is automatic; wrap is not a number format. Dates use {"date":"YYYY-MM-DD"}. Headers in row 1. Use typed numbers and formulas for calculated quantities. Use readable column widths. The tool exports and creates previews; read_workbook must then reopen the saved output.', {'path':S,'sheets_json':S}, ['path','sheets_json']),
]
TOOLS[-1]['function']['description'] += ' Formula objects also support fill_down_to (e.g. cell F2, formula =D2*E2, fill_down_to F73) to fill a same-column range with adjusted references; do not enumerate repeated formulas. For large workbooks create a few sheets first, then use update_workbook to add remaining sheets in separate calls.'
TOOLS[-1]['function']['description'] += ' Additional supported numeric display formats: 0.000, 0.0000, 0.00000000, #,##0.000, #,##0.0000. Create referenced sheets before writing formulas referencing them.'
TOOLS.append(fn('update_workbook', 'Add or replace ONLY the sheets named in sheets_json in an existing XLSX; all other sheets remain intact. Same sheet schema as create_workbook. Each named sheet is replaced in full. Split large workbooks across calls. Formula entries may use fill_down_to, e.g. {cell:"F2",formula:"=D2*E2",fill_down_to:"F73"}. Reopen the saved workbook after all updates.', {'path':S,'sheets_json':S}, ['path','sheets_json']))
TOOLS.extend([
    fn('read_document','Read actual PDF pages, DOCX paragraphs/tables, or PPTX slide text. Does not substitute for visual review.',{'path':S},['path']),
    fn('create_document','Create PDF or DOCX. content_json is {title,sections:[{heading,paragraphs:[text],table:[[cell,...]]}]}. Actual file must be reopened and rendered.',{'path':S,'content_json':S},['path','content_json']),
    fn('create_presentation','Create editable PPTX. content_json is {slides:[{title,paragraphs:[text]}]}. Use concise content. Saved slide renders must be checked.',{'path':S,'content_json':S},['path','content_json']),
    fn('render_document','Render saved PDF, DOCX or PPTX into controller-side preview images. Returns preview metadata, not a visual correctness verdict.',{'path':S},['path']),
])
READ_TOOLS={'list_files','read_text','read_workbook','read_document','render_document'}
WRITE_TOOLS={'write_text','create_workbook','update_workbook','create_document','create_presentation'}


def inventory(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


class Broker:
    def __init__(self, root, logs, writable=(), runtime=None, sandbox=None):
        self.root = Path(root).resolve()
        self.logs = Path(logs).resolve()
        self.logs.mkdir(parents=True, exist_ok=True)
        self.writable = writable
        self.counter = 0
        self.runtime=runtime or {}
        self.sandbox=sandbox

    def executable(self,key):
        value=self.runtime.get(key) or os.environ.get('WORKFACTORY_'+key.upper())
        if not value:
            raise ValueError('Missing runtime configuration '+key+'; set an explicit executable path')
        return value

    def document(self,path,content=None):
        self.counter+=1
        folder=self.logs/f'document-{self.counter:03d}';folder.mkdir()
        spec={'operation':'inspect' if content is None else 'create','path':str(path),
              'content':content,'preview_dir':str(folder/'previews'),'runtime':self.runtime}
        save(folder/'spec.json',spec)
        script='presentation_tool.mjs' if content is not None and path.suffix=='.pptx' else 'document_tool.py'
        executable=self.executable('node' if script.endswith('.mjs') else 'python')
        process=subprocess.run([executable,str(ROOT/script),str(folder/'spec.json')],capture_output=True,text=True,timeout=240)
        (folder/'stderr.txt').write_text(process.stderr)
        if process.returncode:raise RuntimeError('Document operation failed '+process.stderr[-1500:])
        result=json.loads(process.stdout.strip().splitlines()[-1])
        result['path']=str(path.relative_to(self.root))
        return result

    def render_document(self,path):
        self.counter+=1
        folder=self.logs/f'render-{self.counter:03d}';folder.mkdir()
        env=os.environ.copy()
        if self.runtime.get('font_directories'):
            from xml.sax.saxutils import escape
            font_config=folder/'fonts.conf'
            font_config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'+''.join(
                '<dir>'+escape(str(p))+'</dir>' for p in self.runtime['font_directories'])+
                '<cachedir>'+escape(str(folder/'font-cache'))+'</cachedir></fontconfig>')
            env['FONTCONFIG_FILE']=str(font_config)
        if path.suffix=='.docx':
            command=[self.executable('python'),self.executable('docx_renderer'),str(path),'--output_dir',str(folder)]
        elif path.suffix=='.pdf':
            command=[self.executable('pdftoppm'),'-scale-to','1600','-png',str(path),str(folder/'page')]
        elif path.suffix=='.pptx':
            convert=[self.executable('soffice'),'-env:UserInstallation='+ (folder/'office-profile').as_uri(),
                     '--headless','--convert-to','pdf','--outdir',str(folder),str(path)]
            converted=subprocess.run(convert,capture_output=True,text=True,timeout=240,env=env)
            pdf=folder/(path.stem+'.pdf')
            if converted.returncode or not pdf.exists():
                raise RuntimeError('PPTX render conversion failed '+converted.stderr[-1200:])
            command=[self.executable('pdftoppm'),'-scale-to','1600','-png',str(pdf),str(folder/'slide')]
        else:raise ValueError('Unsupported render format')
        process=subprocess.run(command,capture_output=True,text=True,timeout=240,env=env)
        (folder/'stderr.txt').write_text(process.stderr)
        if process.returncode:raise RuntimeError('Render failed '+process.stderr[-1500:])
        return {'path':str(path.relative_to(self.root)),'preview_count':len(list(folder.glob('*.png'))),
                'visual_review':'pending; rendering success does not establish visual correctness'}

    def path(self, value, write=False):
        if value.startswith('/task/'):
            value = value[6:]
        if Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('path outside task directory')
        p = (self.root / value).resolve()
        if not p.is_relative_to(self.root) or p == self.root:
            raise ValueError('path outside task directory')
        if write and not any(value == prefix or value.startswith(prefix.rstrip('/') + '/')
                             or prefix == '.' for prefix in self.writable):
            raise ValueError('path is read-only')
        return p

    def workbook(self, path, sheets=None, update=False):
        path=Path(path).resolve()
        if not path.is_relative_to(self.root):raise ValueError('workbook path outside task directory')
        self.counter += 1
        folder = self.logs / f'workbook-{self.counter:03d}'
        folder.mkdir()
        spec = {'operation':'inspect' if sheets is None else ('update' if update else 'create'),
                'path':str(path),'preview_dir':str(folder/'previews')}
        if sheets is not None:
            if not isinstance(sheets,list) or not sheets:
                raise ValueError('need nonempty sheets')
            for sheet in sheets:
                rows = sheet.get('rows', [])
                if not rows or any(not isinstance(r,list) for r in rows):
                    raise ValueError('need nonempty matrix of rows')
                for f in sheet.get('formats',[]):
                    if f.get('format') not in NUMBER_FORMATS:
                        raise ValueError('unsupported numeric/date format '+str(f.get('format'))+'; wrapping is automatic, use documented numeric/date formats only')
            spec['sheets'] = sheets
        save(folder/'spec.json',spec)
        proc = subprocess.run([self.executable('node'), str(ROOT/'workbook_tool.mjs'),str(folder/'spec.json')],
            capture_output=True,text=True,timeout=180)
        (folder/'stdout.txt').write_text(proc.stdout)
        (folder/'stderr.txt').write_text(proc.stderr)
        if proc.returncode:
            raise RuntimeError('workbook tool failed: '+proc.stderr[-1800:])
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        # Absolute host paths remain in controller logs only.
        result['path'] = str(path.relative_to(self.root))
        return result

    def call(self, name, args):
        if name=='execute_command':
            if self.sandbox is None:raise ValueError('Docker execution is not configured')
            return self.sandbox.execute(args['command'])
        if name == 'list_files':
            return {'files':list(inventory(self.root))}
        p = self.path(args['path'],write=name in WRITE_TOOLS)
        if name in {'read_document','create_document','create_presentation'}:
            allowed={'.pdf','.docx','.pptx'} if name=='read_document' else ({'.pptx'} if name=='create_presentation' else {'.pdf','.docx'})
            if p.suffix not in allowed:raise ValueError('Unsupported document extension')
            return self.document(p,json.loads(args['content_json']) if name!='read_document' else None)
        if name=='render_document':return self.render_document(p)
        if name == 'read_text':
            if p.suffix not in {'.txt','.md','.json','.csv','.tsv','.html','.xml'}: raise ValueError('unsupported text extension')
            return {'path':args['path'],'text':p.read_text()}
        if name == 'write_text':
            if p.suffix not in {'.txt','.md','.json','.csv','.tsv','.html','.xml'}: raise ValueError('unsupported text extension')
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text(args['text'])
            return {'written':args['path'],'bytes':p.stat().st_size}
        if name in {'read_workbook','create_workbook','update_workbook'}:
            if p.suffix != '.xlsx': raise ValueError('expected .xlsx extension')
            return self.workbook(p,json.loads(args['sheets_json']) if name != 'read_workbook' else None,update=name=='update_workbook')
        raise ValueError('unknown tool')


def run_agent(stage, inputs, root, logs, config, writable=(), max_turns=18, resume_messages=None, reuse_resume_readbacks=True):
    from docker_runtime import DockerRuntime
    settings=dict(config.get('_POLICY',{}).get('sandbox',{}))
    settings.pop('construction_sources', None)
    if stage=='04_build' and config.get('_CONSTRUCTION_SOURCES'):
        settings['construction_sources']=config['_CONSTRUCTION_SOURCES']
    sandbox=DockerRuntime(root,writable,settings,logs) if settings.get('backend')=='docker' else None
    try:
        return _run_agent(stage,inputs,root,logs,config,writable,max_turns,resume_messages,reuse_resume_readbacks,sandbox)
    finally:
        if sandbox:sandbox.close()


def _run_agent(stage, inputs, root, logs, config, writable, max_turns, resume_messages, reuse_resume_readbacks, sandbox):
    config = {**config, 'NATIVE_WEB_SEARCH': '0'}
    logs = Path(logs); logs.mkdir(parents=True,exist_ok=False)
    broker = Broker(root, logs/'tools', writable,config.get('_POLICY',{}).get('runtime'),sandbox)
    messages = render(stage, inputs)
    messages[0]['content'] += '\n工具路径均以 /task 为根，使用相对路径。文件工具不提供外网、任意代码或宿主机目录。先读取实际文件。表格计算可通过公式执行。此执行器要求最终结果调用 submit_result 提交，参数就是上述 JSON 对象；不要用正文或代码围栏提交结果。submit_result 必须是该轮唯一调用。'
    if resume_messages is not None:
        messages=resume_messages
    available = TOOLS if writable else [t for t in TOOLS if t['function']['name'] in READ_TOOLS]
    if sandbox:
        available=[*[t for t in available if t['function']['name'] in {'list_files','read_text','write_text'}],fn('execute_command','Execute bash in a fresh isolated WorkFactory container. /task contains only visible task files. Inputs are read-only for solvers. Use installed Python and LibreOffice for arbitrary document operations. No network or credentials are present.',{'command':S},['command'])]
        messages[0]['content']+='\n可用 execute_command 在独立 Docker 内运行代码，支持多格式文件。只访问可见工作区。创建成果后重新打开实际文件检查。'
    available = [*available,fn('submit_result','Submit the final structured result and terminate this stage. Use after actual file operations and checks.',
        {'task_id':S,'status':{'type':'string','enum':['ok','blocked','rejected']},
         'result':{'anyOf':[STAGES[stage][0],{'type':'null'}]},
         'issues':{'type':'array','items':S}},['task_id','status','result','issues'])]
    save(logs/'inputs.json',inputs)
    save(logs/'initial_messages.json',messages)
    save(logs/'metadata.json',{'model':config['OPENAI_MODEL'],'stage':stage,'writable':writable,
        'isolation':'disposable Docker with read-only solver inputs' if sandbox else 'fixed file capability broker; no shell/code tool',
        'hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
          for name in ['tool_runtime.py','workbook_tool.mjs','document_tool.py','presentation_tool.mjs',
                       'docker_runtime.py','contracts.py',f'prompts/{stage}.txt']}})
    before = inventory(Path(root))
    reopened=set()
    if resume_messages is not None and reuse_resume_readbacks:
        pending={}
        for message in messages:
            if message['role']=='assistant':
                for call in message.get('tool_calls',[]):pending[call['id']]=call['function']
            if message['role']=='tool' and message.get('tool_call_id') in pending:
                function=pending[message['tool_call_id']]
                try:
                    args=json.loads(function['arguments']);result=json.loads(message['content'])
                    if function['name'] in WRITE_TOOLS | {'read_workbook','read_document','read_text'}:
                        relative=str(broker.path(args['path']).relative_to(broker.root))
                        if function['name'] in WRITE_TOOLS:reopened.discard(relative)
                        elif 'error' not in result:reopened.add(relative)
                except (ValueError,KeyError,TypeError):pass
    def finish(parsed):
        errors=output_errors(stage,parsed,inputs)
        after=inventory(Path(root))
        for p in before.keys() | after.keys():
            allowed=any(prefix=='.' or p==prefix or p.startswith(prefix.rstrip('/')+'/') for prefix in writable)
            if not allowed and before.get(p)!=after.get(p):errors.append('read-only input changed '+p)
        save(logs/'validation.json',{'pass':not errors,'errors':errors,'before':before,'after':after})
        save(logs/'parsed.json',parsed)
        return parsed if not errors else None
    for turn in range(max_turns):
        start = time.monotonic()
        max_tokens=int(config.get('MAX_OUTPUT_TOKENS',9000))
        save(logs/f'{turn:02d}-request.json',{'model':config['OPENAI_MODEL'],'messages':messages,'tools':available,'max_tokens':max_tokens})
        try:
            response = complete({**config,'_STREAM_LOG':str(logs/f'{turn:02d}-stream.jsonl')},messages,max_tokens,available)
        except Exception as exc:
            save(logs/'transport_error.json',{'error_type':type(exc).__name__,
                'message':str(exc).replace(config['OPENAI_API_KEY'],'[REDACTED]')})
            raise
        save(logs/f'{turn:02d}-response.json',response)
        choice = response['choices'][0]; msg = choice['message']
        messages.append(msg)
        calls = msg.get('tool_calls',[])
        print(json.dumps({'task_id':inputs['task_id'],'model':config['OPENAI_MODEL'],'stage':stage,'turn':turn,'elapsed':round(time.monotonic()-start,1),
            'tools':[c['function']['name'] for c in calls],'finish':choice.get('finish_reason')},ensure_ascii=False),flush=True)
        if choice.get('finish_reason') == 'length':
            save(logs/'validation.json',{'pass':False,'errors':['output truncated']}); return None
        if calls:
            for call in calls:
                try:
                    if call['function']['name']=='submit_result':
                        if len(calls)!=1:raise ValueError('submit_result must be the only call in its turn')
                        parsed=json.loads(call['function']['arguments'])
                        schema_errors=output_errors(stage,parsed,inputs)
                        if schema_errors:raise ValueError('Submission rejected by output contract: '+json.dumps(schema_errors,ensure_ascii=False))
                        if stage in {'04_build','09_teacher'} and parsed.get('status')=='ok':
                            submitted=parsed.get('result') or {}
                            files=submitted.get('deliverables',[]) if stage=='09_teacher' else [f['path'] for f in submitted.get('reference_files',[])]
                            needed={str(broker.path(p).relative_to(broker.root)) for p in files}
                            missing=sorted(needed-reopened)
                            if missing and not sandbox:raise ValueError('Saved files must be reopened successfully with the matching read tool before submission: '+', '.join(missing))
                        save(logs/'submission.json',{'method':'submit_result','turn':turn,'arguments':parsed})
                        return finish(parsed)
                    args=json.loads(call['function']['arguments'])
                    name=call['function']['name']
                    if name in WRITE_TOOLS:reopened.discard(str(broker.path(args['path']).relative_to(broker.root)))
                    result = broker.call(name,args)
                    if name in {'read_workbook','read_document','read_text'}:reopened.add(str(broker.path(args['path']).relative_to(broker.root)))
                except Exception as exc:
                    result = {'error':str(exc).replace(str(broker.root),'/task').replace(str(ROOT),'/controller')}
                # Preserve failed calls for later trace filtering.
                save(logs/f'{turn:02d}-tool-{call["id"]}.json',result)
                messages.append({'role':'tool','tool_call_id':call['id'],
                                 'content':json.dumps(result,ensure_ascii=False)})
            continue
        save(logs/'validation.json',{'pass':False,'errors':['Tool stages must finish with submit_result; prose cannot bypass submission gates'],
                                   'before':before,'after':inventory(Path(root))})
        save(logs/'parsed.json',None)
        return None
    save(logs/'validation.json',{'pass':False,'errors':['tool turn limit reached']})
    return None

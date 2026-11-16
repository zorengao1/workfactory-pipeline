"""Independent, disposable stage container; model credentials never enter it."""
import json
import subprocess
import uuid
from pathlib import Path


class DockerRuntime:
    def __init__(self,root,writable,settings,logs):
        self.root=Path(root).resolve();self.settings=settings;self.logs=Path(logs)
        self.name='workfactory-'+uuid.uuid4().hex
        self.started=False
        self.writable=tuple(writable)

    def start(self):
        if self.started:return
        command=['docker','run','-d','--name',self.name,'--label','pipeline=workfactory',
                 '--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                 '--pids-limit','256','--memory',self.settings.get('memory','2g'),
                 '--cpus',str(self.settings.get('cpus',1)),
                 '--mount',f'type=bind,src={self.root},dst=/task,readonly']
        for value in self.writable:
            if value=='.':raise ValueError('Writable root not allowed for solver')
            p=self.root/value
            if value=='REQUEST.txt':p.touch(exist_ok=True)
            else:p.mkdir(parents=True,exist_ok=True)
            command+=['--mount',f'type=bind,src={p},dst=/task/{value}']
        command+=[self.settings['image']]
        subprocess.run(command,capture_output=True,text=True,check=True)
        self.started=True

    def execute(self,command):
        self.start()
        try:
            p=subprocess.run(['docker','exec','--workdir','/task',self.name,'bash','-lc',command],
                capture_output=True,text=True,timeout=self.settings.get('command_timeout_seconds',120))
            return {'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
        except subprocess.TimeoutExpired:
            # Kill the container so no orphaned command can keep editing files.
            self.close()
            return {'error':'Command timeout; container stopped','exit_code':124}

    def close(self):
        if self.started:
            subprocess.run(['docker','rm','-f',self.name],capture_output=True)
            self.started=False

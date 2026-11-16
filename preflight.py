"""Fail explicitly on missing dependencies; never substitute execution backends."""
import subprocess
from pathlib import Path


def check_runtime(policy):
    sandbox=policy.get('sandbox',{})
    if sandbox.get('backend')=='docker':
        subprocess.run(['docker','image','inspect',sandbox['image']],capture_output=True,check=True)
    elif sandbox.get('backend')!='file_tools':
        raise ValueError('Choose docker or file_tools explicitly')
    runtime=policy.get('runtime',{})
    for name,path in runtime.items():
        if name in {'node','python','docx_renderer','soffice','pdftoppm','pdf_font_file'} and path and not Path(path).is_file():
            raise ValueError('Missing runtime resource '+name)
    if sandbox.get('backend')=='file_tools' and (not runtime.get('node') or not runtime.get('python')):
        raise ValueError('file_tools needs explicit node and python runtime paths')

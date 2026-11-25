"""Run independent same-model construction/teacher groups concurrently."""
import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODELS=('deepseek-v4.1-flash-1017','mimo-v2.6-flash','gpt-6.1-sol')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,help='External credential env file')
    parser.add_argument('--pipeline-config',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--models',nargs='+',choices=MODELS,default=list(MODELS[:2]))
    args=parser.parse_args()
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    def run(model):
        with (root/(model+'.log')).open('a') as log:
            result=subprocess.run([sys.executable,'-u','-m','workfactory.pipeline.batch_generate',
                '--config',str(Path(args.config).resolve()),'--pipeline-config',str(Path(args.pipeline_config).resolve()),
                '--output',str(root),'--model',model],stdout=log,stderr=subprocess.STDOUT)
        return model,result.returncode
    with ThreadPoolExecutor(len(args.models)) as pool:
        results=list(pool.map(run,args.models))
    for model,code in results:print(model,code)
    if any(code for _,code in results):raise SystemExit(1)


if __name__=='__main__':main()

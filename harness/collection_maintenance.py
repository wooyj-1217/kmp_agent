"""Explicit heavy collection maintenance; never called by lifecycle hooks."""
import argparse
import importlib.util
import json
from pathlib import Path


def load(name):
    spec=importlib.util.spec_from_file_location('maintenance_'+name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    probe=sub.add_parser('probe');probe.add_argument('source',type=Path)
    sub.add_parser('link');sub.add_parser('status')
    project=sub.add_parser('projects');project.add_argument('--session-id')
    args=parser.parse_args()
    if args.action=='probe': result=load('codex_sync').source_probe(args.source)
    elif args.action=='projects': result=load('projects').after_hook(args.root,args.session_id)
    else:
        logger=load('logging').Logger(args.root)
        result=({'linked':logger.resolve_interventions(),**logger.intervention_status()}
                if args.action=='link' else logger.status())
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()

"""Explicit QA exclusions and criterion links; no filename-based build exemptions."""
from pathlib import Path
import subprocess


def generated_paths(root,values,protected):
    root=Path(root).resolve()
    if not isinstance(values,list) or any(not isinstance(v,str) for v in values):
        raise ValueError('generated_paths must be explicit relative directory paths')
    protected=set(protected)
    # Tracked files remain product sources even when inside a declared output path.
    repo=subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'],capture_output=True,text=True)
    if repo.returncode==0 and Path(repo.stdout.strip()).resolve()==root:
        files=subprocess.run(['git','-C',str(root),'ls-files','-z'],capture_output=True,check=True).stdout
        protected.update(p.decode() for p in files.split(b'\0') if p)
    clean=[]
    for value in values:
        path=Path(value)
        if not value or path.is_absolute() or '..' in path.parts or path.as_posix()!=value or value=='.' or any(c in value for c in '*?[]'):
            raise ValueError('generated_paths must be canonical relative directories, not globs or root')
        if any(part in {'.git','.harness','.kmp-agent','.codex','.agents','qa-tools'} for part in path.parts):
            raise ValueError('private/control paths cannot be generated outputs')
        destination=root/path
        if not destination.resolve().is_relative_to(root) or any(p.is_symlink() for p in [destination,*destination.parents] if p.is_relative_to(root)):
            raise ValueError('generated path must not traverse symlinks')
        if destination.exists() and not destination.is_dir():raise ValueError('generated output must be a directory')
        if any(p==value or p.startswith(value+'/') for p in protected):
            raise ValueError('generated path overlaps tracked or declared product source/input/output: '+value)
        if value not in clean:clean.append(value)
    return clean


def repair_criteria(values,owner,criteria):
    if not isinstance(values,dict):raise ValueError('repair_criteria must map owner criterion IDs to QA criterion IDs')
    known_owner={c['id'] for c in (owner or {}).get('criteria',[])}
    known_qa={c['id'] for c in criteria}
    for key,ids in values.items():
        if key not in known_owner or not isinstance(ids,list) or not ids or any(not isinstance(q,str) for q in ids) or len(set(ids))!=len(ids) or not set(ids)<=known_qa:
            raise ValueError('repair_criteria requires known owner and QA criterion IDs, no empty or duplicate links')
    return values

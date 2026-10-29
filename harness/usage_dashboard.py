"""Local approved flow UI + usage API. Collection uses only explicit registrations."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse
from harness.usage_projection import project


def handler(root, assets, catalog=None):
    root, assets = Path(root).resolve(), Path(assets).resolve()
    builtins = Path(__file__).with_name('dashboard_assets')
    sources = catalog or {'current': {'name': root.name, 'root': str(root)}}
    def select_source(params):
        from harness.usage_targets import registered_targets, valid_id
        values = params.get('project')
        if values is not None:
            if len(values) != 1 or values[0] not in sources:
                raise ValueError('unknown project catalog entry')
            key = values[0]
        else:
            matches = [key for key, value in sources.items() if Path(value['root']).resolve() == root]
            if len(matches) == 1:
                key = matches[0]
            elif len(sources) == 1:
                key = next(iter(sources))
            else:
                raise ValueError('project selection required')
        source = sources[key]; selected_root = Path(source['root']).resolve()
        identity, targets = registered_targets(selected_root)
        declared = source.get('project_id', identity)
        explicit = params.get('project_id')
        if explicit is not None and len(explicit) != 1:
            raise ValueError('ambiguous work target')
        target = explicit[0] if explicit is not None else declared
        if not valid_id(target) or target not in targets:
            raise ValueError('unknown or unconfirmed work target')
        return key, selected_root, target
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host', '').split(':')[0] not in {'127.0.0.1', 'localhost'}:
                self.send_error(403); return
            query = urlparse(self.path); params = parse_qs(query.query, keep_blank_values=True)
            route = query.path[len('/actual'):] if query.path.startswith('/actual/') else query.path
            download = False
            try:
                if route == '/api/artifact':
                    selected, source_root, target = select_source(params)
                    ledger = json.loads((source_root / '.harness/tasks/tasks.yaml').read_text())
                    task = ledger['tasks'][params['task'][0]]
                    if task.get('project_id') != target:
                        raise ValueError('artifact outside selected work target')
                    ref = task.get('outputs', [])[int(params['index'][0])]
                    path = (source_root / ref['path']).resolve()
                    if not path.is_relative_to(source_root) or not path.is_file():
                        self.send_error(404, 'artifact cannot be publicly retrieved'); return
                    body = path.read_bytes()
                    if hashlib.sha256(body).hexdigest() != ref.get('sha256'):
                        self.send_error(409, 'artifact differs from recorded evidence'); return
                    mime = 'application/octet-stream'; download = True
                elif route == '/api/projects':
                    from harness.usage_targets import registered_targets
                    body = json.dumps([{'id': key, 'name': value['name'], 'project_id': value.get('project_id', registered_targets(value['root'])[0])} for key, value in sources.items()], ensure_ascii=False).encode(); mime = 'application/json'
                elif route in {'/api/workspace', '/api/workspace-usage', '/api/usage-response', '/api/task-record'}:
                    from harness.dashboard_workspace import workspace, usage_slice, compact
                    selected, source_root, target = select_source(params)
                    data = workspace(source_root, project_id=target)
                    if route == '/api/task-record':
                        data = next(t for t in data['tasks'] if t['task_id'] == params.get('task', [None])[0])
                    elif route == '/api/usage-response':
                        data = next(r for r in data['usage']['rows'] if r['session_id'] == params.get('session', [None])[0] and r['response_id'] == params.get('response', [None])[0])
                    if route.endswith('-usage'):
                        request_id = params.get('request', [None])[0]
                        task_id = params.get('task', [None])[0]
                        execution_id = params.get('execution', [None])[0]
                        if execution_id is not None and not any(
                                execution_id == e['agent_run_id'] for t in data['tasks'] for e in t.get('executions', [])):
                            raise ValueError('execution outside selected work target')
                        ids = None
                        if request_id:
                            req = next((r for r in data['requests'] if r['id'] == request_id), None)
                            if req is None:
                                raise ValueError('unknown request')
                            ids = set(req['task_ids'])
                        if task_id:
                            if ids is not None and task_id not in ids:
                                raise ValueError('task outside request')
                            scoped = project(source_root, task_id, include_children=params.get('children', ['0'])[0]=='1', project_id=target)
                            data = usage_slice(scoped, execution_id=execution_id, start=params.get('start', [None])[0], end=params.get('end', [None])[0])
                        else:
                            data = usage_slice(data['usage'], ids, execution_id=execution_id, start=params.get('start', [None])[0], end=params.get('end', [None])[0])
                    if route == '/api/workspace':
                        data = compact(data)
                    body = json.dumps(data, ensure_ascii=False).encode(); mime = 'application/json'
                elif route in {'/workspace/', '/workspace/index.html'}:
                    body = (builtins / 'workspace.html').read_bytes(); mime = 'text/html'
                elif route in {'/workspace.js', '/workspace.css'}:
                    body = (builtins / route[1:]).read_bytes(); mime = 'text/javascript' if route.endswith('.js') else 'text/css'
                elif route == '/api/usage':
                    mode = params.get('mode', ['current'])[0]
                    if mode not in {'current', 'tasks'}:
                        raise ValueError('unknown view')
                    selected, source_root, target = select_source(params)
                    data = project(source_root, params.get('task', [None])[0], params.get('execution', [None])[0],
                                   mode, params.get('children', ['0'])[0] == '1', project_id=target)
                    body = json.dumps(data, ensure_ascii=False).encode(); mime = 'application/json'
                elif route in {'/usage-panel.js', '/usage-panel.css'}:
                    p = builtins / route[1:]; body = p.read_bytes()
                    mime = 'text/javascript' if p.suffix == '.js' else 'text/css'
                elif route in {'/', '/index.html'}:
                    html = (assets / 'index.html').read_text()
                    body = html.replace('</main>', '</main><link rel="stylesheet" href="/usage-panel.css"><script src="/usage-panel.js"></script>').encode()
                    mime = 'text/html'
                elif route in {'/app.js', '/data.json'}:
                    p = assets / route[1:]; body = p.read_bytes()
                    mime = 'text/javascript' if p.suffix == '.js' else 'application/json'
                elif query.path in {'/synthetic/', '/synthetic/index.html', '/synthetic/snapshot.json'}:
                    name = 'snapshot.json' if query.path.endswith('.json') else 'index.html'
                    body = (assets.parent / 'synthetic' / name).read_bytes()
                    mime = 'application/json' if name.endswith('.json') else 'text/html'
                else:
                    self.send_error(404); return
            except (OSError, ValueError, KeyError, TypeError, StopIteration, IndexError) as error:
                self.send_error(400, 'usage view unavailable: ' + type(error).__name__); return
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            if download:
                self.send_header('Content-Disposition', 'attachment; filename="recorded-artifact"')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


def serve(root, assets, port, catalog=None):
    root = Path(root).resolve()
    stop = threading.Event()
    def collect_registered():
        from harness.usage_collection import registrations, poll
        from harness.tasks import Tasks
        while not stop.wait(1):
            for source in [root] + [Path(v['root']) for v in (catalog or {}).values() if Path(v['root']).resolve()!=root]:
                entries = registrations(source)
                if entries:
                    try:
                        poll(Tasks(source, entries[0]['run_id']))
                    except (OSError, ValueError, KeyError):
                        continue
    thread = threading.Thread(target=collect_registered, daemon=True); thread.start()
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(root, assets, catalog))
    print('http://127.0.0.1:' + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set(); server.server_close(); thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--port', type=int, default=8795)
    parser.add_argument('--catalog', type=Path)
    args = parser.parse_args(); serve(args.root, args.assets, args.port, json.loads(args.catalog.read_text()) if args.catalog else None)


if __name__ == '__main__':main()

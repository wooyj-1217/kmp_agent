"""Model-free migration smoke check: serve all dashboard assets from an empty project.

Run from any checkout: rtk proxy python3 -B tools/check_dashboard_assets.py
No product records, database, model calls, or existing .harness state are used.
"""
from pathlib import Path
import sys,tempfile,threading,json,hashlib,subprocess,shutil
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
from harness.usage_dashboard import handler
assets=root/'harness/dashboard_assets'
with tempfile.TemporaryDirectory(prefix='agent-empty-dashboard-') as temp:
    state=Path(temp)
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(state,assets))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    process=subprocess.Popen(['rtk','proxy',sys.executable,'-B','-m','harness.dashboard','--root',str(state),'--port','0'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    dashboard_url=process.stdout.readline().strip()
    assert dashboard_url.startswith('http://127.0.0.1:'), 'Dashboard startup failed'
    services=[('dashboard',dashboard_url,['/','/app.js','/record-details.js','/usage.js','/style.css']),('workspace','http://127.0.0.1:'+str(server.server_port),['/workspace/','/workspace.js','/workspace.css','/usage-panel.js','/usage-panel.css'])]
    results=[]
    try:
        for service,url,routes in services:
            for route in routes:
                with urlopen(url+route,timeout=5) as response:
                    body=response.read();assert response.status==200 and body,route
                    results.append({'service':service,'route':route,'status':response.status,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()})
        assert not any(state.iterdir()), 'Static loading mutated empty project root'
    finally:
        server.shutdown();server.server_close();thread.join()
        process.terminate();process.communicate(timeout=10)
node=shutil.which('node');syntax=[]
if node:
    for path in sorted(assets.glob('*.js')):
        result=subprocess.run([node,'--check',str(path)],capture_output=True,text=True)
        assert result.returncode==0,(path.name,result.stderr)
        syntax.append(path.name)
output={'result':'PASS','data':'empty temporary root; no local trial logs or database','model_called':False,'real_browser':False,'http_assets':results,'node_syntax':syntax,'node_available':bool(node)}
print(json.dumps(output,ensure_ascii=False,indent=2))

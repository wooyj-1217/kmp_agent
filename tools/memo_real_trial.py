"""Isolated real model trial. Fixture infrastructure is not agent-authored implementation."""
import argparse,json,subprocess,shutil,os
from pathlib import Path
from harness.tasks import Tasks
from harness.logging import Logger
from harness.delegation import Development,manifest,digest,inside
from harness.delegation_runtime import run_codex,validate_result
from harness.qa import QA
NATIVE=os.environ.get('KMP_AGENT_CODEX') or shutil.which('codex') or 'codex'
GRADLE=os.environ.get('KMP_AGENT_GRADLE') or shutil.which('gradle') or 'gradle'
NODE=os.environ.get('KMP_AGENT_NODE') or shutil.which('node') or 'node'
def write(root,name,value):
 p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
def setup(root):
 if root.exists():raise ValueError('new isolated root required')
 root.mkdir(parents=True)
 write(root,'.kmp-agent/project.json',json.dumps({'project_id':root.name,'project_path':'..'}))
 write(root,'.gitignore','.harness/\n.kmp-agent/\n.worker-cache/\nqa-tools/\n.gradle/\n')
 write(root,'AGENTS.md','Isolated memo trial only. Prefix shell commands with rtk proxy. Never change the immutable original-request.md or build contracts. No commits, network deployment or unrelated edits. QA must write evidence only under qa-tools/. Build outputs must stay under .worker-cache/. To build use rtk proxy python3 tools/build.py TASKS. If sandbox blocks the build report NOT_RUN honestly; coordinator builds separately.\n')
 request="""# Isolated memo vertical slice, not demo_app v1
This is an authorized local validation project. No edits to installed harness, demo product or existing DB. Do not copy any existing user data.
REQ-01 A browser user can view saved memos, enter a memo, save it to a real Ktor server, then reload the list and see that memo with a generated ID and timestamp. In-memory server storage is sufficient ONLY for this trial; restart persistence and request idempotency are explicitly OUT OF SCOPE, not presumed verified.
REQ-02 Empty or Unicode-whitespace-only body and body longer than 200 Unicode code points are rejected, including direct API calls. Exactly 200 Unicode code points is valid. Preserve the exact accepted body, including surrounding whitespace, newlines and Korean/emoji, without truncation. Failed requests must not add memos. Server owns validation and also calls the KMP common validator; Web uses the JS version of the same validator.
REQ-03 Web displays initial loading, empty list, ready list, empty/invalid input, saving (disable duplicate action), success, error (retained body and explicit retry). It must not claim success until server confirms. List reload is explicit; unsaved body remains during failed save, ordinary reload need not restore unsaved drafts. Save failure retry is manual. Buttons labeled and keyboard usable, body counter aligned at input end, focus visible, no horizontal overflow at 360px. No back/navigation control is required in this single-screen trial.
REQ-04 Shared module contains real Kotlin common validation compiled for JVM and JS, used by real Server and Web. Web UI is browser JS for this isolated trial only, not a product platform decision. Server uses Ktor and JVM17. Android/iOS app entry points are not included: record NOT_RUN, never claim mobile PASS.
REQ-05 Successful save returns 201 memo object; GET /api/memos returns chronological oldest-first JSON array; empty/invalid POST returns 400. Preserve all records and exact text in GET. User-visible strings may be Korean or plain English consistently. No authentication or public exposure. Bind IPv4 loopback only on PORT; health /health returns200. The local server serves web/index.html, web/app.js and shared JS module output under /shared/; never serve project root or DB/log/config.
"""
 write(root,'original-request.md',request)
 write(root,'user-request.md',(Path(__file__).resolve().parents[1]/'docs/memo-real-trial-request.md').read_text())
 write(root,'input-provenance.md','user-request.md is a public synthetic trial specification, not private user text. original-request.md is an immutable controller-derived trial specification, not literal user text or approved demo policy.\n')
 write(root,'planning.md',request+'\nAcceptance IDs: AC-SHARED, AC-WEB, AC-SERVER, AC-E2E, AC-DESIGN, AC-BOUNDARY. All refer to REQ-01..05 above.\n')
 write(root,'api.md','# API v1 trial frozen\nGET /api/memos 200 array [{id:string,body:string,createdAt:ISO8601 string}], oldest-first. POST /api/memos {"body":string} ->201 same object. Invalid/missing/wrong type body ->400 JSON {"error":string}. POST success appends exactly one memo. GET /health 200. Server binds 127.0.0.1 PORT env default18790. Process memory only. UI and JS module served by same origin. Paths / index.html, /app.js, /shared/<exported module assets>. SHARED module API: package trial.memo, fun isValidMemo(body:String):Boolean, fun memoLength(body:String):Int; export both as @JsExport (opt-in as needed). Exports top-level package trial.memo in generated Kotlin JS plain module `memo-shared` exposed as globalThis[\'memo-shared\'].trial.memo; confirm generated output and adapt server/web if actual compiler differs, do not alter API policy. JS output browser script .worker-cache/build/shared/dist/js/productionLibrary/; use jsBrowserProductionLibraryDistribution task.\n')
 write(root,'policy.md','original-request.md is immutable. Only technical choices within this trial are delegated. No new persistence/idempotency/product policy. Input failures preserve editor; disable duplicate in-flight clicks; manual retry, no blind automatic retry. No mobile or visual PASS without execution/image review.\n')
 write(root,'architecture.md','Shared Kotlin common JVM+JS validation at shared/src/commonMain; native UI absent. Web browser JS at web uses actual compiled shared JS module global export. Server Ktor at server consumes shared JVM artifact. Root build configuration owned by coordinator; UI owner web; shared UI none. In-memory server repository, no DB. API exposes only explicitly allowed Web/static outputs.\n')
 write(root,'settings.gradle.kts','pluginManagement { repositories { gradlePluginPortal(); mavenCentral() } }\ndependencyResolutionManagement { repositories { mavenCentral() } }\nrootProject.name="memo-real-trial"\ninclude(":shared",":server")\n')
 write(root,'build.gradle.kts','plugins { kotlin("multiplatform") version "2.2.10" apply false; kotlin("jvm") version "2.2.10" apply false; kotlin("plugin.serialization") version "2.2.10" apply false }\nallprojects { layout.buildDirectory.set(rootProject.layout.projectDirectory.dir(".worker-cache/build/$name")) }\n')
 write(root,'gradle.properties','org.gradle.daemon=false\norg.gradle.workers.max=2\nkotlin.compiler.execution.strategy=in-process\norg.gradle.jvmargs=-Xmx1536m\n')
 write(root,'shared/build.gradle.kts','plugins { kotlin("multiplatform") }\nkotlin { jvm(); js(IR) { browser(); binaries.library(); useCommonJs() }; sourceSets { commonTest.dependencies { implementation(kotlin("test")) } } }\n')
 # Use UMD rather than commonjs so browser can load directly, compiler verifies output.
 write(root,'shared/build.gradle.kts','plugins { kotlin("multiplatform") }\nkotlin { jvm(); js(IR) { browser(); binaries.library(); compilerOptions { moduleKind.set(org.jetbrains.kotlin.gradle.dsl.JsModuleKind.MODULE_UMD) }; outputModuleName="memo-shared" }; sourceSets { commonTest.dependencies { implementation(kotlin("test")) } } }\n')
 write(root,'server/build.gradle.kts','plugins { kotlin("jvm"); kotlin("plugin.serialization"); application }\nkotlin { jvmToolchain(17) }\ndependencies {\n implementation(project(":shared"))\n implementation("io.ktor:ktor-server-core-jvm:3.2.3")\n implementation("io.ktor:ktor-server-cio-jvm:3.2.3")\n implementation("io.ktor:ktor-server-content-negotiation-jvm:3.2.3")\n implementation("io.ktor:ktor-serialization-kotlinx-json-jvm:3.2.3")\n implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")\n runtimeOnly("org.slf4j:slf4j-simple:2.0.17")\n testImplementation(kotlin("test"))\n}\napplication { mainClass.set("trial.memo.server.MainKt") }\n')
 for path in ['shared/src/commonMain/kotlin/trial/memo','shared/src/commonTest/kotlin/trial/memo','server/src/main/kotlin/trial/memo/server','web','design']: (root/path).mkdir(parents=True,exist_ok=True)
 write(root,'tools/build.py',"import os,subprocess,sys\nfrom pathlib import Path\nroot=Path(__file__).resolve().parents[1]\nenv=os.environ.copy();env.setdefault('GRADLE_RO_DEP_CACHE',str(Path.home()/'.gradle/caches'));env['GRADLE_USER_HOME']=str(root/'.worker-cache/gradle')\nraise SystemExit(subprocess.call(["+repr(GRADLE)+",'--no-daemon','--project-cache-dir',str(root/'.worker-cache/project'),*sys.argv[1:]],cwd=root,env=env))\n")
 for args in [('init','-q'),('config','user.name','Isolated Memo Trial'),('config','user.email','trial@example.invalid'),('add','.'),('commit','-qm','isolated infrastructure and immutable trial contracts')]:subprocess.run(['rtk','proxy','git',*args],cwd=root,check=True,capture_output=True)
 rid=Logger(root).start('HARNESS_BUILD','development','Actual isolated memo code development and independent QA; no demo changes')
 m=Tasks(root,rid);m.configure_runtime_limits(max_parallel=2,max_executions=18)
 write(root,'.harness/trial.json',json.dumps({'run_id':rid,'root':str(root),'native':NATIVE,'original_sha256':digest(root/'original-request.md')},indent=2))
 return rid

def manager(root):return Tasks(root,json.loads((root/'.harness/trial.json').read_text())['run_id'])
def author(root):
 m=manager(root);tid='DESIGN'
 m.register('MEMO-TRIAL',tid,'design','Memo trial design and interactive state specimen','One-screen design only, scoped design/ files',[{'id':'AC-DESIGN','required':True,'description':'REQ-03 complete states and accessible layout'}],['user-request.md','original-request.md','planning.md','api.md','policy.md','architecture.md'],max_attempts=2,work_type='HARNESS_BUILD',execution_scope='documentation',pipeline_stage='design')
 m.ready(tid);run=m.begin(tid,'design',execution_mode='independent_process');dev=Development(root,m.run_id);ws,out,before,_=dev.workspace(tid,run['agent_run_id'])
 packet={'task_id':tid,'parent_task_id':None,'goal':'Create an actual design artifact design/design.md and self-contained interactive HTML state specimen design/prototype.html for original-request.md. Cover normal/loading/empty/input-invalid/saving/success/error+manual retry, long content, keyboard and 360px. Include buttons to preview every state in prototype; use no CDN. No product implementation. Existing agreed policy must be preserved. Read source contracts, record requirement mapping. Only design/ may change. Return structured result.','inputs':run['inputs'],'allowed_paths':['design'],'verification_commands':[],'instructions':'All shell commands rtk proxy. Write real artifacts, not an implementation claim. Do not commit or modify original contracts. Independent QA reviews later.'}
 result=run_codex(m,tid,run['agent_run_id'],ws,packet,out/'process',NATIVE,600);claim=validate_result(result['result'])
 after=manifest(ws);changed=[p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)]
 if result['returncode'] or claim['status']!='COMPLETE' or set(changed)!=set(claim['changed_files']) or any(not inside(p,'design') for p in changed):raise ValueError('design author invocation/diff failed')
 for p in changed:(root/p).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ws/p,root/p)
 m.submit(tid,run['agent_run_id'],changed,'Actual independent design author submission, not approved; requires QA',design_status={'specification':'COMPLETE','mockup':'COMPLETE','visual_review':'NOT_RUN'})
 return result

def designqa(root):
 m=manager(root)
 m.register('MEMO-TRIAL','DESIGN-REPAIR','design','Address independent design QA findings','Only existing design outputs; original policy unchanged',[{'id':'AC-DESIGN','required':True,'description':'Independent QA confirms repaired states'}],['original-request.md','planning.md'],max_attempts=2,work_type='HARNESS_BUILD',execution_scope='documentation',pipeline_stage='design')
 q=QA(root,m.run_id);q.configure('QA-DESIGN','design','DESIGN',['user-request.md'],[
 {'id':'DQ-STATES','required':True,'description':'Directly inspect design/design.md and actual prototype. REQ-03 states and manual save retry preserve exact body; map contradictions/missing states, no invented policy. Write evidence under qa-tools.'},
 {'id':'DQ-LAYOUT','required':True,'description':'Inspect actual image design/capture.png if provided using image tools and HTML. Check 360px plan, labels, hierarchy, focus/counter; if no actual visual inspection mark NOT_RUN rather than pass. Evidence must identify inspected artifact and actual findings.'}],repair_task_id='DESIGN-REPAIR',max_attempts=2,executable=NATIVE,timeout=600)
 from harness.qa_repair import execute_with_owner
 return execute_with_owner(q,'QA-DESIGN')

def visualqa(root):
 m=manager(root);q=QA(root,m.run_id)
 q.configure('QA-DESIGN-IMAGE','design','DESIGN',['user-request.md'],[{'id':'DQ-ACTUAL-IMAGE','required':True,'kind':'visual','description':'Review the attached actual browser screenshots design/capture.png and capture-400.png visually against design/design.md and immutable request. Return evidence as actual PNG path, not markdown. Source inspection alone cannot establish visual PASS. The attempted 360px browser viewport measured 400px, so do NOT claim 360px verified. Explicitly distinguish actual image appearance from nonexecuted keyboard/full responsiveness. Review actual error state, text counter alignment, action hierarchy and readability.'}],max_attempts=1,executable=NATIVE,timeout=600,images=['design/capture.png','design/capture-400.png'])
 return q.execute('QA-DESIGN-IMAGE')

def configuredev(root,revision=''):
 m=manager(root);refs={'planning':'planning.md','design':'design/design.md','api':'api.md','policy':'policy.md'}
 parent='IMPLEMENT'+revision
 m.register('MEMO-TRIAL',parent,'development','Real memo shared/Web/Ktor implementation','Implement frozen memo trial without demo changes',[{'id':'AC-INTEGRATION','required':True,'description':'Actual compiled shared JVM+JS, Web JS syntax, Ktor API save and GET'}],list(refs.values())+['user-request.md','original-request.md','architecture.md'],max_attempts=3,work_type='HARNESS_BUILD',execution_scope='code_implementation',pipeline_stage='development')
 m.configure_development(parent,refs,['shared/src','web','server/src'],api_required=True,service_version='memo-trial-v1')
 children=[]
 tasks={'kmp':[':shared:jvmTest',':shared:jsBrowserProductionLibraryDistribution'],'server':[':server:test',':server:installDist']}
 for area,path in [('kmp','shared/src'),('web','web'),('server','server/src')]:
  command=['rtk','proxy','python3','tools/build.py',*tasks[area]] if area!='web' else ['rtk','proxy',NODE,'--check','web/app.js']
  goal={'kmp':'Implement REAL Kotlin common validation trial.memo.isValidMemo and memoLength, JVM+JS exports via @JsExport. Count Unicode code points not UTF16 units, reject Unicode whitespace-only, preserve accepted strings; add boundary and Unicode unit tests. Read immutable API contract and build output. No UI.', 'web':'Implement actual browser web/index.html, web/app.js and optional styles. Match design/design.md and prototype approved policy. Read original-request.md+api.md, use actual compiled shared validator via UMD global and /shared/<generatedfilename>. Provide accessible form, exact body, counter codepoints, initial GET+refresh, save 201 then GET, loading/saving/error retry states. No fixtures or fake success. Runtime common export inspection permitted, no root settings changes.', 'server':'Implement actual Ktor JVM app trial.memo.server.MainKt. Use shared Kotlin validator, JSON API exactly per api.md, process-memory thread-safe storage, UUID+Instant, chronological GET, exact body; wrong JSON body returns400 without insertion. Serve only explicit web files and compiled shared JS assets from configured build path, no project root. CORS unnecessary same origin. Environment PORT bind127.0.0.1. Real compile/API correctness required.'}[area]
  children.append({'task_id':'IMPL-'+area.upper()+revision,'area':area,'title':area+' memo implementation','goal':goal+' COMPLETE denotes implemented scoped code, not build verification: report verification NOT_RUN honestly if your sandbox blocks Gradle, but use COMPLETE when implementation is finished and contracts unchanged; coordinator owns independent build and can reject your code. Do not report overall quality PASS. Commands through rtk proxy. Root build settings owned by coordinator and immutable. If own sandbox prevents build, report NOT_RUN; coordinator runs independent actual commands.','requirement_ids':['REQ-01','REQ-02','REQ-03','REQ-04','REQ-05'],'acceptance_ids':['AC-'+area.upper()],'allowed_paths':[path],'dependencies':[] if area=='kmp' else ['IMPL-KMP'+revision],'verification_commands':[command],'out_of_scope':['root settings','original requirements','design edits','demo files','persistence','mobile UI','Git commits'],'max_attempts':3})
 commands=[['rtk','proxy','python3','tools/build.py',':shared:jvmTest',':shared:jsBrowserProductionLibraryDistribution',':server:test',':server:installDist'],['rtk','proxy',NODE,'--check','web/app.js']]
 Development(root,m.run_id).configure(parent,children,{'evidence':['architecture.md'],'modules':{'kmp':['shared/src'],'web':['web'],'server':['server/src']},'ui_owners':{'web':'web'}},{p:parent for p in ['build.gradle.kts','settings.gradle.kts','gradle.properties']},commands,max_parallel=2,executable=NATIVE,timeout=900)
 return Development(root,m.run_id).execute(parent)

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['setup','design','designqa','dev','retrydev','resume','visualqa']);p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root).resolve()
 result={'setup':setup,'design':author,'designqa':designqa,'dev':configuredev,'retrydev':lambda root:configuredev(root,'-R2'),'resume':lambda root:Development(root,manager(root).run_id).execute('IMPLEMENT-R2'),'visualqa':visualqa}[a.action](root)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

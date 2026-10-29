/* Execute the actual renderer with recorded-link fixtures. No browser/network/model. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
async function render(requests) {
  const nodes = new Map();
  const node = key => { if (!nodes.has(key)) nodes.set(key, {}); return nodes.get(key); };
  const data = {
    tasks: [{task_id:'T',project_id:'product',role:'development',title:'same title',state:'TODO',
      view:{verdict:'NOT_RUN',criteria:[]},executions:[],outputs:[],reviews:[]}],
    requests,activity:[],issues:[],assigned_children:[],active_task_ids:[],observed_active_task_ids:[],
    incremental_usage_execution_ids:[],unlinked_active_task_ids:[],
    usage:{rows:[],active_executions:[],taxonomy:{development:{}}},origin:'ACTUAL_RECORDED_RUN'
  };
  const context = {
    document:{hidden:false,querySelector:key=>key==='.canvas'?null:node(key),querySelectorAll:()=>[],addEventListener:()=>{}},
    window:{scrollY:0,scrollTo:()=>{},addEventListener:()=>{}},
    localStorage:{getItem:()=>JSON.stringify({menu:'history',project:'current',request:'',task:'T'}),setItem:()=>{}},
    fetch:async path=>({ok:true,json:async()=>path==='/api/projects'?[{id:'current',name:'fixture'}]:data}),
    requestAnimationFrame:f=>f(),setInterval:()=>{},URLSearchParams,CSS:{escape:x=>x}
  };
  vm.runInNewContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  return node('#content').innerHTML;
}
(async()=>{
  const missing='사용자 원문과 연결되지 않은 작업 기록입니다.';
  const requests=[{id:'R1',summary:'first actual request',task_ids:['T']}];
  const linked=await render(requests);
  assert.ok(linked.includes('연결된 원문 요청: first actual request'));
  assert.ok(!linked.includes(missing));
  const multiple=await render([...requests,{id:'R2',summary:'second actual request',task_ids:['T']}]);
  assert.ok(multiple.includes('first actual request · second actual request'));
  assert.ok(!multiple.includes(missing));
  assert.ok((await render([{id:'other',summary:'unrelated',task_ids:['OTHER']}])).includes(missing));
  console.log('request-not-selected, multiple linked requests, true missing-link: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});

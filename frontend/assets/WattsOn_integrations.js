const root='data/';
const groups=[
 ['cloud','Cloud & servers','Azure · AWS · GCP · Swiss hosting','#37649a','#eef4fc','<path d="M6 16a4 4 0 0 1-1-8 6 6 0 0 1 11-2 5 5 0 0 1 2 10zM7 20h10"/>',[
 ['azure_costs','Azure billing','Map tagged resource IDs and billing quantities to workload, owner and hosting region.'],
 ['aws_costs','AWS billing','Normalize ARNs, usage units and monthly currency before comparing test capacity.'],
 ['hoster_invoice','Swiss hoster invoices','Parse Swiss dates and CHF charges. Match GPU, storage and services to their resource owners.'],
 ['server_inventory','Server inventory','Check capacity, environment and criticality before resizing. Keep hot disaster recovery available.'],
 ['server_metrics_weekly','Server telemetry','Compare uptime to CPU and GPU activity to find idle compute.'],
 ['data_center_locations','Hosting regions','Separate active sites from the provider catalogue for location-based Scope 3.']]],
 ['ai','AI & agents','Gateway · subscriptions · agent runs','#7252a1','#f5effa','<rect x="5" y="5" width="14" height="14" rx="4"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3M9 12h6"/>',[
 ['ai_usage','AI gateway','Separate input, cached input and output tokens by model, task and department.'],
 ['ai_subscriptions','AI subscriptions','Compare purchased and active seats. Apply notice periods and final contract prices.'],
 ['ai_agent_runs','Agent activity','Link retries, tool calls and outcomes to gateway use. Avoid counting tokens twice.'],
 ['ai_invoice_monthly','AI supplier invoices','Reconcile monthly charges to model class, token counts and currency.']]],
 ['seats','Software licences','SaaS contracts · Microsoft 365','#257e73','#eaf6f1','<rect x="3" y="4" width="18" height="15" rx="3"/><path d="M3 9h18m-14 5h4"/>',[
 ['saas_contracts','SaaS agreements','Keep final contract versions and check renewal dates before reclaiming unused licences.'],
 ['m365_usage','Microsoft 365 activity','Use weekly active users and normalized storage to check seat demand.']]],
 ['platform','Data & analytics','Clusters · jobs · Power BI','#85651f','#fbf5e4','<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v13c0 4 16 4 16 0V5M4 11c0 4 16 4 16 0"/>',[
 ['data_platform_usage','Cluster activity','Compare node runtime against active hours by cluster and region.'],
 ['data_platform_jobs','Jobs & protection windows','Identify flexible work; preserve daily ETL, deadlines and closing windows.'],
 ['data_catalog_tables','Data catalogue','Compare table size and last read with retention requirements before archival.'],
 ['powerbi_usage','Power BI refreshes','Compare refresh count and duration with views; protect audit reporting.']]],
 ['ops','Engineering & storage','CI/CD · web · logs · backups','#965632','#fff1e7','<path d="m7 7-5 5 5 5m10-10 5 5-5 5m-4-14-2 18"/>',[
 ['ci_pipeline_runs','Build pipelines','Compare runner CPU hours, triggers, reruns and no-change builds.'],
 ['web_traffic','Web traffic','Interpret sampled requests, bot share and egress using the UTC timestamp.'],
 ['log_volume','Log storage','Normalize MB and GB and preserve required security and audit retention.'],
 ['backup_chains','Backup chains','Identify duplicate copies; check data class, restore tests and second-site requirements.']]],
 ['context','Finance & ownership','Exchange rates · teams · safeguards','#626c8b','#f0f2f8','<path d="M12 3 3 7l9 4 9-4zM6 10v7m6-5v5m6-7v7M3 20h18"/>',[
 ['exchange_rates','Monthly FX rates','Convert EUR and USD into CHF using the case’s ECB / Bundesbank monthly rates.'],
 ['mapping_departments_tools','Resource ownership','Map tools and resources to departments, cost centres and accountable roles.'],
 ['business_calendar','Basel calendar','Align schedules to workdays, public holidays and company closures.'],
 ['it_tickets','Tickets & guardrails','Surface exceptions, approvals, freezes and known capacity changes.'],
 ['provider_monthly_report','Provider summaries','Reconcile headline CHF totals to underlying billing lines.'],
 ['headcount','Department headcount','Allocate shared tools by each department’s share of average FTE.'],
 ['projects','Project directory','Match project IDs, owners, contract status and rechargeability.'],
 ['project_hours_monthly','Project hours','Cross-check allocation and rechargeability against recorded hours.']]]
];
const $=id=>document.getElementById(id);
const fmt=n=>n.toLocaleString('en-CH');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const byId=new Map(caseSources.map(s=>[s.id,s]));
$('sourceCount').textContent=fmt(byId.size);
const directory=new Map(groups.flatMap(g=>g[6].map(([id,title,purpose])=>[id,{...byId.get(id),title,purpose,group:g[1]}])));
const monthNames=new Intl.DateTimeFormat('en-GB',{month:'short',year:'numeric',timeZone:'UTC'});
const months=[...new Set(caseSources.flatMap(s=>Object.keys(s.months)))].filter(Boolean).sort().reverse();
for(const m of months)$('period').add(new Option(monthNames.format(new Date(m+'-01T00:00:00Z')),m));
$('dictionary').href=root+'data_dictionary.md';
let tier='all';
function recordCount(s){const month=$('period').value;return month?(s.months[month]||s.months['']||0):s.n}
function visible(g){
 const query=$('search').value.trim().toLowerCase();
 return g[6].map(([id])=>directory.get(id)).filter(s=>(tier==='all'||tier===(s.file.startsWith('extra/')?'bonus':'core'))&&recordCount(s)>0&&[s.title,s.file,s.group,s.purpose,g[2]].join(' ').toLowerCase().includes(query));
}
function render(){
 let total=0,count=0;
 $('groups').innerHTML=groups.map(g=>{
  const rows=visible(g);if(!rows.length)return '';
  count+=rows.length;total+=rows.reduce((v,r)=>v+recordCount(r),0);
  return '<button class="group" data-group="'+g[0]+'" style="--accent:'+g[3]+';--tint:'+g[4]+'"><span class="group-top"><i class="icon"><svg aria-hidden="true" viewBox="0 0 24 24">'+g[5]+'</svg></i>'+rows.length+' source'+(rows.length===1?'':'s')+'</span><b>'+g[1]+'</b><small>'+g[2]+'</small></button>';
 }).join('')||'<p class="empty">No matching sources. Try a filename or a different period.</p>';
 $('shown').textContent=count+' of 28 sources'+($('period').value?' · includes standing reference files':'');
 $('rowCount').textContent=fmt(total);
 document.querySelectorAll('[data-tier]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.tier===tier));
}
function show(kind,title,body){
 $('detailKind').textContent=kind;$('detailTitle').textContent=title;$('detailBody').innerHTML=body;
 if(!$('detail').open)$('detail').showModal();
}
function sourceLink(s){return '<a class="source-link" href="'+root+s.file+'" target="_blank" rel="noopener">Open '+esc(s.file.split('/').pop())+' ↗</a>'}
function sample(fields,values){
 return '<dl class="row-preview">'+fields.map((f,i)=>'<dt>'+esc(f)+'</dt><dd>'+esc(typeof values[i]==='object'&&values[i]!==null?JSON.stringify(values[i]):values[i]??'—')+'</dd>').join('')+'</dl>';
}
function showGroup(g){
 const rows=visible(g);
 show('Source library',g[1],rows.map(s=>{
  const keys=Object.keys(s.examples).sort(),month=$('period').value;
  const example=s.examples[month]||s.examples[keys[0]];
  return '<details class="file" '+(rows.length===1?'open':'')+'><summary>'+esc(s.title)+' <small>'+fmt(recordCount(s))+' records</small></summary><span class="file-title">'+(s.file.startsWith('extra/')?'Bonus':'Core')+' · '+esc(s.file)+(s.months['']?' · reference snapshot':'')+'</span><p>'+esc(s.purpose)+'</p><details><summary>Inspect one source record</summary>'+sample(s.fields,example)+'</details>'+sourceLink(s)+'</details>';
 }).join(''));
}
$('groups').onclick=e=>{const b=e.target.closest('[data-group]');if(b)showGroup(groups.find(g=>g[0]===b.dataset.group))};
document.querySelector('.pills').onclick=e=>{if(e.target.dataset.tier){tier=e.target.dataset.tier;render()}};
$('period').onchange=render;$('search').oninput=render;
const guideTopics=[
 ['Find idle compute','Compare Frankfurt development runtime with active hours, then match billed quantity to the Azure resource.',['data_platform_usage','azure_costs']],
 ['Check unused seats','Compare purchased seats with active users. Check contract status, notice periods and the accountable owner before renewal.',['ai_subscriptions','saas_contracts','m365_usage']],
 ['Protect production','Use job deadlines, the Basel calendar and IT tickets to separate flexible work from protected ETL and closing windows.',['data_platform_jobs','business_calendar','it_tickets']],
 ['Trace a carbon estimate','Start with hosting region and metered usage. Inspect the energy and grid factors in the Forecast evidence ledger.',['data_center_locations','azure_costs','data_platform_usage']]
];
function showGuide(index){
 const topic=guideTopics[index];
 show('Wattson · source guide','Which evidence do you need?','<div class="links">'+guideTopics.map(([label],i)=>'<button class="source-link" data-topic="'+i+'" aria-pressed="'+(i===index)+'">'+label+'</button>').join('')+'</div><p>'+topic[1]+'</p>'+topic[2].map(id=>sourceLink(directory.get(id))).join('')+(index===3?'<p><a href="forecast.html#library">Open factor ledger ↗</a></p>':''));
}
$('guide').onclick=()=>showGuide(0);
$('detailBody').onclick=e=>{const b=e.target.closest('[data-topic]');if(b){showGuide(Number(b.dataset.topic));$('detailBody').querySelector('[aria-pressed=true]').focus()}};
const reviews={
 inventory:['Dublin capacity mismatch','Head of IT','The test fleet is billed for 64 vCPUs. Inventory accounts for 52. Reconcile the 12-vCPU gap before changing fleet size. Keep hot disaster recovery and acceptance-test freezes protected.',['aws_costs','server_inventory','it_tickets']],
 billing:['March cloud discrepancy','Finance','The provider summary reports CHF 28,240 against CHF 23,532 in line items. Trace the CHF 4,708 difference to credits, adjustments or a corrected invoice before accepting the headline total.',['provider_monthly_report','azure_costs','aws_costs','hoster_invoice']]
};
document.querySelector('.review-grid').onclick=e=>{const b=e.target.closest('[data-review]');if(!b)return;const [title,owner,body,ids]=reviews[b.dataset.review];show('Human review · '+owner,title,'<p class="review-text">'+body+'</p><h3>Compare evidence</h3>'+ids.map(id=>sourceLink(directory.get(id))).join('')+'<p><a href="package.html#approvals">View package approvals ↗</a></p>')};
render();

// Validate a local copy without transmitting it or replacing the case baseline.
function inspectCsv(text,expected,delimiter=','){
 let field='',record=[],quoted=false,afterQuote=false,count=0,header,first;
 function finish(){
  record.push(field);field='';afterQuote=false;
  if(record.some(v=>v!=='')){
   if(!header){
    header=record;
    const missing=expected.filter(k=>!header.includes(k));
    if(missing.length)throw Error('Missing columns: '+missing.join(', '));
    if(new Set(header).size!==header.length)throw Error('Duplicate column names in the header.');
   }else{
    if(record.length!==header.length)throw Error('Record '+(count+1)+' has '+record.length+' fields; expected '+header.length+'.');
    count++;if(!first)first=record;
   }
  }
  record=[];
 }
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(quoted){
   if(c!=='"'){field+=c;continue}
   if(text[i+1]==='"'){field+='"';i++;continue}
   quoted=false;afterQuote=true;continue;
  }
  if(c===delimiter){record.push(field);field='';afterQuote=false}
  else if(c==='\n'||c==='\r'){if(c==='\r'&&text[i+1]==='\n')i++;finish()}
  else if(c==='"'&&!field&&!afterQuote)quoted=true;
  else if(afterQuote||c==='"')throw Error('Unexpected quote in record '+(count+1)+'.');
  else field+=c;
 }
 if(quoted)throw Error('The last quoted field is incomplete.');
 finish();
 if(!count)throw Error('No data records found.');
 return {fields:header,first,count};
}
function inspectJsonl(text,s){
 let count=0,first;
 const keys=s?.id==='ai_agent_runs'?['run_id','agent']:s?.id==='ci_pipeline_runs'?['pipeline','repo']:[];
 for(const [i,line] of text.split(/\r?\n/).entries()){
  if(!line.trim())continue;
  let r;try{r=JSON.parse(line)}catch{throw Error('Invalid JSON on line '+(i+1)+'.')}
  if(!r||Array.isArray(r)||typeof r!=='object'||keys.some(k=>!(k in r)))throw Error('Line '+(i+1)+' requires '+keys.join(' and ')+'.');
  count++;if(!first)first=r;
 }
 if(!count)throw Error('No data records found.');
 return {fields:Object.keys(first),first:Object.values(first),count};
}
$('checkExport').onclick=()=>$('upload').click();
$('upload').onchange=async e=>{
 const file=e.target.files[0];e.target.value='';if(!file)return;
 const s=[...directory.values()].find(r=>r.file.split('/').pop().toLowerCase()===file.name.toLowerCase());
 try{
  if(!s)throw Error('Choose one of the 28 listed case filenames so WattsOn can match its schema.');
  const data=(await file.text()).replace(/^\uFEFF/,'');
  const result=s.file.endsWith('.csv')?inspectCsv(data,s.fields):inspectJsonl(data,s);
  show('Local file check',s.title,'<p><b>'+fmt(result.count)+' readable records</b> · expected '+(s.file.endsWith('.csv')?'columns found':'record keys found')+'</p><p class="detail-note">Checked in this browser. Dashboard figures use the bundled case snapshot.</p><details><summary>Inspect first record</summary>'+sample(result.fields,result.first)+'</details>');
 }catch(err){show('Local file check','Export needs review','<p>'+esc(err.message)+'</p>')}
};


// Imported snapshots belong to this browser. Credentials are used only for a single read.
(() => {
 const dialog=$('connector'),body=$('connectorBody'),hosted=location.origin==='http://127.0.0.1:8768';
 const catalog=[...directory.values()],options={file:'Files',invoice:'Invoice files',aws:'AWS invoices',gcp:'GCP billing export',azure:'Azure costs',powerbi:'Power BI',databricks:'Databricks SQL',http:'HTTPS / OData',odbc:'ODBC database'};
 const definitions={
  aws:[['account','AWS account ID'],['report','CUR report name or S3 prefix'],['role','Read-only role ARN'],['externalId','External ID (optional)']],
  gcp:[['billing','Billing account ID'],['dataset','BigQuery export dataset'],['table','Billing export table'],['serviceAccount','Service account JSON','password']],
  azure:[['subscription','Subscription ID'],['token','Azure access token','password']],
  powerbi:[['dataset','Semantic model ID'],['table','Table name'],['token','Power BI access token','password']],
  databricks:[['url','Workspace HTTPS URL','url'],['warehouse','SQL warehouse ID'],['table','Catalog.schema.table'],['token','Workspace access token','password']],
  http:[['url','HTTPS endpoint','url'],['path','JSON record path (optional)'],['token','Bearer token (optional)','password'],['header','API key header (optional)'],['key','API key (optional)','password']],
  odbc:[['dsn','Windows ODBC data source name'],['table','Table or view'],['user','Database user (optional)'],['password','Database password (optional)','password']]
 };
 const database=new Promise((resolve,reject)=>{
  const open=indexedDB.open('wattson-imported-sources',1);
  open.onupgradeneeded=()=>open.result.createObjectStore('sources',{keyPath:'id'});
  open.onsuccess=()=>resolve(open.result);open.onerror=()=>reject(open.error);
 });
 let saved=[],pending=[],kind='file',revision=0,workbook=null;
 function field(label,input){return '<label class="src-field">'+label+input+'</label>'}
 function msg(message){const el=$('sourceStatus');if(el)el.textContent=message}
 function cancelPending(){revision++;pending=[];workbook=null}
 async function reload(){
  const db=await database;
  saved=await new Promise((resolve,reject)=>{const r=db.transaction('sources').objectStore('sources').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
  drawSaved();
 }
 function drawSaved(){
  $('personal').hidden=!saved.length;
  const q=$('search').value.toLowerCase();
  const a=saved.filter(x=>[x.name,x.group,x.filename].join(' ').toLowerCase().includes(q));
  $('personalList').innerHTML=a.map(x=>'<button data-saved="'+esc(x.id)+'"><small>'+esc(x.group)+'</small><b>'+esc(x.name)+'</b><span>'+fmt(x.count)+' rows · '+esc(x.filename)+'</span></button>').join('')||'<p>No matching imported sources.</p>';
 }
 $('search').addEventListener('input',drawSaved);
 $('personalList').onclick=e=>{
  const b=e.target.closest('[data-saved]');if(!b)return;
  const x=saved.find(s=>s.id===b.dataset.saved);
  show('My sources · '+x.group,x.name,'<p>'+fmt(x.count)+' '+(x.partial?'preview rows':'records')+' · '+esc(x.filename)+'</p><p class="detail-note">Added '+esc(new Date(x.when).toLocaleString())+'</p><details open><summary>First record</summary>'+sample(x.fields,x.first)+'</details><button class="source-link" id="getSnapshot">Download saved data ↓</button>');
  $('getSnapshot').onclick=()=>{const url=URL.createObjectURL(x.blob),link=document.createElement('a');link.href=url;link.download=x.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
 };
 function backendNote(){return '<p class="connector-note">Backend connector not present in this FastAPI app yet. This connector is mocked in-browser for now, so it will not leave the current app or call external cloud APIs.</p>'}
 function connectorControls(){
  const name=field('Source name','<input name="name" '+(hosted?'required ':'')+'placeholder="'+options[kind]+'">');
  const fields=(definitions[kind]||[]).map(([key,label,type])=>{
   const required=hosted&&!label.includes('optional')?'required':'';
   return field(label,'<input autocomplete="off" name="'+key+'" type="'+(type||'text')+'" '+required+'>');
  }).join('');
  const note=hosted?'Reads a snapshot of up to 5,000 rows. Credentials are used for this request only.':'Creates a mocked preview and saves it under My sources. Backend calculations keep using the bundled case snapshot.';
  return (!hosted?backendNote():'')+'<form id="remoteForm" autocomplete="off">'+name+fields+'<button class="primary" type="submit">Test &amp; preview</button><small>'+note+'</small></form>';
 }
 function view(){
  cancelPending();const types=Object.entries(options).map(([k,v])=>'<option value="'+k+'" '+(kind===k?'selected':'')+'>'+v+'</option>').join('');
  let controls;
  if(kind==='file'){
   controls='<div class="file-zone"><b>Import data sources together</b><small>CSV, JSON Lines, JSON, TSV'+(hosted?', Excel (.xlsx, .xlsm)':'')+' · AWS CUR and GCP billing CSV exports supported as files</small><input id="importFiles" aria-label="Choose source files" type="file" multiple accept=".csv,.tsv,.jsonl,.json'+(hosted?',.xlsx,.xlsm':'')+'"></div><div class="links"><label class="source-link">Choose case folder<input type="file" id="caseFolder" webkitdirectory multiple hidden></label>'+(hosted?'<button class="source-link" id="bundle">Load all 28 case exports</button>':'')+'</div><small>Choose individual exports or the full case folder, including its extra subfolder. Other exports can be added under their own names.</small>';
  }else if(kind==='invoice'){
   controls='<div class="file-zone"><b>Import invoice exports</b><small>AWS CUR CSV, GCP billing export CSV, Azure cost CSV, Swiss hoster invoice CSV, JSON, TSV'+(hosted?', Excel (.xlsx, .xlsm)':'')+'</small><input id="importFiles" aria-label="Choose invoice exports" type="file" multiple accept=".csv,.tsv,.jsonl,.json'+(hosted?',.xlsx,.xlsm':'')+'"></div><small>Files are validated in the browser and saved under My sources. Backend calculations continue to use the bundled case snapshot until a loader is added.</small>';
  }else controls=connectorControls();
  body.innerHTML=field('Source type','<select id="connectorType">'+types+'</select>')+controls+'<p role="status" id="sourceStatus"></p><div id="staged"></div>';
  $('connectorType').onchange=e=>{kind=e.target.value;view()};
  if($('importFiles'))$('importFiles').onchange=e=>stageFiles([...e.target.files]);
  if($('caseFolder'))$('caseFolder').onchange=e=>stageFiles([...e.target.files].filter(f=>namedSource(f.name)));
  if($('bundle'))$('bundle').onclick=loadBundle;
  if($('remoteForm'))$('remoteForm').onsubmit=hosted?remote:mockRemote;
 }
 function namedSource(name){return catalog.find(s=>s.file.split('/').pop().toLowerCase()===name.toLowerCase())}
 function schemaSource(fields){const matches=catalog.filter(s=>s.fields.every(k=>fields.includes(k)));return matches.length===1?matches[0]:null}
 function fallbackGroup(){
  return kind==='invoice'?'Imported invoices':kind==='aws'?'AWS invoices':kind==='gcp'?'GCP billing export':kind==='azure'?'Azure costs':'Custom file';
 }
 function record(file,fields,first,count,source,extra={}){
  return {id:'file:'+file.name,name:source?.title||file.name.replace(/\.[^.]+$/,''),group:source?.group||fallbackGroup(),filename:file.name,fields,first,count,blob:file,when:Date.now(),...extra};
 }
 async function post(url,body,signal){
  const r=await fetch(url,{method:'POST',headers:{'X-WattsOn':'preview'},body,signal});
  const data=await r.json();if(!r.ok)throw Error(data.error||'The source could not be read.');
  return data;
 }
 function snapshot(name,group,data,id){
  if(!data.rows.length)throw Error('No records returned.');
  return {id,name,group,filename:name.replace(/[\\/:*?"<>|]/g,'_')+'.json',fields:data.fields,first:data.rows[0],count:data.rows.length,partial:data.partial,when:Date.now(),blob:new Blob([JSON.stringify(data.rows.map(r=>Object.fromEntries(data.fields.map((k,i)=>[k,r[i]]))))],{type:'application/json'})};
 }
 async function parse(file,sheet){
  const known=namedSource(file.name),suffix=file.name.toLowerCase().split('.').pop();
  if(['xlsx','xlsm'].includes(suffix)){
   const data=await post('/api/file?'+new URLSearchParams({name:file.name,...(sheet?{sheet}:{})}),await file.arrayBuffer());
   const item=record(file,data.fields,data.rows[0]||[],data.rows.length,schemaSource(data.fields),{id:'file:'+file.name+'#'+data.sheet,name:file.name+' · '+data.sheet,partial:data.partial,sheets:data.sheets,sheet:data.sheet});
   if(data.partial)item.countLabel='5,000 preview rows · full workbook retained';
   return item;
  }
  const text=(await file.text()).replace(/^\uFEFF/,'');
  let result;
  if(suffix==='jsonl')result=inspectJsonl(text,known);
  else if(suffix==='json'){
   const a=JSON.parse(text);
   if(!Array.isArray(a)||!a.length||a.some(v=>!v||typeof v!=='object'||Array.isArray(v)))throw Error('Expected a JSON array of records.');
   const fields=Object.keys(a[0]);result={fields,first:fields.map(k=>a[0][k]),count:a.length};
  }else{
   if(!['csv','tsv'].includes(suffix))throw Error('Unsupported file type.');
   const head=text.split(/\r?\n/,1)[0];
   const delim=suffix==='tsv'?'\t':[',',';','\t','|'].sort((a,b)=>head.split(b).length-head.split(a).length)[0];
   result=inspectCsv(text,known?.fields||[],delim);
  }
  if(!result.fields.some(Boolean)||result.fields.some(f=>!f.trim()))throw Error('Every column needs a heading.');
  return record(file,result.fields,result.first,result.count,known||schemaSource(result.fields));
 }
 function preview(){
  const box=$('staged');if(!box)return;
  box.innerHTML=(workbook&&pending[0]?.sheets?.length>1?field('Worksheet','<select id="sheetPick">'+pending[0].sheets.map(s=>'<option '+(s===pending[0].sheet?'selected':'')+'>'+esc(s)+'</option>').join('')+'</select>'):'')+
   '<div class="source-preview">'+pending.map(s=>'<details><summary>'+esc(s.name)+' <small>'+fmt(s.count)+' '+(s.partial?'preview rows':'rows')+'</small></summary><p>'+esc(s.group)+'</p>'+sample(s.fields,s.first)+'</details>').join('')+'</div>'+
   '<button id="saveSources" class="primary">Save '+pending.length+' source'+(pending.length===1?'':'s')+'</button><small>Saved to My sources. The case dashboards use their bundled baseline.</small>';
  if($('sheetPick'))$('sheetPick').onchange=e=>stageFiles([workbook],e.target.value);
  $('saveSources').onclick=save;
 }
 async function stageFiles(files,sheet){
  const ticket=++revision;pending=[];workbook=null;$('staged').replaceChildren();
  if(!files.length){msg('No case files matched. Choose the folder containing the CSV and JSONL exports.');return}
  const items=[],seen=new Set();
  try{
   for(const file of files){
    msg('Reading '+(items.length+1)+' of '+files.length+' · '+file.name);
    let item;try{item=await parse(file,sheet)}catch(err){throw Error(file.name+' · '+err.message)}
    if(ticket!==revision)return;
    if(seen.has(item.id))throw Error('Two files have the same name. Import them separately with distinct names.');
    seen.add(item.id);items.push(item);
   }
   pending=items;workbook=files.length===1&&items[0].sheets?files[0]:null;
   const recognized=new Set(items.map(s=>namedSource(s.filename)?.id).filter(Boolean));
   msg(fmt(items.reduce((n,s)=>n+s.count,0))+' rows ready to review.'+(recognized.size?' Matched '+recognized.size+' of 28 case sources.':'')+(items.some(s=>saved.some(x=>x.id===s.id))?' Saving updates the matching snapshots.':''));
   preview();
  }catch(err){if(ticket===revision)msg(err.message)}
 }
 async function loadBundle(){
  const ticket=++revision;pending=[];$('staged').replaceChildren();
  try{
   const files=[];
   for(const s of catalog){
    msg('Loading '+s.title+'…');const r=await fetch(root+s.file);if(!r.ok)throw Error('Could not load '+s.file);
    files.push(new File([await r.blob()],s.file.split('/').pop()));if(ticket!==revision)return;
   }
   await stageFiles(files);
  }catch(err){if(ticket===revision)msg(err.message)}
 }
 async function remote(e){
  e.preventDefault();const form=e.target,ticket=++revision;
  pending=[];$('staged').replaceChildren();msg('Reading from '+options[kind]+'…');
  const config=Object.fromEntries(new FormData(form)),type=kind;
  try{
   const data=await post('/api/connect',JSON.stringify({...config,kind:type}));
   if(revision!==ticket)return;
   pending=[snapshot(config.name,options[type],data,'remote:'+type+':'+config.name)];
   msg(data.partial?'Preview limited to returned rows.':'Connection verified.');preview();
  }catch(err){if(ticket===revision)msg(err.message)}
 }
 function mockData(type,config){
  const name=config.name||options[type];
  const rows={
   aws:[['2026-08',config.account||'123456789012','AmazonEC2','eu-central-1','732.0','Hrs','128.44','department=IT;environment=dev'],['2026-08',config.account||'123456789012','AmazonS3','eu-west-1','418.6','GB-Mo','39.18','department=Finance;environment=prod']],
   gcp:[['2026-08',config.billing||'000000-AAAAAA-BBBBBB','Compute Engine','europe-west6','612.5','hour','CHF','144.20','project=p-carbon-lab'],['2026-08',config.billing||'000000-AAAAAA-BBBBBB','BigQuery','europe-west6','92.0','TiB','CHF','57.80','project=p-analytics']],
   azure:[['2026-08',config.subscription||'0000-0000','Virtual Machines','Switzerland North','384.0','vCore-hour','CHF','34.61','department=Finance'],['2026-08',config.subscription||'0000-0000','Storage','Germany West Central','1840.0','GB-month','EUR','22.10','department=IT']],
   powerbi:[['2026-08',config.dataset||'semantic-model','Revenue cockpit','Sales','8','33.5','54','management']],
   databricks:[['2026-08',config.table||'main.billing.jobs','dp-dev','Germany (Frankfurt)','8','24.0','2.1','preview']],
   http:[['2026-08',config.url||'https://api.example.test/export','200','application/json','128','mocked response']],
   odbc:[['2026-08',config.dsn||'FinanceDW',config.table||'cloud_costs','Finance','4200','CHF','188.40']]
  };
  const fields={
   aws:['month','account_id','service','region','usage_amount','unit','cost_usd','tags'],
   gcp:['month','billing_account_id','service','region','usage_amount','unit','currency','cost','labels'],
   azure:['month','subscription_id','service','region','quantity','unit','currency','cost','tags'],
   powerbi:['month','dataset','report','department','refreshes','duration_min','views','classification'],
   databricks:['month','table','cluster','region','node_count','runtime_h','active_use_h','note'],
   http:['month','endpoint','status','content_type','records','note'],
   odbc:['month','dsn','table','department','cost_center','currency','amount']
  };
  return {fields:fields[type]||['month','source','records','note'],rows:rows[type]||[['2026-08',name,'128','mock connector preview']],partial:true};
 }
 async function mockRemote(e){
  e.preventDefault();const ticket=++revision,form=e.target,type=kind,config=Object.fromEntries(new FormData(form));
  pending=[];$('staged').replaceChildren();msg('Preparing mocked '+options[type]+' preview…');
  await new Promise(resolve=>setTimeout(resolve,180));
  if(revision!==ticket)return;
  const sourceName=(config.name||options[type]+' mock').trim();
  pending=[snapshot(sourceName,options[type],mockData(type,{...config,name:sourceName}),'mock:'+type+':'+sourceName)];
  msg('Mock connector preview ready. No redirect or external API call was made.');
  preview();
 }
 async function save(){
  const items=pending.slice();if(!items.length)return;
  $('saveSources').disabled=true;
  try{
   const db=await database;
   await new Promise((resolve,reject)=>{const tx=db.transaction('sources','readwrite');for(const s of items)tx.objectStore('sources').put(s);tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error||Error('Could not save the sources.'))});
   await reload();dialog.close();$('personal').scrollIntoView({block:'center'});
  }catch(err){msg('Save failed: '+err.message);if($('saveSources'))$('saveSources').disabled=false}
 }
 function open(type){kind=Object.hasOwn(options,type)?type:'file';view();dialog.showModal()}
 $('addSource').onclick=()=>open('file');
 dialog.addEventListener('close',()=>{cancelPending();body.replaceChildren()});
 reload().catch(()=>{});
 const requested=new URLSearchParams(location.search).get('add');if(requested)open(requested);
})();



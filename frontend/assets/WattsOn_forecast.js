/* Reference-year estimates shared with the baseline and package screens. */
const measures = [
  {id:'M1',name:'Start training GPU on demand',resource:'gpu-ml',days:1.5,cost:9770,energy:3909,co2:1485,guard:'Keep quarterly training days 1–3 and ad-hoc work available.',source:'hoster_invoice.csv; server_metrics_weekly.csv; T-1101'},
  {id:'M2',name:'Relocate and pause development',resource:'dp-dev',days:3,cost:24590,energy:5720,co2:3085,guard:'Validate residency and keep development and training available.',source:'azure_costs.csv; T-1053; T-1074'},
  {id:'M3',name:'Scale production between batches',resource:'dp-prod',days:3,cost:23560,energy:5708,co2:599,guard:'Head of Consulting approval. Protect daily ETL, month-end and year-end close.',source:'azure_costs.csv; data_platform_jobs.csv; T-1029'},
  {id:'M4',name:'Right-size the test fleet',resource:'vm-test',days:1.5,cost:16980,energy:2507,co2:702,guard:'Retain hot DR and acceptance freezes. Reconcile 52 inventory vs 64 billed vCPUs.',source:'aws_costs.csv; server_inventory.csv; T-1094; T-1204'},
  {id:'M5',name:'Reduce idle AI subscriptions',resource:'ai_subscriptions',days:1,cost:14990,energy:40,co2:10,guard:'Head of IT approval; migrate two active users; respect 30-day notice.',source:'ai_subscriptions.csv; exchange_rates.csv'},
  {id:'M6',name:'Reclaim unused SaaS seats',resource:'saas_contracts',days:2,cost:29900,energy:1054,co2:264,guard:'At renewal only. Head of Finance decides video-tool overlap.',source:'saas_contracts.csv; m365_usage.csv'},
  {id:'M7',name:'Route classification to a small model',resource:'ai-marketing',days:1.5,cost:9250,energy:1340,co2:335,guard:'Validate classification quality and cap requests.',source:'ai_usage.csv; ai_invoice_monthly.csv; T-1212'},
  {id:'M8',name:'Shorten non-audit log retention',resource:'logs',days:1,cost:6170,energy:344,co2:36,guard:'Exclude audit and security logs; respect retention obligations.',source:'log_volume.csv; mapping_departments_tools.csv'}
];
const baseline={cost:470384,energy:56139,co2:11956,market:2004};
const marketFactor=baseline.market/baseline.energy;
const units={cost:'CHF',energy:'kWh',co2:'kg CO₂'};
const titles={cost:'Operating cost',energy:'Electricity use',co2:'Carbon footprint'};
const id=s=>document.getElementById(s);
const fmt=n=>Math.round(n).toLocaleString('en-CH');
const selected=new Set(measures.map(m=>m.id));
let metric='co2', briefView='drivers', department='All departments', ledgerMetric='co2';
const list=id('measureList');
for(const m of measures){
 const label=document.createElement('label'),input=document.createElement('input');
 input.type='checkbox'; input.checked=true;input.value=m.id;
 input.onchange=()=>{if(input.checked)selected.add(m.id);else selected.delete(m.id);render(m.id)};
 label.append(input,m.id+' · '+m.name);list.append(label);
}
function sums(){
 const total={days:0,cost:0,energy:0,co2:0};
 for(const m of measures.filter(m=>selected.has(m.id))) for(const key of Object.keys(total))total[key]+=m[key];
 return total;
}
function assumptions(){
 const g=Number(id('growth').value);
 return {growth:[g-7,g,g+8],grid:Number(id('grid').value)/100,market:id('basis').value==='market',year:Number(id('year').value)};
}
function forecast(n,pack,band,a,s){
 if(n===0)return {cost:baseline.cost,energy:baseline.energy,co2:a.market?baseline.market:baseline.co2};
 const demand=(1+a.growth[band]/100)**n;
 const nodeStep=.2*(n===1?11/12:1);
 const renewal=.12*(n===1?2/12:1)*m365Spend;
 const energy=(baseline.energy+21141.1*nodeStep-(pack?s.energy:0))*demand;
 const carbon=(baseline.co2+21141.1*nodeStep*.105-(pack?s.co2:0))*demand*(1+a.grid)**n;
 return {cost:(baseline.cost+87255.5*nodeStep+renewal-(pack?s.cost:0))*demand,energy,co2:a.market?energy*marketFactor:carbon};
}
function series(n,pack,a,s){return [0,1,2].map(b=>forecast(n,pack,b,a,s)[metric])}
function draw(a,s){
 const points=Array.from({length:5},(_,n)=>[series(n,false,a,s),series(n,true,a,s)]);
 const top=Math.max(...points.flat(2))*1.08;
 const narrow=window.matchMedia('(max-width:540px)').matches;
 const width=narrow?350:675,left=narrow?40:62,right=width-(narrow?22:41);
 const step=(right-left)/4;
 const x=n=>left+n*step, y=v=>184-154*v/top;
 const path=arr=>arr.map(([x,y],i)=>(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)).join(' ');
 const plot=(p,b)=>points.map((v,n)=>[x(n),y(v[p][b])]);
 let html='<defs><linearGradient id="lowerBand" x2="0" y2="1"><stop stop-color="#16a34a"/><stop offset="1" stop-color="#b9d846"/></linearGradient></defs>';
 html+='<text class="axis-unit" x="'+(left-5)+'" y="16" text-anchor="end">'+units[metric]+'</text>';
 for(let i=0;i<=4;i++){
   const v=top*i/4,Y=y(v);html+='<path d="M'+left+' '+Y+'H'+right+'" stroke="#e0e6e4"/><text x="'+(left-5)+'" y="'+(Y+4)+'" text-anchor="end">'+(v/1000).toFixed(1)+'k</text>';
 }
 for(let p=0;p<2;p++){
   const color=p?'#0f7a36':'#52657b';
   html+='<path d="'+path([...plot(p,0),...plot(p,2).reverse()])+'Z" fill="'+(p?'url(#lowerBand)':color)+'" opacity=".16"/><path d="'+path(plot(p,1))+'" stroke="'+color+'" stroke-width="3.5" fill="none" '+(p?'':'stroke-dasharray="7 5"')+'/>';
 }
 const focus=a.year-2026;
 html+='<path d="M'+x(focus)+' 17V185" stroke="#526170" opacity=".5" stroke-dasharray="2 4"/>';
 for(let n=0;n<=4;n++){
  if(n===focus)html+='<rect x="'+(x(n)-21)+'" y="189" width="42" height="24" rx="12" fill="#eaf3d7"/>';
  html+='<text x="'+x(n)+'" y="206" text-anchor="middle">'+(n?2026+n:'Baseline')+'</text>';
  for(let p=0;p<2;p++) html+='<circle cx="'+x(n)+'" cy="'+y(points[n][p][1])+'" r="'+(n===focus?6:3)+'" fill="'+(p?'#0f7a36':'#52657b')+'" stroke="white" stroke-width="2"/>';
 }
 for(let n=1;n<=4;n++)html+='<rect class="chart-hit" data-year="'+(2026+n)+'" x="'+(x(n)-step/2)+'" y="12" width="'+step+'" height="204" fill="transparent"><title>View fiscal year '+(2026+n)+'</title></rect>';
 id('chart').innerHTML='<svg viewBox="0 0 '+width+' 222" role="img" aria-label="'+titles[metric]+' in '+units[metric]+', baseline through fiscal year 2030. Exact values under Inspect year." style="font:12px system-ui;fill:#50606b">'+html+'</svg>';
 const [without,withPkg]=points[focus];
 const percent=100*(1-withPkg[1]/without[1]);
 function snapshot(label,values,style){
  return '<div class="snapshot '+style+'"><span class="ph">'+label+'</span><strong>'+fmt(values[1])+' <small>'+units[metric]+'</small></strong><span class="limits">'+fmt(values[0])+' – '+fmt(values[2])+'</span></div>';
 }
 id('readouts').innerHTML=snapshot('Without package',without,'before')+'<div class="bridge"><span class="saving-ring" style="--pct:'+percent+'%"><b>−'+percent.toFixed(1)+'%</b></span></div>'+snapshot('With package',withPkg,'after');
 document.querySelectorAll('[data-fy]').forEach(b=>b.setAttribute('aria-pressed',Number(b.dataset.fy)===a.year));
 id('yearTitle').textContent=titles[metric]+' · FY '+a.year;
 const detailRow=(label,values)=>'<tr><th>'+label+'</th>'+values.map(v=>'<td>'+fmt(v)+'</td>').join('')+'</tr>';
 id('detailMetrics').innerHTML='<table><caption>'+units[metric]+' · demand growth scenarios</caption><thead><tr><th>Path</th><th>Low</th><th>Mid</th><th>High</th></tr></thead><tbody>'+detailRow('Without package',without)+detailRow('With package',withPkg)+detailRow('Avoided',without.map((v,i)=>v-withPkg[i]))+'</tbody></table>';
 id('chartYear').textContent='FY '+(a.year-1)+'/'+String(a.year).slice(-2)+(metric==='co2'?' · '+(a.market?'Market-based':'Location-based'):'');
 id('years').innerHTML=points.slice(1).map((pair,n)=>'<tr><td>'+(2027+n)+'</td>'+pair.map(v=>'<td>'+v.map(fmt).join(' / ')+'</td>').join('')+'</tr>').join('');
}
function render(reason){
 const a=assumptions(),s=sums();
 id('growthV').value=a.growth[1]+'%';id('growthRange').textContent='Low '+a.growth[0]+'% · high '+a.growth[2]+'% per year';
 id('gridV').value=Math.round(a.grid*100)+'%';id('rollout').value=selected.size;id('rolloutV').value=selected.size+' / 8';
 for(const slider of document.querySelectorAll('.knob input'))slider.style.setProperty('--progress',100*(slider.value-slider.min)/(slider.max-slider.min)+'%');
 list.querySelectorAll('input').forEach(el=>el.checked=selected.has(el.value));
 document.querySelectorAll('[data-m]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.m===metric));
 draw(a,s);
 drawBrief(a,s);
 const target=(label,value,pass,hint,ratio)=>'<div class="goal"><i class="dial '+(pass?'':'pending')+'" aria-hidden="true" style="--fill:'+Math.min(100,ratio*100)+'%"><span>'+(pass?'✓':'↗')+'</span></i><div><small>'+label+'</small><b>'+value+'</b><em class="'+(pass?'':'miss')+'">'+(pass?'Met':'Below target')+' · '+hint+'</em></div></div>';
 id('targets').innerHTML=target('Operating cost reduction',(s.cost/baseline.cost*100).toFixed(1)+'%',s.cost>=.25*baseline.cost,'25% target',s.cost/(.25*baseline.cost))+target('Grid CO₂ reduction',(s.co2/baseline.co2*100).toFixed(1)+'%',s.co2>=.4*baseline.co2,'40% target',s.co2/(.4*baseline.co2))+target('One-time effort','CHF '+fmt(s.days*1100),s.days<=15,fmt(16500-s.days*1100)+' CHF left',s.days/15);
 const n=a.year-2026,ref=forecast(n,false,1,a,s),pkg=forecast(n,true,1,a,s);
 for(const [key,target] of Object.entries({co2:'sumCarbon',cost:'sumCost',energy:'sumEnergy'}))id(target).textContent=fmt(ref[key]-pkg[key]);
 id('sumMeasures').textContent=selected.size+' / '+measures.length;
 id('formula').innerHTML='<p><b>FY '+a.year+' · '+titles[metric]+'</b><br>'+fmt(ref[metric])+' − '+fmt(pkg[metric])+' = '+fmt(ref[metric]-pkg[metric])+' '+units[metric]+' avoided (rounded).</p><p>For each path, add scheduled capacity and price changes to the baseline, subtract selected annual savings, then compound demand for '+n+' years. Implementation costs are shown separately in the receipt. Prices otherwise stay fixed.</p><p>Location-based carbon uses regional baseline emissions and the measures’ regional savings, then compounds the grid change. Market-based carbon uses forecast kWh × '+marketFactor.toFixed(4)+' kg/kWh, an illustrative blended contractual factor.</p><p>Shading spans demand growth of '+a.growth[0]+'% to '+a.growth[2]+'% around '+a.growth[1]+'%. The bands are scenario bounds at mid-case energy and grid factors. Factor uncertainty is reported separately in the baseline CSV. The annual case baseline anchors every forecast.</p>';
 const growth=Math.pow(1+a.growth[1]/100,n),step=.2*(n===1?11/12:1),price=.12*(n===1?2/12:1)*m365Spend;
 const carbonScale=Math.pow(1+a.grid,n);
 let equation;
 if(metric==='cost')equation='('+fmt(baseline.cost)+' baseline + '+fmt(87255.5*step)+' extra nodes + '+fmt(price)+' renewal − '+fmt(s.cost)+' selected savings) × '+growth.toFixed(4);
 else if(metric==='energy')equation='('+fmt(baseline.energy)+' baseline + '+fmt(21141.1*step)+' extra nodes − '+fmt(s.energy)+' selected savings) × '+growth.toFixed(4);
 else if(a.market)equation=fmt(pkg.energy)+' forecast kWh × '+marketFactor.toFixed(5)+' kg/kWh';
 else equation='('+fmt(baseline.co2)+' baseline + '+fmt(21141.1*step*.105)+' extra production emissions − '+fmt(s.co2)+' selected savings) × '+growth.toFixed(4)+' demand × '+carbonScale.toFixed(4)+' grid intensity';
 id('formula').insertAdjacentHTML('afterbegin','<p class="finding"><b>With package · '+units[metric]+'</b><br>'+equation+' ≈ '+fmt(pkg[metric])+'.</p>');
 if(reason)recommend(reason);
}
id('rollout').oninput=e=>{selected.clear();measures.slice(0,+e.target.value).forEach(m=>selected.add(m.id));render('rollout')};
for(const name of ['growth','grid','basis','year'])id(name).addEventListener('input',()=>render(name));
id('metrics').onclick=e=>{if(e.target.dataset.m){metric=e.target.dataset.m;render('metric')}};
id('chart').onclick=e=>{if(e.target.dataset.year){id('year').value=e.target.dataset.year;render('year')}};
function openForecastDetail(showCalculation=false){
 id('formula').parentElement.open=showCalculation;
 id('yearDetail').showModal();
}
id('inspectCalc').onclick=()=>openForecastDetail();
window.matchMedia('(max-width:540px)').addEventListener('change',()=>draw(assumptions(),sums()));
id('libraryCalc').onclick=()=>openForecastDetail(true);
document.querySelector('.year-buttons').onclick=e=>{if(e.target.dataset.fy){id('year').value=e.target.dataset.fy;render('year')}};
document.querySelectorAll('[data-inspect]').forEach(b=>b.onclick=()=>{metric=b.dataset.inspect;render('metric');openForecastDetail()});
id('summaryMeasures').onclick=()=>{const pick=document.querySelector('.pick');pick.open=true;pick.querySelector('summary').focus();pick.scrollIntoView({block:'center'})};
id('reset').onclick=()=>{id('growth').value=12;id('grid').value=-3;id('year').value=2030;id('basis').value='location';metric='co2';measures.forEach(m=>selected.add(m.id));render('reset')};
function download(name,columns,rows){
 const cell=value=>'"'+String(value??'').replaceAll('"','""')+'"';
 const csv=[columns,...rows].map(row=>row.map(cell).join(',')).join('\r\n');
 const url=URL.createObjectURL(new Blob(['\uFEFF',csv],{type:'text/csv;charset=utf-8'}));
 const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
id('assumptionsCsv').onclick=()=>{
 const a=assumptions(),columns=Object.keys(factors[0]);
 const rows=factors.map(row=>({...row}));
 Object.assign(rows.find(r=>r.parameter==='growth_per_year'),{value_low:a.growth[0],value_mid:a.growth[1],value_high:a.growth[2],source:'Scenario control; provider_monthly_report.csv; T-1261',calculation_or_assumption:'Compound annually; default 12%, low -7pp and high +8pp.'});
 rows.push({parameter:'grid_intensity_change_per_year',must_or_bonus:'Bonus',value_mid:Math.round(a.grid*100),unit:'percent',source:'Illustrative scenario control',calculation_or_assumption:'Annual multiplicative change to location-based intensity.'});
 download('baseline_and_assumptions.csv',columns,rows.map(row=>columns.map(c=>row[c])));
};
id('measuresCsv').onclick=()=>download('measures_package.csv',measureHeader,measures.filter(m=>selected.has(m.id)).map(m=>[m.id,m.name,m.resource,m.name,m.days,m.cost,m.energy,m.co2,Math.round(m.energy*marketFactor),m.guard,m.source+'; market-based estimate = kWh saved × blended supplier factor']));
const sourceGroups=[
 ['Data platform','data_platform_jobs.csv · data_catalog_tables.csv · powerbi_usage.csv','Fixed ETL and flexible jobs; 247 tables unread for a year, including 36 retention flags; 17,280 refreshes for eight views on pbi-06.'],
 ['Development and infrastructure','ci_pipeline_runs.jsonl · web_traffic.csv · log_volume.csv · backup_chains.csv','21% unchanged nightlies; 36.5% bot traffic; exclude audit logs; 21 of 36 sources backed up three ways. Verify restore tests.'],
 ['AI and collaboration','ai_agent_runs.jsonl · ai_invoice_monthly.csv · m365_usage.csv','9.4% of report-agent outputs opened. Reconcile usage with the invoice and check seat activity before renewal.'],
 ['Regions and ownership','data_center_locations.csv · provider_monthly_report.csv · headcount.csv · projects.csv · project_hours_monthly.csv','Separate used regions from the catalogue. Direct costs follow resource tags, shared costs follow FTE; review project hours for rechargeability.']
];
id('sources').innerHTML=sourceGroups.map(([label,src,body])=>'<p><b>'+label+'</b><br>'+body+'<br><small>'+src+'</small></p>').join('');
function bot(message){const m=document.createElement('div');m.className='msg bot';m.textContent=message;id('msgs').append(m);id('msgs').scrollTop=id('msgs').scrollHeight}
function ask(q){
 const m=document.createElement('div');m.className='msg me';m.textContent=q;id('msgs').append(m);
 const a=assumptions(),s=sums(),n=a.year-2026,without=forecast(n,false,1,a,s),withPkg=forecast(n,true,1,a,s);
 if(/department|driver|largest/i.test(q)){
  const top=[...caseData.ledger].sort((a,b)=>b.co2-a.co2)[0];
  bot(top.tool+' leads at '+fmt(top.co2)+' kg CO₂, or '+(100*top.co2/baseline.co2).toFixed(1)+'% of the baseline. Source: cleaned resource ledger; see Drivers for allocation by department.');
 }else if(/season|quarter/i.test(q)){
  const hours=caseData.quarters,sum=hours.reduce((a,b)=>a+b,0);
  bot('The baseline production activity shares from September onward are '+hours.map(h=>(100*h/sum).toFixed(1)+'%').join(', ')+'. Source: quarterly sums of dp-prod active_use_h in data_platform_usage.csv. Seasonality uses them to allocate forecast production energy.');
 }else if(/certificat|market.based|grid mix/i.test(q)){
  const loc=forecast(n,true,1,{...a,market:false},s),market=forecast(n,true,1,{...a,market:true},s);
  bot('FY '+a.year+' with your selection: '+fmt(loc.co2)+' kg on location-based accounting, '+fmt(market.co2)+' kg on market-based accounting. Source: regional grid factors vs '+marketFactor.toFixed(5)+' contractual kg/kWh × '+fmt(market.energy)+' kWh. The latter is a supplier proxy.');
 }else if(/seat|subscription/i.test(q))bot('Aug 2026 purchased / active: ChatGPT 23 / 2, Copilot 100 / 60, Claude 34 / 28. Idle cost = (21×25 + 40×21 + 6×25) USD × 0.8076 ≈ CHF 1,224 per month. Sources: ai_subscriptions.csv and exchange_rates.csv.');
 else if(/range|uncertain/i.test(q))bot('FY '+a.year+' with the package: '+series(n,true,a,s).map(fmt).join(' / ')+' '+units[metric]+'. These low, mid and high paths compound demand at '+a.growth.join(' / ')+'% annually. Source: current assumptions and the baseline receipt.');
 else if(/target|budget|effort/i.test(q))bot('Reference-year cost reduction = CHF '+fmt(s.cost)+' ÷ 470,384. Location-based CO₂ reduction = '+fmt(s.co2)+' ÷ 11,956 kg. Effort = '+s.days+' days × CHF 1,100. Source: selected M1–M8 case estimates.');
 else if(/gpu|m1\b/i.test(q))bot('M1: 3,909 kWh avoided × 0.380 kg/kWh ≈ 1,485 kg CO₂ and CHF 9,770 annual savings, for 1.5 days of effort. Retain quarterly training and ad-hoc starts. Sources: hoster_invoice.csv and T-1101.');
 else if(/etl|prod|protect/i.test(q))bot('Keep production online for 02:00–08:00 ETL, refresh and export, plus closing windows. M3 is off-window scaling and requires Consulting approval. Sources: data_platform_jobs.csv and T-1029.');
 else if(/compare|path|saving|forecast/i.test(q))bot('FY '+a.year+': '+fmt(without[metric])+' − '+fmt(withPkg[metric])+' = '+fmt(without[metric]-withPkg[metric])+' '+units[metric]+' avoided. Source: annual baseline, selected measures and the controls shown here.');
 else bot('I can calculate the current paths, range or targets, or explain AI seats, GPU savings and protected production hours. Choose one of those topics.');
}
function send(e){e.preventDefault();const v=id('chIn').value.trim();if(v)ask(v);id('chIn').value=''}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!chatPanel.inert)closeChat()});

const departmentNames=[...new Set([...Object.keys(caseData.fte),...caseData.ledger.map(r=>r.dept)])].filter(d=>d!=='Overhead').sort();
const totalFte=Object.values(caseData.fte).reduce((sum,n)=>sum+n,0);
const number=n=>n.toLocaleString('en-CH',{maximumFractionDigits:1});
const quarterNames=['Sep–Nov','Dec–Feb','Mar–May','Jun–Aug'];
const biggestEmitter=caseData.ledger.reduce((top,row)=>row.co2>top.co2?row:top);
function evidence(label,content){return '<details class="evidence-fold"><summary>'+label+'</summary>'+content+'</details>'}
function rankBar(label,value,max,unit){
 return '<li><span>'+label+'</span><strong>'+fmt(value)+' '+unit+'</strong><i aria-hidden="true"><b style="width:'+100*value/Math.max(1,max)+'%"></b></i></li>';
}
function sourceFile(path){
 const url=caseData.dataPath+path;
 return '<a href="'+encodeURI(url)+'" target="_blank" rel="noopener">'+path.split('/').pop()+'</a>';
}
function rankedWorkloads(){
 return caseData.ledger.map(r=>{
  let share=1;
  if(department!=='All departments')share=r.dept==='Overhead'?(caseData.fte[department]||0)/totalFte:Number(r.dept===department);
  return {...r,chf:r.chf*share,kwh:r.kwh*share,co2:r.co2*share,share};
 }).filter(r=>r.share>0).sort((a,b)=>b[ledgerMetric]-a[ledgerMetric]);
}
function drawDrivers(){
 const rows=rankedWorkloads();
 const ledger=rows.map(r=>'<tr><td><b>'+r.tool+'</b><small>'+r.rid+' · '+r.cat+' · '+r.loc+'</small></td><td>'+(r.dept==='Overhead'?(department==='All departments'?'Shared by FTE':department+' · FTE share'):r.dept)+'</td><td>'+fmt(r.chf)+'</td><td>'+fmt(r.kwh)+'</td><td>'+number(r.co2)+'</td></tr>').join('');
 const units={co2:'kg CO₂',chf:'CHF',kwh:'kWh'};
 const filters='<div class="ledger-head"><label>Department <select id="deptPick">'+['All departments',...departmentNames].map(d=>'<option '+(d===department?'selected':'')+'>'+d+'</option>').join('')+'</select></label><label>Rank by <select id="ledgerSort">'+[['co2','CO₂'],['chf','Cost'],['kwh','Energy']].map(([k,v])=>'<option value="'+k+'" '+(k===ledgerMetric?'selected':'')+'>'+v+'</option>').join('')+'</select></label></div>';
 const bars=rows.slice(0,3).map(r=>rankBar(r.tool,r[ledgerMetric],rows[0][ledgerMetric],units[ledgerMetric])).join('');
 const table='<div class="scroll"><table><thead><tr><th>Workload</th><th>Department</th><th>CHF</th><th>kWh</th><th>kg CO₂</th></tr></thead><tbody>'+ledger+'</tbody></table></div>';
 return '<div class="explore-head"><h3>Top three workloads</h3><small>Baseline FY 2025/26</small></div>'+filters+'<ol class="rank-bars">'+bars+'</ol>'+evidence('All '+rows.length+' ledger entries',table)+evidence('Sources &amp; allocation','<p>Frankfurt development ran for 69,120 node-hours with 750 hours of active use. Estimated footprint: 69,120 × 0.10 kWh × 1.30 PUE × 0.380 kg/kWh ≈ 3.4 t CO₂.</p><p>Tagged costs follow the owner. Shared tools use each department’s share of '+number(totalFte)+' FTE. The API bill includes agent activity.</p><small>'+['azure_costs.csv','data_platform_usage.csv','mapping_departments_tools.csv','extra/headcount.csv'].map(sourceFile).join(' · ')+'</small>');
}
function drawDecisions(){
 const handoff={M3:'Head of Consulting',M4:'Head of IT · inventory discrepancy',M5:'Head of IT',M6:'Head of Finance'};
 const lines=measures.map(m=>'<details class="guardline"><summary>'+m.id+' · '+m.name+' · '+(selected.has(m.id)?'Included':'Excluded')+'</summary><p>'+m.guard+'</p><small>Baseline potential: CHF '+fmt(m.cost)+' · '+fmt(m.energy)+' kWh · '+fmt(m.co2)+' kg CO₂ per year. Effort: '+m.days+' days × CHF 1,100. '+(handoff[m.id]?'Review: '+handoff[m.id]+'. ':'')+m.source+'</small></details>').join('');
 return '<div class="explore-head"><h3>Dublin test fleet</h3><small>Owner · Head of IT</small></div><ol class="rank-bars review-bars">'+rankBar('Billed',64,64,'vCPUs')+rankBar('In inventory',52,64,'vCPUs')+'</ol><div class="review-action"><span>Reconcile 12 vCPUs before resizing.</span><a id="reviewDecisions" href="package.html#approvals">Open approvals ↗</a></div>'+evidence('Measure safeguards &amp; owners',lines);
}
function drawCarbon(a,s){
 const paths=[false,true].map(pack=>[false,true].map(market=>forecast(a.year-2026,pack,1,{...a,market},s).co2));
 const max=Math.max(...paths.flat());
 const comparison=(name,col,note)=>'<div><h4>'+name+'</h4><small>'+note+'</small><ol class="rank-bars carbon-bars">'+rankBar('Without package',paths[0][col],max,'kg')+rankBar('With package',paths[1][col],max,'kg')+'</ol></div>';
 return '<div class="explore-head"><h3>Same electricity, two CO₂ estimates</h3><small>FY '+a.year+'</small></div><div class="account-pair">'+comparison('Location-based',0,'Regional grids · target basis')+comparison('Market-based',1,'Supplier certificates · estimate')+'</div>'+evidence('Factors &amp; calculation','<p>Grid factors in kg CO₂/kWh: Zurich 0.105, Frankfurt 0.380, Dublin 0.280 and EU mixed 0.250. The Swiss estimate includes imports. The grid slider changes these factors each year.</p><p>Market-based CO₂ = kWh × '+marketFactor.toFixed(4)+' kg/kWh. This illustrative certificate factor comes from 2,004 kg ÷ 56,139 kWh and needs supplier verification.</p>');
}
function quarterlyEnergy(a,s){
 const hours=caseData.quarters,total=hours.reduce((n,v)=>n+v,0),n=a.year-2026;
 const prod=(21141.1*(1+.2*(n===1?11/12:1))-(selected.has('M3')?5708:0))*(1+a.growth[1]/100)**n;
 const fiscalStart=a.year-1;
 const dates=[Date.UTC(fiscalStart,8,1),Date.UTC(fiscalStart,11,1),Date.UTC(a.year,2,1),Date.UTC(a.year,5,1),Date.UTC(a.year,8,1)];
 const annual=forecast(n,true,1,a,s).energy;
 return hours.map((h,i)=>{
  const share=h/total,days=(dates[i+1]-dates[i])/(dates[4]-dates[0]);
  return prod*share+(annual-prod)*days;
 });
}
function drawSeasons(a,s){
 const demand=quarterlyEnergy(a,s),peak=Math.max(...demand);
 const bars=demand.map((v,i)=>'<div class="season-col '+(v===peak?'peak':'')+'"><b>'+fmt(v)+'</b><i style="height:'+v/peak*70+'px"></i><span>'+quarterNames[i]+'</span></div>').join('');
 return '<div class="explore-head"><h3>Quarterly electricity</h3><small>With package · FY '+a.year+' · kWh</small></div><div class="season-plot">'+bars+'</div>'+evidence('How quarters are estimated','<p>Production follows the baseline pattern of '+caseData.quarters.map(fmt).join(' / ')+' active hours. Other workloads are split by days in each quarter. Production capacity rises from 20 to 24 nodes in October 2026.</p><small>'+sourceFile('data_platform_usage.csv')+' · T-1261</small>');
}
function drawBrief(a,s){
 const demand=quarterlyEnergy(a,s);
 id('entryDriver').textContent=number(biggestEmitter.co2/1000)+' t CO₂';
 id('entryDriver').parentElement.querySelector('small').textContent=biggestEmitter.tool+' · baseline';
 id('entryPeak').textContent=quarterNames[demand.indexOf(Math.max(...demand))];
 id('entryCarbon').textContent=number(forecast(a.year-2026,true,1,{...a,market:false},s).co2/1000)+' t CO₂';
 document.querySelectorAll('[data-view]').forEach(b=>{b.setAttribute('aria-expanded',!id('caseView').hidden&&b.dataset.view===briefView);b.setAttribute('aria-controls','caseView')});
 const views={drivers:drawDrivers,measures:drawDecisions,carbon:drawCarbon,seasons:drawSeasons};
 id('caseView').innerHTML=views[briefView](a,s);
 if(briefView==='measures'){const link=id('reviewDecisions'),navLink=document.querySelector('nav a[href^="package.html"]');if(link&&navLink)link.href=navLink.href.split('#')[0]+'#approvals'}
 if(briefView==='drivers'){
  id('deptPick').onchange=e=>{department=e.target.value;drawBrief(a,s);id('deptPick').focus();recommend('drivers')};
  id('ledgerSort').onchange=e=>{ledgerMetric=e.target.value;drawBrief(a,s);id('ledgerSort').focus();recommend('drivers')};
 }
 id('factorLedger').innerHTML=factors.map(r=>{
  const vals=r.parameter==='growth_per_year'?a.growth:[r.value_low,r.value_mid,r.value_high];
  return '<tr><td>'+r.parameter.replaceAll('_',' ')+'<small> · '+r.unit+'</small></td><td>'+vals.join(' / ')+'</td><td>'+r.source+' · '+r.calculation_or_assumption+'</td></tr>';
 }).join('');
}
document.querySelector('.briefnav').onclick=e=>{const b=e.target.closest('[data-view]');if(!b)return;id('caseView').hidden=b.dataset.view===briefView&&!id('caseView').hidden;briefView=b.dataset.view;drawBrief(assumptions(),sums())};
let adviceTimer,latestAdvice;
function scenarioAdvice(reason){
 const a=assumptions(),n=a.year-2026,s=sums();
 if(reason==='drivers'){
  const row=rankedWorkloads()[0],unit={chf:'CHF',kwh:'kWh',co2:'kg CO₂'}[ledgerMetric];
  return ['Review '+row.tool+' first.',department+' · FY 2025/26 · '+fmt(row[ledgerMetric])+' '+unit+' in the baseline ledger.'];
 }
 if(reason==='growth'){
  const range=series(n,true,a,s);
  return ['Plan for the high-demand case.','At '+a.growth[2]+'% growth, FY '+a.year+' reaches '+fmt(range[2])+' '+units[metric]+' with the package. Mid case: '+fmt(range[1])+'.'];
 }
 if(reason==='grid'||reason==='basis'){
  const location=forecast(n,true,1,{...a,market:false},s).co2;
  const market=forecast(n,true,1,{...a,market:true},s).co2;
  if(reason==='basis')return [a.market?'Verify the supplier’s certificate factor.':'Use regional grids to track the 40% target.','FY '+a.year+' with package · '+fmt(location)+' kg on regional grids · '+fmt(market)+' kg using the certificate estimate.'];
  return [a.market?'Switch to location-based CO₂ to see the grid change.':'Check the regional grid factors before committing.','At '+Math.round(a.grid*100)+'% per year, the grid-based forecast is '+fmt(location)+' kg CO₂ in FY '+a.year+'.'];
 }
 const omitted=measures.filter(m=>!selected.has(m.id));
 const priorityKey=metric==='co2'&&a.market?'energy':metric;
 const candidates=omitted.length?omitted:measures;
 const measure=measures.find(m=>m.id===reason)||candidates.reduce((best,m)=>m[priorityKey]>best[priorityKey]?m:best);
 const included=selected.has(measure.id),delta=included?-1:1;
 const alternative={...s};
 for(const key of ['cost','energy','co2'])alternative[key]+=delta*measure[key];
 const effect=Math.abs(forecast(n,true,1,a,s)[metric]-forecast(n,true,1,a,alternative)[metric]);
 const title=(included?'Prioritize ':'Consider ')+measure.id+' · '+measure.name+'.';
 return [title,'FY '+a.year+' · '+fmt(effect)+' '+units[metric]+' potential savings. '+measure.guard];
}
function showAdviceInChat(){
 if(!latestAdvice)return;
 const text=latestAdvice.join(' ');
 if(id('msgs').lastElementChild?.textContent===text)return;
 if(id('msgs').lastElementChild?.dataset.advice)id('msgs').lastElementChild.remove();
 bot(text);
 id('msgs').lastElementChild.dataset.advice='true';
}
function recommend(reason){
 clearTimeout(adviceTimer);
 const publish=()=>{
  latestAdvice=scenarioAdvice(reason);
  id('thoughtTitle').textContent=latestAdvice[0];
  id('thoughtEvidence').textContent=latestAdvice[1];
  id('forecastThought').hidden=false;
  if(!chatPanel.inert)showAdviceInChat();
 };
 if(['growth','grid','rollout'].includes(reason))adviceTimer=setTimeout(publish,240);
 else publish();
}
id('dismissThought').onclick=()=>{clearTimeout(adviceTimer);id('forecastThought').hidden=true;launcher.focus({preventScroll:true})};
render();

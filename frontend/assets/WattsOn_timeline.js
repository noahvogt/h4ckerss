/* The selected interval includes its start and stops at its end. */
const timeline = (() => {
  const zone = 'Europe/Zurich';
  const hour = 3600000;
  const clock = new Intl.DateTimeFormat('sv-SE', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  });
  const local = ms => clock.format(ms).replace(' ', 'T');
  const minutePattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;
  // Swiss local minutes have zero, one, or two matching instants during this baseline.
  function instants(value) {
    if (!minutePattern.test(value)) return [];
    const wall = Date.parse(value + ':00Z');
    if (!Number.isFinite(wall)) return [];
    return [wall - 2*hour, wall - hour].filter(ms => local(ms) === value);
  }
  const min = '2025-09-01T00:00', max = '2026-09-01T00:00';
  const first = instants(min)[0], last = instants(max)[0];
  const yearHours = (last-first)/hour, weights = [0];
  for (let i=0; i<yearHours; i++) {
    const stamp=local(first+i*hour);
    const weekday=new Date(stamp.slice(0,10)+'T12:00:00Z').getUTCDay()%6 !== 0;
    const h=Number(stamp.slice(11,13));
    weights.push(weights[i]+(weekday && h>=8 && h<18 ? 1.45 : weekday ? .72 : .55));
  }
  function cumulative(ms) {
    const offset = Math.min(yearHours, Math.max(0, (ms - first) / hour));
    const index = Math.floor(offset);
    return weights[index] + (offset - index) * ((weights[index+1] ?? weights[index]) - weights[index]);
  }
  const valid = (a,b) => Number.isSafeInteger(a) && Number.isSafeInteger(b) &&
    a%60000===0 && b%60000===0 && first<=a && a<b && b<=last;
  const params = new URLSearchParams(location.search);
  // Old links stored UTC wall-clock strings with an inclusive final minute.
  function decode(a,b) {
    if (typeof a!=='string' || typeof b!=='string') return [];
    if (minutePattern.test(a) && minutePattern.test(b)) {
      return [Math.max(first,Date.parse(a+':00Z')),Math.min(last,Date.parse(b+':00Z')+60000)];
    }
    return [a,b].map(v=>/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$/.test(v)?Date.parse(v):NaN);
  }
  function restore(a,b) {
    if (a==='2025-09-01T00:00' && b==='2026-08-31T23:59') return [first,last];
    return decode(a,b);
  }
  let [start,end]=restore(params.get('from'),params.get('to'));
  if (!valid(start,end)) {
    try {
      const saved=JSON.parse(sessionStorage.getItem('wattson-period-v2')||'null');
      [start,end]=saved || restore(...JSON.parse(sessionStorage.getItem('wattson-period-v1')||'[]'));
    } catch {}
  }
  if (!valid(start,end)) [start,end]=[first,last];
  const iso = ms => new Date(ms).toISOString().slice(0,16)+'Z';
  const brief = new Intl.DateTimeFormat('en-GB',{timeZone:zone,day:'numeric',month:'short',year:'numeric'});
  function rangeLabel() {
    if (start===first && end===last) return 'Sep 2025 – Aug 2026';
    const a=local(start), b=local(end);
    if (a.endsWith('T00:00') && b.endsWith('T00:00')) {
      const finalDay=end-60000;
      return brief.format(start) + (a.slice(0,10)===local(finalDay).slice(0,10)?'':' – '+brief.format(finalDay));
    }
    const display = ms => {
      const wall=local(ms), time=wall.slice(11);
      return time+(instants(wall).length===2?(instants(wall)[0]===ms?' CEST':' CET'):'');
    };
    return brief.format(start)+', '+display(start)+' – '+(a.slice(0,10)===b.slice(0,10)?'':brief.format(end)+', ')+display(end);
  }
  const api = {
    get start(){return local(start)}, get end(){return local(end)},
    get full(){return start===first && end===last},
    get share(){return (cumulative(end)-cumulative(start))/weights[yearHours]},
    get label(){return rangeLabel()},
    number(n){return Number(n).toLocaleString('en-US',n!==0 && Math.abs(n)<1 ? {maximumSignificantDigits:2} : {maximumFractionDigits:0})},
    total(n){return api.number(n*api.share)},
    tree(t){
      if (!t || api.full) return t;
      const match=t.head.match(/[\d,]+(?:\.\d+)?/);
      if (!match) return t;
      const head=t.head.replace(match[0],api.total(Number(match[0].replaceAll(',',''))));
      return {head,sub:'Selected period · '+head,story:api.label+' · Illustrative hourly allocation.',f:'Full baseline × selected share of modeled activity',src:t.src,kids:[
        {l:'Full baseline · '+t.sub,v:t.head,f:t.f,src:t.src,kids:t.kids,note:t.story,range:t.range,px:t.px},
        {l:'Activity in selected window',v:(api.share*100).toLocaleString('en-US',{maximumSignificantDigits:3})+'%',f:'Weighted hours in selection ÷ weighted hours in baseline',note:'Basel local-time demo profile: weekday 08:00–18:00 = 1.45, other weekday hours = 0.72, weekends = 0.55. Partial hours are prorated.'}
      ]};
    }
  };
  function href(link) {
    const url = new URL(link.href);
    url.searchParams.set('from', iso(start)); url.searchParams.set('to',iso(end));link.href=url.href;
  }
  function commit(a,b) {
    if (!valid(a,b)) return;
    start=a;end=b;
    try{sessionStorage.setItem('wattson-period-v2',JSON.stringify([a,b]))}catch{}
    try{const url=new URL(location.href);url.searchParams.set('from',iso(a));url.searchParams.set('to',iso(b));history.replaceState(null,'',url)}catch{}
    sync();document.dispatchEvent(new Event('timelinechange'));
  }
  function sync() {
    document.querySelectorAll('.time-filter').forEach(form=>{
      form.elements.from.value=local(start);form.elements.to.value=local(end);
      updateOccurrences(form,'from',start);updateOccurrences(form,'to',end);
      form.querySelector('summary').title=api.label+' · Basel time';
      form.querySelector('output').textContent=api.label;
      form.querySelector('small').textContent=api.full?'Full case baseline':'Illustrative allocation by hour';
      form.querySelector('.time-error').textContent='';
    });
    document.querySelectorAll('a[href^="index.html"],a[href^="package.html"],a[href^="forecast.html"]').forEach(href);
  }
  function updateOccurrences(form,name,selected) {
    const options=instants(form.elements[name].value);
    const select=form.elements[name+'Offset'];
    const previous=selected ?? Number(select.value);
    select.replaceChildren();
    select.parentElement.hidden=options.length!==2;
    for (const [index,ms] of options.entries()) {
      select.add(new Option(index===0?'First · UTC+02':'Second · UTC+01',String(ms)));
    }
    if(options.includes(previous)) select.value=String(previous);
    return options.includes(previous)?previous:options[0];
  }
  function mount(host) {
    const form=document.createElement('form');form.className='time-filter';
    form.innerHTML='<details><summary><span aria-hidden="true">◷</span> Date &amp; time <output></output></summary><div class="time-settings"><div class="time-presets"><button type="button" data-preset="full">Full year</button><button type="button" data-preset="month">August</button><button type="button" data-preset="week">Final week</button><button type="button" data-preset="day">Final day</button></div><p class="time-zone">Basel local time · Europe/Zurich</p><div class="time-fields"><label>From<input required name="from" type="datetime-local"></label><label>To<input required name="to" type="datetime-local"></label><label class="occurrence" hidden>From occurrence<select name="fromOffset"></select></label><label class="occurrence" hidden>To occurrence<select name="toOffset"></select></label><button type="submit">Apply range</button></div><p class="time-error" role="alert"></p><p>The range stops at the To time. For a full day, use midnight to the following midnight. Totals use an illustrative hourly profile.</p></div></details><small></small>';
    const details=form.querySelector('details');
    for(const input of form.querySelectorAll('input')){
      input.min=min;input.max=max;
      input.oninput=()=>{updateOccurrences(form,input.name);form.querySelector('.time-error').textContent=''};
    }
    form.onsubmit=e=>{
      e.preventDefault();
      const a=updateOccurrences(form,'from'), b=updateOccurrences(form,'to');
      const error=form.querySelector('.time-error');
      if(a===undefined||b===undefined){error.textContent='That local time is skipped when Basel clocks move forward. Choose another time.';return}
      if(!valid(a,b)){error.textContent='The To time must be later than From and within the baseline dates.';return}
      details.open=false;commit(a,b);
    };
    form.querySelectorAll('[data-preset]').forEach(button=>button.onclick=()=>{
      const wall=({full:min,month:'2026-08-01T00:00',week:'2026-08-25T00:00',day:'2026-08-31T00:00'})[button.dataset.preset];
      details.open=false;commit(instants(wall)[0],last);
    });
    host.append(form);
  }
  document.addEventListener('DOMContentLoaded',()=>{
    document.querySelectorAll('.time-host').forEach(mount); sync();
    document.dispatchEvent(new Event('timelinechange'));
  });
  return api;
})();

document.addEventListener('DOMContentLoaded',()=>{
  const footer=document.querySelector('.wrap > footer');
  if(!footer)return;
  new IntersectionObserver(([entry])=>{
    document.documentElement.classList.toggle('footer-in-view',entry.isIntersecting);
  }).observe(footer);
});

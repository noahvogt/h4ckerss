'use strict';

const metrics = {
  cost_chf: { label: 'Digital cost', prefix: 'CHF ' },
  energy_kwh: { label: 'Estimated electricity', suffix: ' kWh' },
  co2_kg: { label: 'Location-based CO₂', suffix: ' kg CO₂' },
};
const locations = { CH: 'Zurich', DE: 'Frankfurt', IE: 'Dublin', EU: 'EU (mixed)', unknown: 'Unknown location' };
const categories = { cloud: 'Cloud', server: 'Servers', ai: 'AI', saas: 'SaaS' };
const fields = Object.keys(metrics);
const number = new Intl.NumberFormat('en-CH', { maximumFractionDigits: 1 });
const percentage = new Intl.NumberFormat('en-CH', { style: 'percent', maximumFractionDigits: 1 });
const month = new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const find = id => document.getElementById(id);
const headquarters = find('basel-marker');
const companyKey = headquarters.dataset.location;
const markers = [...document.querySelectorAll('.marker')];
const regionButtons = [...document.querySelectorAll('[data-region]')];
const panel = find('region-detail');
const closeButton = find('close-detail');
const mapStage = find('map-stage');

const example = {
  period_start: '2025-09-01',
  period_end: '2026-08-31',
  illustrative: true,
  rows: [
    { category: 'cloud', location: 'CH', department: 'Consulting', tool: 'Production data platform', cost_chf: 42500, energy_kwh: 14000, co2_kg: 1470 },
    { category: 'cloud', location: 'CH', department: 'Finance', tool: 'Finance database', cost_chf: 16000, energy_kwh: 5000, co2_kg: 525 },
    { category: 'server', location: 'DE', department: 'Consulting', tool: 'GPU server', cost_chf: 11500, energy_kwh: 4500, co2_kg: 1710 },
    { category: 'cloud', location: 'DE', department: 'IT', tool: 'Development data platform', cost_chf: 19000, energy_kwh: 8700, co2_kg: 3306 },
    { category: 'server', location: 'IE', department: 'IT', tool: 'Test environments', cost_chf: 14000, energy_kwh: 3000, co2_kg: 840 },
    { category: 'cloud', location: 'IE', department: 'IT', tool: 'Build service', cost_chf: 3800, energy_kwh: 1200, co2_kg: 336 },
    { category: 'ai', location: 'EU', department: 'Sales', tool: 'AI subscriptions', cost_chf: 8500, energy_kwh: null, co2_kg: null },
    { category: 'saas', location: 'EU', department: 'Sales', tool: 'CRM platform', cost_chf: 7000, energy_kwh: null, co2_kg: null },
  ],
};

// These observations refer to the supplied case files and the bundled example period.
const caseEvidence = {
  DE: {
    waste: true,
    title: 'Development cluster was rarely active',
    finding: 'The cluster ran for 8,640 hours. It was actively used for about 750 hours (9% of that time).',
    constraint: 'Keep the cluster and GPU available during quarterly model training.',
    sources: [
      'data_platform_usage.csv · development cluster (dp-dev)',
      'server_metrics_weekly.csv · GPU server (gpu-ml-01) averaged 9.2% utilisation across 52 weekly records',
      'IT tickets T-1053 and T-1101 · quarterly training',
    ],
  },
  CH: {
    title: 'Finance needs the platform at month-end',
    finding: 'Finance needs the production platform until about 04:00 on the last three working days of each month.',
    sources: ['IT ticket T-1029 · production platform (dp-prod)'],
  },
  IE: {
    waste: true,
    title: 'Test servers used little of their capacity',
    finding: 'Across 364 recorded days, daily charges covered the equivalent of 64 vCPUs running around the clock. Median daily CPU utilisation was 6.3%.',
    constraint: 'Check the release freeze and keep disaster recovery available.',
    sources: ['aws_costs.csv · test environment (vm-test), 1,536 vCPU-hours per recorded day', 'IT tickets T-1058, T-1094 and T-1204 · capacity and operating requirements'],
  },
  EU: {
    waste: true,
    title: '67 AI seats showed no activity',
    finding: 'August 2026 subscription records show inactive seats across ChatGPT Team, Claude Team and Microsoft Copilot.',
    constraint: 'Check cancellation and renewal terms before counting savings.',
    sources: ['ai_subscriptions.csv · August 2026, Final rows'],
  },
};

let baseline = example;
let selectedLocation = null;
let metric = 'co2_kg';
let group = 'tool';
let liveMap;

function evidenceFor(key) {
  return baseline === example ? caseEvidence[key] : null;
}

function appendWasteBadge(element) {
  const badge = document.createElement('span');
  badge.className = 'waste-chip';
  badge.setAttribute('aria-hidden', 'true');
  badge.textContent = '!';
  element.append(badge);
}

function summarise(rows) {
  return Object.fromEntries(fields.map(field => {
    const known = rows.map(row => row[field]).filter(value => value !== null);
    return [field, { value: known.length ? known.reduce((a, b) => a + b, 0) : null, partial: known.length < rows.length }];
  }));
}

function format(field, value, withUnit = true) {
  if (value === null) return '—';
  const { prefix = '', suffix = '' } = metrics[field];
  const formatted = number.format(value);
  return withUnit ? `${prefix}${formatted}${suffix}` : formatted;
}

function renderTotals(id, totals, orderedFields = fields) {
  find(id).replaceChildren(...orderedFields.map(field => {
    const row = document.createElement('div');
    if (field === 'energy_kwh') row.className = 'energy-total';
    const label = document.createElement('dt');
    const amount = document.createElement('dd');
    label.textContent = metrics[field].label;
    const { value, partial } = totals[field];
    amount.textContent = format(field, value);
    row.append(label, amount);
    if (partial) {
      const coverage = document.createElement('small');
      coverage.textContent = value === null ? 'Unavailable' : 'Partial total';
      row.append(coverage);
    }
    return row;
  }));
}

function drawArrows() {
  if (liveMap) return;
  const canvas = find('map-arrows');
  const bounds = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(ratio, ratio);
  const centre = element => {
    const rect = element.getBoundingClientRect();
    return [rect.left + rect.width / 2 - bounds.left, rect.top + rect.height / 2 - bounds.top];
  };
  const [x, y] = centre(headquarters);
  for (const marker of markers) {
    const [tx, ty] = centre(marker);
    const angle = Math.atan2(ty - y, tx - x);
    const radius = marker.querySelector('.bubble').offsetWidth / 2 + 10;
    const endX = tx - radius * Math.cos(angle);
    const endY = ty - radius * Math.sin(angle);
    const active = marker.dataset.location === selectedLocation;
    ctx.strokeStyle = active ? '#4e6d36' : '#526e7c';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = active ? 2.5 : 1.5;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(endX, endY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    for (const side of [-1, 1]) ctx.lineTo(endX - 8 * Math.cos(angle + side * .48), endY - 8 * Math.sin(angle + side * .48));
    ctx.closePath();
    ctx.fill();
  }
}

function renderMap(regionTotals, companyTotals) {
  const companySelected = selectedLocation === companyKey;
  const hq = companyTotals[metric];
  const max = Math.max(0, hq.value ?? 0, ...markers.map(marker => regionTotals[marker.dataset.location][metric].value ?? 0));
  const fractionFor = value => value > 0 ? Math.sqrt(value / max) : 0;
  const hqFraction = fractionFor(hq.value);
  const hasDashedBubble = hqFraction === 0
    || markers.some(marker => !(regionTotals[marker.dataset.location][metric].value > 0));
  const hqLabel = hq.value === null ? 'Unavailable' : format(metric, hq.value) + (hq.partial ? '*' : '');
  const hqAccessibleLabel = `Basel HQ, company total, ${hq.value === null ? 'unavailable' : format(metric, hq.value)}${hq.partial ? ', partial total' : ''}`;
  headquarters.style.setProperty('--bubble', `${Math.max(13, hqFraction * 48)}px`);
  headquarters.querySelector('.hq-value').textContent = hqLabel;
  headquarters.setAttribute('aria-label', hqAccessibleLabel);
  headquarters.setAttribute('aria-expanded', String(companySelected));
  headquarters.toggleAttribute('data-empty', !hqFraction);
  liveMap?.updateHeadquarters({ selected: companySelected, fraction: hqFraction, label: hqAccessibleLabel, amount: hqLabel });
  let showWasteLegend = false;
  for (const marker of markers) {
    const key = marker.dataset.location;
    const { value, partial } = regionTotals[key][metric];
    const positive = value !== null && value > 0;
    const fraction = fractionFor(value);
    const selected = key === selectedLocation;
    marker.style.setProperty('--bubble', `${Math.max(13, fraction * 48)}px`);
    marker.toggleAttribute('data-empty', !positive);
    marker.setAttribute('aria-expanded', String(selected));
    const label = value === null ? 'unavailable' : `${format(metric, value)}${partial ? ', partial total' : ''}`;
    const waste = Boolean(evidenceFor(key)?.waste);
    const accessibleLabel = `${locations[key]}, ${label}${waste ? ', waste identified' : ''}`;
    marker.toggleAttribute('data-waste', waste);
    marker.setAttribute('aria-label', accessibleLabel);
    liveMap?.update(key, { fraction, selected, label: accessibleLabel, empty: !positive, waste });
    showWasteLegend ||= waste;
  }
  for (const button of regionButtons) {
    const key = button.dataset.region;
    button.hidden = !baseline.rows.some(row => row.location === key);
    const waste = !button.hidden && Boolean(evidenceFor(key)?.waste);
    button.toggleAttribute('data-waste', waste);
    button.setAttribute('aria-label', `${locations[key]}${waste ? ', waste identified' : ''}`);
    button.setAttribute('aria-expanded', String(selectedLocation === key));
    showWasteLegend ||= waste;
  }
  find('waste-legend').hidden = !showWasteLegend;
  find('other-regions').hidden = regionButtons.every(button => button.hidden);
  find('map-caption').textContent = [
    hasDashedBubble ? 'Dashed circles indicate zero, negative or unavailable values.' : '',
    hq.value !== null && hq.partial ? '* Partial company total.' : '',
  ].filter(Boolean).join(' ');
  drawArrows();
}

function groupTotals(rows, field) {
  const groups = new Map();
  for (const row of rows) {
    const key = row[field] ?? '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  return [...groups].map(([label, items]) => [label, summarise(items)]);
}

function renderGroupNote(rows) {
  const departments = new Set(rows.map(row => row.department));
  const tools = new Set(rows.map(row => row.tool));
  let message = '';
  if (departments.size === 1 && tools.size > 1) {
    const [department] = departments;
    message = `${department} covers ${number.format(tools.size)} tools.`;
  } else if (departments.size === tools.size && tools.size > 1) {
    const assignments = new Set(rows.map(row => JSON.stringify([row.tool, row.department])));
    if (assignments.size === tools.size) {
      message = 'Each tool belongs to a different department.';
    }
  }
  const note = find('group-note');
  note.textContent = message;
  note.hidden = !message;
}

function renderCategorySummary(rows) {
  const totals = new Map(groupTotals(rows, 'category'));
  const labels = Object.entries(categories);
  if (totals.has('')) labels.push(['', 'Uncategorised']);
  find('category-summary').replaceChildren(...labels.map(([key, name]) => {
    const item = document.createElement('li');
    const label = document.createElement('span');
    const amount = document.createElement('strong');
    const entry = totals.get(key)?.[metric];
    label.textContent = name;
    amount.textContent = !entry || entry.value === null ? 'Unavailable' : format(metric, entry.value) + (entry.partial ? '*' : '');
    item.append(label, amount);
    return item;
  }));
}

function renderBreakdown(sorted, totals) {
  find('group-heading').textContent = group === 'department' ? 'Department' : 'Tool';
  const tableRows = sorted.map(([label, values]) => {
    const row = document.createElement('tr');
    const heading = document.createElement('th');
    heading.scope = 'row';
    heading.textContent = label;
    row.append(heading);
    for (const field of fields) {
      const cell = document.createElement('td');
      const { value, partial } = values[field];
      cell.textContent = `${format(field, value, false)}${value !== null && partial ? '*' : ''}`;
      row.append(cell);
    }
    return row;
  });
  if (!tableRows.length) {
    const row = document.createElement('tr');
    const cell = row.insertCell();
    cell.colSpan = 4;
    cell.textContent = 'No rows for this region.';
    tableRows.push(row);
  }
  find('breakdown').replaceChildren(...tableRows);
  find('coverage-note').textContent = fields.some(field => totals[field].partial) ? '— unavailable. * partial total.' : '';
}

function render() {
  const regionRows = Object.fromEntries(Object.keys(locations).map(key => [key, baseline.rows.filter(row => row.location === key)]));
  const regionTotals = Object.fromEntries(Object.entries(regionRows).map(([key, rows]) => [key, summarise(rows)]));
  find('data-badge').textContent = baseline.illustrative ? 'Illustrative data' : 'Imported baseline';
  find('baseline-period').textContent = `Baseline · ${month.format(new Date(baseline.period_start))} – ${month.format(new Date(baseline.period_end))}`;
  const companyTotals = summarise(baseline.rows);
  renderTotals('annual-totals', companyTotals);
  renderCategorySummary(baseline.rows);
  renderMap(regionTotals, companyTotals);
  panel.hidden = selectedLocation === null;
  if (panel.hidden) return;

  const companySelected = selectedLocation === companyKey;
  const rows = companySelected ? baseline.rows : regionRows[selectedLocation];
  const totals = companySelected ? companyTotals : regionTotals[selectedLocation];
  find('detail-title').textContent = companySelected ? 'Basel HQ' : locations[selectedLocation];
  find('detail-period').textContent = find('baseline-period').textContent;
  const note = find('detail-note');
  note.hidden = !companySelected && Object.hasOwn(cityCoordinates, selectedLocation);
  note.textContent = companySelected
    ? 'Company-wide digital services across all deployment regions, including services without a known city.'
    : selectedLocation === 'EU'
      ? 'The case groups some AI and SaaS services at EU level. Their deployment cities are unspecified.'
      : 'The exports do not identify a specific deployment city.';
  find('hq-coverage').hidden = !companySelected;
  renderTotals('region-totals', totals, ['energy_kwh', 'cost_chf', 'co2_kg']);
  const shares = companySelected ? [] : [
    ['cost_chf', 'digital spend'],
    ['co2_kg', 'estimated CO₂'],
  ].flatMap(([field, label]) => {
    const total = companyTotals[field];
    const part = totals[field].value;
    return part !== null && part >= 0 && total.value > 0 && part <= total.value
      ? [`${percentage.format(part / total.value)} of ${total.partial ? 'known ' : ''}company ${label}`]
      : [];
  });
  find('company-share').textContent = shares.join(' · ');
  const rankBy = totals[metric].value === null && totals.cost_chf.value !== null ? 'cost_chf' : metric;
  const sorted = groupTotals(rows, group)
    .sort((a, b) => (b[1][rankBy].value ?? -Infinity) - (a[1][rankBy].value ?? -Infinity));
  renderGroupNote(rows);
  renderDrivers(sorted, rankBy, totals[rankBy], companySelected);
  renderCaseEvidence();
  renderBreakdown(sorted, totals);
}

function renderDrivers(sorted, rankBy, total, companySelected) {
  const amounts = sorted.map(([name, values]) => [name, values[rankBy]])
    .filter(([, amount]) => amount.value !== null);
  const top = amounts.slice(0, 3);
  const showShares = total.value > 0 && amounts.every(([, amount]) => amount.value >= 0);
  const label = { cost_chf: 'cost', energy_kwh: 'electricity', co2_kg: 'CO₂' }[rankBy];
  find('drivers').hidden = !top.length;
  find('drivers-title').textContent = `Top ${label} drivers by ${group}`;
  find('drivers-share-label').textContent = showShares
    ? `Share of ${total.partial ? 'known ' : ''}${companySelected ? 'company' : 'regional'} ${label}`
    : '';
  find('driver-list').replaceChildren(...top.map(([name, { value, partial }]) => {
    const row = document.createElement('li');
    const header = document.createElement('div');
    const nameLabel = document.createElement('span');
    const amount = document.createElement('strong');
    nameLabel.textContent = name;
    amount.textContent = format(rankBy, value) + (partial ? '*' : '');
    header.append(nameLabel, amount);
    row.append(header);
    if (showShares) {
      const share = value / total.value;
      const track = document.createElement('div');
      const bar = document.createElement('span');
      const shareText = document.createElement('small');
      track.className = 'driver-track';
      track.setAttribute('aria-hidden', 'true');
      bar.style.width = `${Math.min(100, share * 100)}%`;
      shareText.textContent = percentage.format(share);
      track.append(bar);
      row.append(track, shareText);
    }
    return row;
  }));
}

function renderCaseEvidence() {
  const evidence = evidenceFor(selectedLocation);
  find('case-evidence').hidden = !evidence;
  find('case-evidence').toggleAttribute('data-waste', Boolean(evidence?.waste));
  if (!evidence) return;
  find('case-evidence-title').textContent = evidence.title;
  find('case-evidence-finding').textContent = evidence.finding;
  const constraint = find('case-evidence-constraint');
  constraint.textContent = evidence.constraint ?? '';
  constraint.hidden = !evidence.constraint;
  find('case-evidence-source-list').replaceChildren(...evidence.sources.map(source => {
    const item = document.createElement('li');
    item.textContent = source;
    return item;
  }));
}

function openRegion(key) {
  selectedLocation = key;
  find('case-evidence-sources').open = false;
  render();
  panel.scrollTop = 0;
  closeButton.focus({ preventScroll: true });
}

function visibleMarker(key) {
  const selector = liveMap ? '.geographic-map' : '.schematic';
  return mapStage.querySelector(selector + ' [data-location="' + key + '"]');
}

function closeRegion() {
  const key = selectedLocation;
  selectedLocation = null;
  render();
  const trigger = visibleMarker(key) ?? regionButtons.find(button => button.dataset.region === key);
  trigger?.focus({ preventScroll: true });
}

function validate(input) {
  const validDate = date => typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(date));
  if (!validDate(input?.period_start) || !validDate(input?.period_end) || input.period_start > input.period_end) {
    throw new Error('Use period_start and period_end in YYYY-MM-DD format.');
  }
  if (!Array.isArray(input.rows) || !input.rows.length || input.rows.some(row => !row || !Object.hasOwn(locations, row.location)
    || (row.category != null && !Object.hasOwn(categories, row.category))
    || ![row.department, row.tool].every(value => typeof value === 'string' && value.trim())
    || fields.some(field => row[field] !== null && (!Number.isFinite(row[field]) || (field !== 'cost_chf' && row[field] < 0))))) {
    throw new Error('Each row needs a valid location, department, tool, and numeric or null metrics.');
  }
}

for (const marker of markers) {
  appendWasteBadge(marker.querySelector('.marker-label'));
  marker.addEventListener('click', () => openRegion(marker.dataset.location));
}
headquarters.addEventListener('click', () => openRegion(companyKey));
for (const button of regionButtons) {
  appendWasteBadge(button);
  button.addEventListener('click', () => openRegion(button.dataset.region));
}
closeButton.addEventListener('click', closeRegion);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && selectedLocation !== null) {
    event.preventDefault();
    closeRegion();
  }
});
for (const key of ['metric', 'group']) {
  const controls = [...document.querySelectorAll(`[data-${key}]`)];
  for (const button of controls) button.addEventListener('click', () => {
    if (key === 'metric') metric = button.dataset.metric;
    else group = button.dataset.group;
    for (const control of controls) control.setAttribute('aria-pressed', String(control === button));
    render();
  });
}
find('data-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const input = JSON.parse(await file.text());
    validate(input);
    baseline = input;
    selectedLocation = null;
    render();
    find('import-status').textContent = `Loaded ${file.name}.`;
  } catch (error) {
    find('import-status').textContent = `Could not load ${file.name}. ${error.message} The previous baseline is still shown.`;
  } finally {
    event.target.value = '';
  }
});

find('data-import').hidden = new URLSearchParams(window.location.search).get('dev') !== '1';
render();
new ResizeObserver(drawArrows).observe(mapStage);

if (window.location.protocol.startsWith('http')) {
  find('map-status').textContent = 'Loading geographic map…';
  createGeographicMap(find('geographic-map'), headquarters, markers, openRegion).then(map => {
    const focused = document.activeElement.closest('.schematic') ? document.activeElement.dataset.location : null;
    liveMap = map;
    mapStage.setAttribute('data-live', '');
    find('map-status').textContent = '';
    render();
    if (focused) visibleMarker(focused)?.focus();
  }).catch(() => {
    find('map-status').textContent = 'Geographic map unavailable. Showing a schematic.';
  });
} else {
  find('map-status').textContent = 'Showing a schematic. Open the local web preview for the geographic map.';
}

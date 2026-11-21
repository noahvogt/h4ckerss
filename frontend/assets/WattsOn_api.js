(function () {
  const endpointNames = {
    health: "/api/health",
    baseline: "/api/baseline",
    package: "/api/package?approvals=true&alternatives=5",
    measures: "/api/measures",
    contradictions: "/api/rules/contradictions",
    approvals: "/api/approvals",
  };
  const exactFrontendCoverage = {
    M1: ["M-gpu-ml-pause"],
    M3: ["M-dp-prod-schedule"],
    M4: ["M-vm-test-downsize"],
  };
  const mockedFrontendCoverage = {
    M2: "Frontend combines backend M-dp-dev-pause and M-dp-dev-relocate into one mocked recommendation.",
    M5: "Frontend combines AI seat cleanup across ChatGPT, Copilot and Claude; backend exposes those as separate measures.",
    M6: "Frontend SaaS card uses a broader mocked seat/license estimate than the backend package shape.",
    M7: "Frontend marketing model-routing estimate has no exact backend measure; backend exposes M-ai-assistant-model.",
    M8: "Frontend log-retention recommendation is mocked; no backend measure currently exposes logs retention.",
    forecast: "Forecast scenarios are frontend-only controls; backend has no forecast endpoint.",
    mapSites: "Local map pins, site-level profiles and Google Maps zoom metadata are frontend-only demo data.",
  };
  const defaultBase = location.protocol === "file:" ? "http://127.0.0.1:8000" : location.origin;
  const params = new URLSearchParams(location.search);
  const baseUrl = (params.get("api") || localStorage.getItem("wattsonApiBase") || defaultBase).replace(/\/$/, "");
  const state = { baseUrl, ok: false, data: {}, errors: {}, missing: mockedFrontendCoverage };

  function url(path) {
    return baseUrl + path;
  }

  async function json(path, options) {
    const response = await fetch(url(path), {
      headers: { "Accept": "application/json", ...(options && options.headers) },
      ...options,
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  function fmt(n) {
    return Math.round(Number(n || 0)).toLocaleString("en-CH");
  }

  function ensureStatus() {
    if (document.getElementById("apiStatus")) return document.getElementById("apiStatus");
    const style = document.createElement("style");
    style.textContent = ".api-status{position:fixed;left:max(12px,env(safe-area-inset-left));bottom:max(12px,env(safe-area-inset-bottom));z-index:80;max-width:min(430px,calc(100vw - 24px));font:600 12px system-ui,sans-serif;color:#16231b;background:#fff;border:1px solid #d7e1d7;border-radius:12px;box-shadow:0 10px 28px #1023191f;overflow:hidden}.api-status summary{cursor:pointer;list-style:none;padding:9px 12px;display:flex;gap:8px;align-items:center}.api-status summary::-webkit-details-marker{display:none}.api-status summary:before{content:'';width:8px;height:8px;border-radius:50%;background:#d97706;box-shadow:0 0 0 3px #d9770624}.api-status[data-live=true] summary:before{background:#16a34a;box-shadow:0 0 0 3px #16a34a24}.api-status[data-live=false] summary:before{background:#dc2626;box-shadow:0 0 0 3px #dc262624}.api-status div{padding:0 12px 11px;color:#53625b;line-height:1.45}.api-status b{color:#16231b}.api-status ul{margin:7px 0 0 18px;padding:0}.api-status li{margin:3px 0}.api-status code{font:600 11px ui-monospace,monospace;background:#f2f5f1;border-radius:5px;padding:1px 4px}";
    document.head.append(style);
    const box = document.createElement("details");
    box.id = "apiStatus";
    box.className = "api-status";
    box.innerHTML = "<summary>Checking API...</summary><div></div>";
    document.body.append(box);
    return box;
  }

  function renderStatus() {
    const box = ensureStatus();
    const failed = Object.entries(state.errors).map(([name, message]) => `<li><code>${name}</code>: ${message}</li>`).join("");
    const missing = Object.entries(state.missing).map(([name, message]) => `<li><code>${name}</code>: ${message}</li>`).join("");
    box.dataset.live = String(state.ok);
    box.querySelector("summary").textContent = state.ok ? `API live at ${baseUrl}` : "Mock data active";
    box.querySelector("div").innerHTML = state.ok
      ? `<b>Backend connected.</b> Exact matches are hydrated where contracts line up. Frontend-only data stays mocked.<ul>${missing}</ul>${failed ? `<p><b>Endpoint issues</b></p><ul>${failed}</ul>` : ""}`
      : `<b>Backend unavailable.</b> The frontend is running with its built-in mocked data.<ul>${failed || "<li>Could not reach the API.</li>"}</ul>`;
  }

  function backendMeasureIdsForFrontend(frontendId) {
    return exactFrontendCoverage[frontendId.toUpperCase()] || [];
  }

  function selectedBackendIdsFromApprovals() {
    const ids = [];
    const rejected = new Set();
    document.querySelectorAll("#approvals .card").forEach(card => {
      const decision = card.querySelector(".stamp")?.dataset.state || "pending";
      const mapped = backendMeasureIdsForFrontend(card.dataset.measure || "");
      if (decision === "no") {
        mapped.forEach(id => rejected.add(id));
        return;
      }
      ids.push(...mapped);
    });
    const packageIds = state.data.package?.summary?.measures || [];
    return [...new Set([...packageIds.filter(id => !rejected.has(id)), ...ids])];
  }

  async function evaluateApprovals() {
    if (!state.ok || !state.data.package) return null;
    const ids = selectedBackendIdsFromApprovals();
    if (!ids.length) return null;
    try {
      const evaluated = await json("/api/package/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ measure_ids: ids }),
      });
      state.data.evaluation = evaluated;
      return evaluated;
    } catch (error) {
      state.errors.evaluate = error.message;
      renderStatus();
      return null;
    }
  }

  async function saveApproval(frontendId, approvalState) {
    if (!state.ok) return null;
    try {
      const saved = await json(`/api/approvals/${encodeURIComponent(frontendId.toLowerCase())}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: approvalState }),
      });
      state.data.approvals = saved;
      return saved;
    } catch (error) {
      state.errors.approvals = error.message;
      renderStatus();
      return null;
    }
  }

  function applySavedApprovals() {
    const decisions = state.data.approvals?.decisions;
    if (!decisions || !window.renderApproval) return;
    document.querySelectorAll("#approvals .card").forEach(card => {
      const decision = decisions[(card.dataset.measure || "").toLowerCase()];
      if (!decision) return;
      window.renderApproval(card, decision);
      const pending = decision === "pending";
      card.querySelectorAll(".ok:not(.stamp),.no:not(.stamp)").forEach(action => action.hidden = !pending);
      const undo = card.querySelector(".revise");
      if (undo) undo.hidden = pending;
    });
    if (window.updateApprovalSummary) window.updateApprovalSummary();
  }

  function decoratePackagePage() {
    const pkg = state.data.package;
    if (!pkg || !document.getElementById("go")) return;
    const summary = pkg.summary;
    const meta = document.querySelector("#go .meta");
    if (meta) {
      meta.textContent = `API package · -${(summary.cost_reduction * 100).toFixed(1)}% CHF · -${((summary.co2_reduction || 0) * 100).toFixed(1)}% CO2`;
    }
    const cta = document.querySelector(".cta p");
    if (cta) {
      cta.insertAdjacentHTML("beforeend", ` <span title="From /api/package">API: CHF ${fmt(summary.savings_chf)} savings, CHF ${fmt(summary.effort_chf)} effort.</span>`);
    }
    applySavedApprovals();
  }

  function decorateForecastPage() {
    const pkg = state.data.package;
    if (!pkg || !document.getElementById("measureList")) return;
    const sources = document.getElementById("sources");
    if (sources) {
      sources.insertAdjacentHTML("afterbegin", `<p><b>Backend package available</b><br>/api/package reports CHF ${fmt(pkg.summary.savings_chf)} savings and CHF ${fmt(pkg.summary.effort_chf)} effort. Forecast-specific controls remain mocked because there is no backend forecast endpoint.</p>`);
    }
  }

  function decorateBaselinePage() {
    const baseline = state.data.baseline;
    if (!baseline || !document.getElementById("geoWindow")) return;
    const nav = document.querySelector(".nav-r");
    if (nav && baseline.annual) {
      nav.textContent = `API baseline ${fmt(baseline.annual.cost_chf)} CHF · partial CO2 coverage`;
    }
  }

  async function boot() {
    ensureStatus();
    const entries = await Promise.all(Object.entries(endpointNames).map(async ([name, path]) => {
      try {
        return [name, await json(path), null];
      } catch (error) {
        return [name, null, error];
      }
    }));
    for (const [name, data, error] of entries) {
      if (error) state.errors[name] = error.message;
      else state.data[name] = data;
    }
    state.ok = Boolean(state.data.health && state.data.baseline && state.data.package && state.data.measures);
    renderStatus();
    if (!state.ok) return;
    decorateBaselinePage();
    decoratePackagePage();
    decorateForecastPage();
  }

  window.WattsOnApi = {
    state,
    json,
    evaluateApprovals,
    saveApproval,
    applySavedApprovals,
    backendMeasureIdsForFrontend,
    selectedBackendIdsFromApprovals,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

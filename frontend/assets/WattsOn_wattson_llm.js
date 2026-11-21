(function () {
  const chat = document.getElementById("watson-chat");
  const input = document.getElementById("chIn");
  const messages = document.getElementById("msgs");
  if (!chat || !input || !messages || typeof window.ask !== "function") return;

  const originalAsk = window.ask.bind(window);
  const history = [];
  let suggestionTimer = 0;
  let lastSuggestionAt = 0;
  let activeRequest = null;

  function text(selector) {
    return Array.from(document.querySelectorAll(selector))
      .map(el => el.textContent.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 12);
  }

  function slimApi() {
    const data = window.WattsOnApi?.state?.data || {};
    return {
      health: data.health,
      baselineAnnual: data.baseline?.annual,
      packageSummary: data.package?.summary,
      packageTargets: data.package?.targets,
      packageMeasures: data.package?.measures?.map(m => ({
        id: m.measure_id, title: m.title, status: m.status, savings_chf: m.savings_chf,
        savings_co2_kg: m.savings_co2_kg, decided_by: m.decided_by, sources: m.sources
      })),
      contradictions: data.contradictions,
      approvals: data.approvals?.decisions,
    };
  }

  function pageSpecific() {
    const out = {};
    try {
      if (window.timeline) out.timeline = { label: timeline.label, full: timeline.full, share: timeline.share };
      if (window.active) out.selectedRegion = {
        code: active.code, name: active.name, cost_chf: active.chf, energy_kwh: active.energy, co2_kg: active.co2,
        profile: window.profiles?.[active.code]
      };
      if (window.caseData) out.caseDataSummary = {
        baseline: window.baseline,
        measures: window.caseData.measures,
        topLedger: window.caseData.ledger?.slice?.(0, 12),
        sourcePath: window.caseData.dataPath,
      };
    } catch {}
    out.controls = Array.from(document.querySelectorAll("select,input[type=range],input[type=checkbox]")).slice(0, 24).map(el => ({
      id: el.id || el.name || el.getAttribute("aria-label") || el.type,
      value: el.type === "checkbox" ? el.checked : el.value,
    }));
    out.approvalCards = Array.from(document.querySelectorAll("#approvals .card")).map(card => ({
      measure: card.dataset.measure,
      status: card.querySelector(".stamp")?.dataset.state || "pending",
      title: card.querySelector("h3,b")?.textContent?.trim(),
    }));
    out.importedSources = Array.from(document.querySelectorAll("#personalList button")).map(button => button.textContent.replace(/\s+/g, " ").trim()).slice(0, 12);
    return out;
  }

  function captureContext() {
    return {
      url: location.pathname + location.search,
      title: document.title,
      headings: text("h1,h2,.section-title b,.section-title h2"),
      visibleHighlights: text(".hero-stats,.stat,.kpi,.review-grid,.trail,.source-foot,.nav-r,.watson-thought:not([hidden])"),
      pageSpecific: pageSpecific(),
      api: slimApi(),
    };
  }

  function addBotHtml(html, typing) {
    const node = document.createElement("div");
    node.className = "msg bot" + (typing ? " typing" : "");
    node.innerHTML = typing ? "<i></i><i></i><i></i>" : html;
    messages.append(node);
    messages.scrollTop = messages.scrollHeight;
    return node;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function askLlm(question, options = {}) {
    if (activeRequest) return false;
    const request = {
      suggestion: Boolean(options.suggestion),
      controller: new AbortController(),
      typing: addBotHtml("", true),
    };
    activeRequest = request;
    try {
      const response = await fetch("/api/wattson/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        signal: request.controller.signal,
        body: JSON.stringify({
          message: question,
          page: document.title,
          ui_context: captureContext(),
          history: history.slice(-8),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Wattson backend failed");
      if (request.controller.signal.aborted) return false;
      const label = data.live ? "" : '<small class="detail-note">Local fallback · set OPENAI_API_KEY for live LLM</small>';
      addBotHtml((options.suggestion ? "<b>Suggestion</b><br>" : "") + escapeHtml(data.reply).replace(/\n/g, "<br>") + label);
      history.push({ role: "user", content: question }, { role: "assistant", content: data.reply });
      return true;
    } catch {
      return false;
    } finally {
      request.typing.remove();
      if (activeRequest === request) activeRequest = null;
    }
  }

  window.ask = function wattsonAsk(question) {
    const q = String(question || "").trim();
    if (!q || activeRequest?.suggestion === false) return false;
    clearTimeout(suggestionTimer);
    if (activeRequest) {
      activeRequest.controller.abort();
      activeRequest.typing.remove();
      activeRequest = null;
    }
    const me = document.createElement("div");
    me.className = "msg me";
    me.textContent = q;
    messages.append(me);
    messages.scrollTop = messages.scrollHeight;
    askLlm(q).then(ok => {
      if (!ok) {
        me.remove();
        originalAsk(q);
      }
    });
    return true;
  };

  window.send = function wattsonSend(event) {
    event.preventDefault();
    if (window.ask(input.value)) input.value = "";
  };

  function scheduleSuggestion(reason) {
    if (chat.inert || activeRequest || Date.now() - lastSuggestionAt < 9000) return;
    clearTimeout(suggestionTimer);
    suggestionTimer = setTimeout(() => {
      if (chat.inert || activeRequest) return;
      lastSuggestionAt = Date.now();
      askLlm("Based on the current UI after this action, suggest the single most useful next step. Action: " + reason, { suggestion: true });
    }, 900);
  }

  document.addEventListener("change", event => {
    const el = event.target;
    if (!chat.contains(el) && el.matches("select,input")) scheduleSuggestion(el.id || el.name || el.type);
  }, true);
  document.addEventListener("click", event => {
    if (chat.contains(event.target)) return;
    const el = event.target.closest("button,[data-group],[data-review],.map-pin,.sitePin,.m,.card");
    if (el) scheduleSuggestion((el.textContent || el.id || el.className || "click").trim().slice(0, 80));
  }, true);

  window.WattsonLLM = { captureContext, ask: askLlm };
})();

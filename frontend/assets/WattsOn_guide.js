/* Shared Guide client for the baseline and package pages. */
(() => {
  const chat = document.getElementById("watson-chat");
  const form = chat.querySelector("form");
  const input = chat.querySelector("#chIn");
  const messages = chat.querySelector("#msgs");
  const chips = chat.querySelector("#chips");
  const mode = chat.querySelector("#guide-mode");
  const diagnostics = chat.querySelector("#guide-diagnostics");
  let examplesLoaded = false;
  let loadingExamples = false;
  let pending = false;

  function append(text, kind = "bot") {
    const message = document.createElement("div");
    message.className = `msg ${kind}`;
    const paragraph = document.createElement("p");
    paragraph.className = "guide-answer";
    paragraph.textContent = text;
    message.append(paragraph);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
  }

  function calculationPath(value) {
    if (typeof value !== "string" || !value.startsWith("/api/")) return null;
    const url = new URL(value, location.href);
    return url.origin === location.origin && url.pathname.startsWith("/api/") ?
      url.pathname + url.search : null;
  }

  function addSources(message, sources) {
    const references = new Map();
    for (const source of sources) {
      const reference = source.reference?.trim();
      if (reference) {
        references.set(reference, references.get(reference) ?? calculationPath(source.api_url));
      }
    }
    if (!references.size) return;

    const disclosure = document.createElement("details");
    disclosure.className = "guide-sources";
    const summary = document.createElement("summary");
    summary.textContent = `Sources and calculations (${references.size})`;
    const list = document.createElement("ul");
    for (const [reference, apiPath] of references) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "guide-source-label";
      label.textContent = reference.split("/").pop() || reference;
      label.title = reference;
      item.append(label);
      if (apiPath) {
        const link = document.createElement("a");
        link.href = apiPath;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "API calculations";
        link.setAttribute("aria-label", `API calculations for ${label.textContent}`);
        item.append(" ", link);
      }
      list.append(item);
    }
    disclosure.append(summary, list);
    disclosure.addEventListener("toggle", () => {
      if (!disclosure.open) return;
      const viewport = messages.getBoundingClientRect();
      const bounds = disclosure.getBoundingClientRect();
      if (bounds.bottom > viewport.bottom) {
        messages.scrollTop += Math.min(bounds.bottom - viewport.bottom + 8, bounds.top - viewport.top);
      }
    });
    message.append(disclosure);
  }

  function addDiagnostics(message, {usage, estimated_cost_usd}) {
    const report = document.createElement("div");
    report.className = "guide-diagnostics";
    report.hidden = !diagnostics.checked;
    report.setAttribute("role", "group");
    report.setAttribute("aria-label", "Response diagnostics");
    if (usage) {
      const format = value => value.toLocaleString("en-US", {maximumSignificantDigits: 4});
      const energy = usage.energy_kwh_mid == null ? "unavailable" : `${format(usage.energy_kwh_mid)} kWh`;
      let emissions = "unavailable";
      if (usage.co2e_kg_mid != null) {
        emissions = `${format(usage.co2e_kg_mid)} kg CO₂e`;
        if (usage.grid_location) emissions += ` (${usage.grid_location} grid)`;
      } else if (usage.energy_kwh_mid == null) {
        emissions = "unavailable without an energy estimate";
      } else if (!usage.grid_location) {
        emissions = "unavailable without a deployment grid";
      }
      const cost = estimated_cost_usd == null ? "unavailable" : `USD ${format(estimated_cost_usd)}`;
      const lines = [
        `Provider-reported tokens · ${usage.input_tokens?.toLocaleString("en-US") ?? "unknown"} input, ${usage.output_tokens?.toLocaleString("en-US") ?? "unknown"} output`,
        `Modeled inference energy (mid) · ${energy}`,
        `Modeled inference CO₂e (mid) · ${emissions}`,
        `Estimated API cost · ${cost}`,
      ];
      for (const text of lines) {
        const line = document.createElement("p");
        line.textContent = text;
        report.append(line);
      }
    } else {
      report.textContent = "Provider diagnostics unavailable for this reply.";
    }
    message.append(report);
  }

  function showAnswer(result) {
    const message = append(result.answer);
    addSources(message, result.sources);
    if (result.notice) {
      const notice = document.createElement("small");
      notice.textContent = result.notice;
      message.append(notice);
    }
    addDiagnostics(message, result);
    messages.scrollTop += message.getBoundingClientRect().top - messages.getBoundingClientRect().top - 12;
  }

  function busy(active) {
    pending = active;
    chat.querySelectorAll("form button, #chips button").forEach(button => { button.disabled = active; });
  }

  async function ask(question) {
    if (pending) return;
    busy(true);
    append(question, "me");
    const waiting = append("Looking up the calculations…");
    try {
      const response = await fetch("/api/guide/ask", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question}),
        signal: AbortSignal.timeout(20000),
      });
      if (!response.ok) throw new Error("Guide response failed");
      const result = await response.json();
      mode.textContent = result.mode === "ai" ? "OpenAI · Project evidence" : "Demo mode · Local answers";
      waiting.remove();
      showAnswer(result);
    } catch {
      waiting.remove();
      append("Couldn’t reach the Guide. Open this page from the WattsON backend and try again.");
      if (!input.value) input.value = question;
    } finally {
      busy(false);
    }
  }

  async function open() {
    if (examplesLoaded || loadingExamples) return;
    loadingExamples = true;
    try {
      const response = await fetch("/api/guide/examples", {signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error("Guide examples failed");
      const data = await response.json();
      mode.textContent = data.mode === "ai" ? "OpenAI available" : "Demo mode · Local answers";
      if (data.notice) append(data.notice);
      for (const example of data.examples) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = example.label;
        button.title = example.question;
        button.disabled = pending;
        button.addEventListener("click", () => ask(example.question));
        chips.append(button);
      }
      examplesLoaded = true;
    } catch {
      mode.textContent = "Guide offline · Start the WattsON backend";
    } finally {
      loadingExamples = false;
    }
  }

  diagnostics.addEventListener("change", () => {
    for (const report of messages.querySelectorAll(".guide-diagnostics")) {
      report.hidden = !diagnostics.checked;
    }
  });

  form.addEventListener("submit", event => {
    event.preventDefault();
    const question = input.value.trim();
    if (question && !pending) {
      input.value = "";
      ask(question);
    }
  });
  window.wattsOnGuide = {open};
})();

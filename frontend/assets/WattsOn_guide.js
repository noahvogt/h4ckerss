/* Shared Guide client for the baseline and package pages. */
(() => {
  const chat = document.getElementById("watson-chat");
  const form = chat.querySelector("form");
  const input = chat.querySelector("#chIn");
  const messages = chat.querySelector("#msgs");
  const chips = chat.querySelector("#chips");
  const mode = chat.querySelector("#guide-mode");
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

  function showAnswer(result) {
    const message = append(result.answer);
    if (result.sources.length) {
      const sources = document.createElement("details");
      sources.className = "guide-sources";
      const summary = document.createElement("summary");
      summary.textContent = `Sources and calculations (${result.sources.length})`;
      const list = document.createElement("ul");
      for (const source of result.sources) {
        const item = document.createElement("li");
        item.textContent = source.reference;
        if (source.api_url?.startsWith("/api/")) {
          const link = document.createElement("a");
          link.href = source.api_url;
          link.target = "_blank";
          link.rel = "noopener";
          link.textContent = "Open API evidence";
          item.append(" · ", link);
        }
        list.append(item);
      }
      sources.append(summary, list);
      message.append(sources);
    }
    if (result.notice) {
      const notice = document.createElement("small");
      notice.textContent = result.notice;
      message.append(notice);
    }
    if (result.usage) {
      const usage = result.usage;
      const report = document.createElement("small");
      report.className = "guide-usage";
      const format = value => value == null ? "unknown" :
        value.toLocaleString("en-US", {maximumSignificantDigits: 4});
      let qualifier = ". Deployment grid unknown.";
      if (usage.grid_location) {
        qualifier = ` (${usage.grid_location} grid).`;
      } else if (usage.energy_kwh_mid == null) {
        qualifier = ". A footprint estimate requires both token counts and compatible factors.";
      }
      report.textContent = `Provider tokens: ${usage.input_tokens ?? "unknown"} input, ${usage.output_tokens ?? "unknown"} output. ` +
        `Modeled inference: ${format(usage.energy_kwh_mid)} kWh and ${format(usage.co2e_kg_mid)} kg CO₂e` + qualifier;
      message.append(report);
    } else if (result.mode === "ai") {
      const report = document.createElement("small");
      report.textContent = "Provider token counts and inference footprint are unavailable for this reply.";
      message.append(report);
    }
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
      mode.textContent = result.mode === "ai" ? "AI routing · Project evidence" : "Demo mode · Local answers";
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
      mode.textContent = data.mode === "ai" ? "AI routing available" : "Demo mode · Local answers";
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

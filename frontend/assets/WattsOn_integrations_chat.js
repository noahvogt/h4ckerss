(function () {
  const launcher = document.getElementById("fab");
  const legacyGuide = document.getElementById("guide");
  const chatPanel = document.getElementById("watson-chat");
  const messages = document.getElementById("msgs");
  const chips = document.getElementById("chips");
  const input = document.getElementById("chIn");
  if (!launcher || !chatPanel || !messages) return;

  const footer = document.querySelector(".wrap > footer");
  if (footer) {
    new IntersectionObserver(([entry]) => {
      document.documentElement.classList.toggle("footer-in-view", entry.isIntersecting);
    }).observe(footer);
  }

  const prompts = [
    "Which source should I import first?",
    "Explain AWS and GCP invoice options",
    "What conflicts need review?",
    "Which data is mocked?"
  ];

  function addBot(message) {
    const node = document.createElement("div");
    node.className = "msg bot";
    node.textContent = message;
    messages.append(node);
    messages.scrollTop = messages.scrollHeight;
  }

  function addMe(message) {
    const node = document.createElement("div");
    node.className = "msg me";
    node.textContent = message;
    messages.append(node);
    messages.scrollTop = messages.scrollHeight;
  }

  window.ask = function ask(question) {
    addMe(question);
    if (/aws|gcp|invoice/i.test(question)) {
      addBot("Use Add source, then pick AWS invoices, GCP billing export, or Invoice files. Those connectors are mocked in this app right now; file import is the path that works without a backend cloud connector.");
    } else if (/conflict|review/i.test(question)) {
      addBot("Review Dublin test fleet inventory and the March cloud report gap first. Compare aws_costs.csv, azure_costs.csv, hoster_invoice.csv, server_inventory.csv, and provider_monthly_report.csv.");
    } else if (/mock/i.test(question)) {
      addBot("The Integrations page keeps imported sources in this browser and does not recalculate backend totals yet. The backend still uses the bundled case data.");
    } else {
      addBot("Start with cloud invoices and ownership mappings: AWS/GCP/Azure billing, hoster invoices, mapping_departments_tools.csv, and exchange_rates.csv. Then reconcile conflicts before changing the package.");
    }
  };

  window.send = function send(event) {
    event.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    window.ask(value);
  };

  window.setChatOpen = function setChatOpen(open) {
    chatPanel.inert = !open;
    launcher.setAttribute("aria-expanded", String(open));
    document.getElementById("watsonAction").textContent = open ? "Close chat" : "Ask Wattson";
    if (open && !messages.children.length) {
      addBot("I can inspect this Integrations page, your current source filters, imported mock sources, and the backend package context.");
      for (const prompt of prompts) {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.textContent = prompt;
        chip.onclick = () => window.ask(prompt);
        chips.append(chip);
      }
    }
    (open ? input : launcher).focus({ preventScroll: true });
  };
  window.openChat = () => window.setChatOpen(true);
  window.closeChat = () => window.setChatOpen(false);
  launcher.onclick = () => window.setChatOpen(chatPanel.inert);
  if (legacyGuide) legacyGuide.onclick = () => window.setChatOpen(true);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !chatPanel.inert) window.closeChat();
  });
})();

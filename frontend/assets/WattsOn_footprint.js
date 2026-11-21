(() => {
  const section = document.getElementById("guide-footprint");
  const status = section.querySelector("[data-footprint-status]");
  const values = section.querySelector("[data-footprint-values]");
  const method = section.querySelector("[data-footprint-method]");
  const refresh = section.querySelector("[data-footprint-refresh]");
  const format = new Intl.NumberFormat("en-US", {maximumSignificantDigits: 6});

  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    status.textContent = "Loading Guide footprint…";
    try {
      const response = await fetch("/api/guide/footprint", {
        cache: "no-store",
        signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error("Guide footprint request failed");
      const result = await response.json();
      for (const cell of values.querySelectorAll("[data-field]")) {
        const value = result[cell.dataset.field];
        cell.textContent = value == null ? "Unknown" : format.format(value);
      }
      values.hidden = result.fact_count === 0;
      status.textContent = result.fact_count === 0 ? "No Guide requests have been logged." :
        `Electricity modeled for ${result.energy_calculated_count} of ${result.fact_count} logged requests. ` +
        `CO₂e modeled for ${result.emissions_calculated_count} of ${result.fact_count}.`;
      const grid = result.grid_locations.length ? `Modeled grid locations: ${result.grid_locations.join(", ")}.` :
        "Deployment grid unknown for the logged usage.";
      method.textContent = result.energy_factor_parameter ?
        `Research factor: ${result.energy_factor_parameter} (${result.energy_factor_unit}). ` +
        "Facility overhead is included. CO₂e uses the recorded deployment grid. " + grid :
        "An electricity estimate requires both input and output counts. " + grid;
    } catch {
      status.textContent = "Guide footprint unavailable. Start the backend and try refreshing.";
      values.hidden = true;
    } finally {
      refresh.disabled = false;
    }
  }

  section.addEventListener("toggle", () => { if (section.open) load(); });
  refresh.addEventListener("click", load);
  if (location.hash === "#guide-footprint") {
    document.getElementById("library").open = true;
    section.open = true;
    section.scrollIntoView();
  }
})();

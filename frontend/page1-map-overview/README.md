# WattsON map overview

Standalone frontend for [issue #9](https://github.com/noahvogt/h4ckerss/issues/9). From this directory, run:

```sh
python3 -m http.server 8000 --bind 127.0.0.1
```

Open [the local preview](http://127.0.0.1:8000/). The geographic map uses [Leaflet 1.9.4](https://leafletjs.com/download.html) and [OpenStreetMap tiles](https://www.openstreetmap.org/copyright). It requires internet access and uses city-centre coordinates to represent deployment regions. Open `index.html` directly for the offline schematic, which also appears if the geographic map cannot load.

The overview opens with the full-width map and the company-wide digital services baseline. The **Basel HQ** bubble represents the company total and opens its breakdown by department or tool, including services without a known city. Zurich, Frankfurt and Dublin show their own regional totals. Add up deployments and records without a city to reconcile the company total. Office electricity and equipment are outside the case baseline. Close the panel with × or Escape. Switch among CO₂, kWh and cost to update the category strip, bubbles and driver rankings.

The first view uses illustrative figures. For integration with #4, the proposed handoff is a baseline JSON file with precomputed values and location codes from the team's fact schema. Test a file by appending `?dev=1` to the preview URL and opening **Developer tools → Import baseline JSON**. The browser reads the file locally and combines its rows for this session. This input expects normalised baseline data, while the two official CSV templates are submission outputs.

Region details show the baseline period, shares of known company spend and estimated CO₂ where calculable, and up to three tools or departments ranked by the selected metric. Percentage bars use the full selected scope as the denominator and are omitted for a breakdown with negative credits. If the selected metric is unavailable, the panel ranks by known cost where available. Expand a case observation to see its source. These observations refer to the supplied ALTYCA case files and appear only with the bundled example. An imported baseline uses its own totals and breakdowns.

An amber exclamation mark identifies a waste finding backed by case data. Select the labelled city or the EU (mixed) button to see the finding and any operational constraint. Expand **Sources** for the original files and ticket references. Case findings are visible with the bundled example and are hidden when importing a different baseline.

```json
{
  "period_start": "2025-09-01",
  "period_end": "2026-08-31",
  "illustrative": true,
  "rows": [
    {
      "location": "DE",
      "category": "server",
      "department": "Consulting",
      "tool": "GPU server",
      "cost_chf": 11500,
      "energy_kwh": 4500,
      "co2_kg": 1710
    }
  ]
}
```

Pass rows for the declared time period, using `CH`, `DE`, `IE`, `EU`, or `unknown` for `location`. Each metric is a number or `null` when unavailable. Use `0` for a known zero and preserve negative cost credits. All imported rows should use the same baseline assumptions. Use `illustrative: true` for fixtures. The frontend labels partial totals and keeps `EU` and `unknown` separate from the mapped cities.

Supply `category` as `cloud`, `server`, `ai` or `saas` from the team's fact table. Rows without it remain in the overall totals and appear as **Uncategorised** in the category strip.

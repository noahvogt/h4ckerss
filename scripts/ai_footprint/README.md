# Hackathon team AI footprint

This standalone CLI accounts for the team's own AI usage during **20–22 November 2026**
in the **Europe/Zurich** timezone. It reads local evidence and reuses WattsON's research
factors. It covers team activity and outputs usage metadata only.

## Collect usage for each team member

Run these commands from the repository root. Install the locked project dependencies
once to enable the pitch summary.

```sh
uv sync --locked --project backend
```

**Codex CLI.** Replace `MyName` and `my-name` with your agreed team alias. The importer
looks in `~/.codex/sessions/`. If you used Codex for unrelated work over the same weekend,
use `--sessions` to point to a specific hackathon rollout file or a directory of selected logs.

```sh
uv run --locked --project backend python -m scripts.ai_footprint import-codex \
  --member "MyName" --output out/ai_footprint/members/my-name-codex.csv
```

**Claude Code.** The importer reads the local transcripts in `~/.claude/projects/`
(or `$CLAUDE_CONFIG_DIR/projects`). That directory holds one subdirectory per working
directory, so point `--transcripts` at the hackathon repository's subdirectory, for example
`~/.claude/projects/-home-me-src-h4ckerss`, if you used Claude Code for other projects over
the same weekend. Without it, every project's sessions in the period are counted.

```sh
uv run --locked --project backend python -m scripts.ai_footprint import-claude \
  --member "MyName" --transcripts ~/.claude/projects/-home-me-src-h4ckerss \
  --output out/ai_footprint/members/my-name-claude.csv
```

**ChatGPT, Cursor, Copilot, Gemini and other tools.** Create a manual CSV
or copy [template.csv](template.csv). Use it for official usage exports or screenshots
showing actual counts for an interval fully within the hackathon. A usage-limit percentage
alone cannot establish token counts. Leave those fields blank if that is all you have.

```sh
uv run --locked --project backend python -m scripts.ai_footprint template \
  --output out/ai_footprint/members/my-name-manual.csv
```

Use one row per distinct evidence item, model and date. Example field values below use
blank counts intentionally. Add numbers only where your own evidence reports them.

```csv
member,tool,model,timestamp,input_tokens,cached_input_tokens,output_tokens,requests,measurement_method,evidence_reference
MyName,ChatGPT,,2026-11-20,,,,,official_export,my-chatgpt-day1
MyName,Cursor,,2026-11-21,,,,,screenshot,my-cursor-day2
MyName,Gemini,,2026-11-22,,,,,screenshot,my-gemini-day3
```

- Use an ISO date for a daily total, or a timestamp with an offset for a timed event.
  The CLI writes timestamps in UTC. `--start` and `--end` override the inclusive Basel dates
  for `import-codex`, `import-claude`, `combine`, and `summary`.
- Include cached input in `input_tokens` exactly once. Use `cached_input_tokens` for the subset
  read from cache if the source reports it. For Claude Code, the inclusive input total is
  the sum of uncached input, cache reads, and cache creation tokens. The importer applies
  this rule automatically.
  [Claude Code monitoring and token field definitions](https://code.claude.com/docs/en/monitoring-usage)
- Enter actual request counts where reported. Use `0` for a reported zero and leave unknown
  numbers blank. Use a short evidence label. Keep raw logs, screenshots, prompts, and keys local.
- Share only the resulting usage CSVs with the person combining the team data. Avoid mixing
  manual and automatic evidence covering the same calls. The tool can deduplicate identical
  rows and flag conflicting rows for the same evidence. It cannot infer that two different
  screenshots or exports cover overlapping usage.

## Combine the team files and generate the pitch summary

Collect the submitted CSVs in `out/ai_footprint/members/`. Keep combined outputs outside
that directory so the input glob selects only member files.

```sh
uv run --locked --project backend python -m scripts.ai_footprint combine \
  out/ai_footprint/members/*.csv --output out/ai_footprint/team.csv

uv run --locked --project backend python -m scripts.ai_footprint summary \
  out/ai_footprint/team.csv --output out/ai_footprint/pitch.md
```

Without `--output`, the summary prints Markdown to the terminal. A location-based CO₂e
estimate requires an explicit `--grid` scenario using one of the existing factors
(`CH`, `DE`, `IE`, `EU`). Use it only when you can explain why that scenario is relevant
to the inference location. The team's presence in Basel does not identify the provider's
deployment grid. Omit the option to report unknown CO₂e.

## Accounting and limitations

- The Codex reader uses deltas of reported cumulative counters within a session. Repeated
  snapshots and identical copied events do not add usage. It follows counter resets and
  uses available reported increments when a missing checkpoint prevents a full delta.
  At the start of the reporting period it can use the latest measured increment if a
  cumulative delta spans the cutoff. A first cumulative-only snapshot from an earlier or
  uncertain start remains unknown. [Codex token accounting](https://github.com/openai/symphony/blob/main/elixir/docs/token_accounting.md)
- The Claude Code reader exports one row per API response, using the `usage` object
  that the transcript stores with each assistant message. A response split into several
  content blocks repeats the same usage on several lines. The reader keys rows on the
  request ID, falling back to the message ID, so those lines count once. Responses that a
  resumed or forked session copies into another transcript also count once. If the lines
  of one response disagree, the reader keeps the largest value for each field and prints a
  warning. Locally generated `<synthetic>` messages are skipped. `requests` is `1` per
  response. Claude Code's background calls (such as session titles, classifiers and
  context compaction) do not produce assistant messages in the transcript. The session
  `cost-state` totals include them but carry no timestamps. On the development machine those
  totals were often 10–30 % higher in cache reads than the per-response sum, so treat the
  import as a lower bound. The reported `inference_geo` was `global`, which does not
  identify a deployment grid.
- Import warnings go to the terminal. Missing usage fields stay blank. Codex request counts
  stay blank because token snapshots do not reliably identify individual requests. Context
  estimates, unreadable log lines, and forked rollouts whose inherited usage cannot be
  isolated are omitted. Rerun the import after the last session has flushed its logs.
  [Codex rollout source](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/list.rs)
- Input and output totals sum measured fields independently. Electricity is modeled only for
  rows with both counts. WattsON's facility-inclusive research proxy is expressed per 1,000
  input plus output tokens. The factor was weighted using the fictional company's baseline
  token mix. The research documents approximate input and output rates derived from one
  modeled GPT-4o example. It does not establish distinct energy rates for cached input,
  uncached input and output for Codex. Cached input is counted once and receives the same
  blended factor as the other tokens.
  [Research assumptions](../../submission/research_baseline_and_assumptions.csv) ·
  [Epoch AI methodology](https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use#appendix)
- The summary shows the cached share across rows with paired input and cache counts. A
  cache-heavy workload can differ substantially from the token mix and serving assumptions
  behind the proxy. The low and high values are deterministic sensitivity scenarios, and
  they do not quantify the cache effect or establish a bound on actual electricity use.
  Use the pitch estimate as a scenario for the logged usage and state its coverage.

## Tests

```sh
uv run --locked --project backend python -m pytest scripts/ai_footprint/tests
```

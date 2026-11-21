# Data decisions

## AI usage

- The provided `ai_usage.csv` contains 52,856 data rows. The loader removes 87
  exact duplicate rows before aggregation, leaving 52,769 records. Rows are
  removed only when every CSV field matches; records sharing a date, model, or
  resource remain distinct when any other field differs.
- Input and output tokens are aggregated independently. `usage_qty` is the sum
  of known input and output values. Cached input tokens are already part of
  `tokens_in`, so they are retained as a separate detail metric but not added a
  second time.
- Missing token values are not replaced with zero, estimated, or otherwise
  invented. If only some input or output values are missing, the known partial
  total is returned and the `note` explicitly flags incomplete usage with the
  number of missing input and output values and the phrase `known tokens only`.
  If all input and output values are missing in a group, `usage_qty` remains
  missing and the note explains that usage is unavailable.
- Detail rows preserve input, cached-input, and output token totals along with
  missing-value counts.

## AI and SaaS subscriptions

- Subscription costs use the shared monthly CHF conversion helper. Invalid
  dates, unsupported currencies, and absent exchange rates raise errors rather
  than being silently converted into plausible-looking values.
- Cost centers are read as strings and mapped through the shared department
  helper. Missing or unknown cost centers map to `Unallocated` and are noted.
- Draft subscriptions remain in detail data but are excluded from billed facts
  and unused-seat calculations.

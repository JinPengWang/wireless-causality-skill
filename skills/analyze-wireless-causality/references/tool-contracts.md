# Tool contracts

Store run-specific Python adapters/reproduction scripts under tools/runs/<run_id>, with their input/output data and settings under logs and results. Keep that runtime script subtree out of source-control commits unless intentionally generalized.

Use the task-selected Python interpreter. Core runtime dependencies are in tools/requirements.txt. Do not install all optional causal/ML dependencies for simple comparisons.

## Implemented tools

| Tool | Input | Output and scope |
|---|---|---|
| check_environment.py | optional expected interpreter prefix | interpreter and dependency versions; no mutation |
| audit_workbooks.py | explicit XLSX paths; optional sheet/header row/sample limit | streaming profiles, missingness, examples and hashes; no semantic inference |
| build_windows.py | versioned JSON mapping | normalized windows with metadata, coverage and source rows |
| compare_runs.py | normalized window JSON; optional reference | duration-weighted or pooled-count per-run summaries and equal-pair contrasts |
| detect_events.py | one selected series and threshold policy | excursions, integrated deficit and onset/recovery censoring |
| plot_windows.py | normalized windows, mode, optional shared theme/language labels | direction/condition/metric-separated ECDF or separate-run traces; dense-series panels retain every eligible entity |
| wifi_frames.py | normalized JSON request | compressed BA decoding, observed retry chains or rate proxy |
| causal_analysis.py | explicit variables, units, controls, design and normalized records | per-recording association/prediction or independent paired contrast; attempts, diagnostics, influence and test-family results |
| event_analysis.py | normalized interval means plus mapped anchors/signals | cross-layer event summaries, timing bounds and censoring; no automatic clock fitting |
| verify_claims.py | hashed artifacts, exact value locators, unit contracts and expressions | atomic numerical checks with explicit arithmetic/meaning boundaries |
| evidence_model.py | v2/v3 ledger and artifacts | presentation-independent integrity, claim and completion checks |
| snapshot_report.py | validated ledger, fresh package directory, optional exact historical renderer source root | immutable ledger/artifact/source package and path/hash mapping; no recalculation or refresh of historical claims |
| write_report.py | validated ledger, optional presentation/table configuration and shared theme | JSON model or localized Markdown/offline HTML with summary, body and audit appendix; no fixed figure count |
| check_report_layout.py | generated HTML, fresh check output, optional existing browser/previews/PDF | static/DOM layout checks and optional PDF export; actual visual review remains separately recorded |
| test_tools.py / test_contracts.py / test_investigation.py / test_report_design.py | no private inputs | synthetic numerical, design-boundary, evidence, presentation and integrity checks |

Adapters for arbitrary free-text exports, cumulative counters, clock fitting, exact aggregate reconstruction, automatic BA matching, event-aligned overlays, causal designs beyond the declared paired backend and Tigramite execution are **not** silently supplied by these primitives. Implement the smallest missing adapter when required, or return an explicit unavailable capability. Do not imply the library is a fully automatic root-cause classifier.

Workbook audit `mode` records requested full/sample scope, not success. Inspect sheet, workbook and top-level execution `status` (`completed`, `partial`, `failed`) and scan boundaries. Read issues remain in JSON with scanned data; any such issue makes the CLI nonzero. Explicit row-limited sampling is a completed sample when no read error occurs, with full-scan completion reported separately.

## Window mapping v1

Top-level keys: schema_version=1, window_s>0, sources (nonempty list), optional max_windows (positive integer; default 100000 output records). Decimal grid boundaries and exposure membership use the same floating-point normalization. Exposure is half-open [start,end); events normalized onto the end are rejected, never silently dropped. Header mappings are checked before filtering, including empty sources.

Each source has path, optional sheet/header_row, optional `where` mapping exact header names to eligible value lists, metadata, time and metrics. Metadata requires run_id, entity, direction, condition and pair_id. These are explicit strings; unknown/unpaired values permit descriptive work but do not establish matched comparisons. Condition IDs must refer to reviewed covariate definitions in the run manifest.

Time requires start-column name, positive scale to seconds, numeric origin in seconds, and split_policy (`reject` or `uniform`). Normalization is `raw_time * scale - origin`. Add an end-column for interval rows. Event rows instead require an observation_interval in normalized seconds and a capture_complete boolean. A declared interval describes observation exposure, not proof of loss-free capture.

Metrics require name, unit, kind, scale and a nonempty definition. Optional measurement_id declares reviewed semantic equivalence across sources; normalized unit and aggregation family must still agree. With an explicit ID, interval amounts and event sums/counts can share an exposure-rate contract, and ratios/event means/fractions can share a pooled-observation contract when their populations and denominators really agree. Duration means remain distinct. Without an ID, the raw kind must also match. Without it, the definition must match. Optional min_observations counts valid source records; min_denominator applies only to ratios or observation means. Defaults are zero; choose scientifically justified thresholds in the run configuration. Use a column for a value, or numerator/denominator columns for ratio. Optional value_map normalizes declared string categories to numeric values; unknown strings remain missing and are counted.

- interval_mean: duration-weighted average, multiplied by scale.
- interval_amount: interval amounts distributed across time and divided by observed seconds, then multiplied by scale. For received bytes to Mbps, scale=8e-6.
- ratio: sum of allocated numerator counts / sum of allocated denominator counts, multiplied by scale. Requires 0<=numerator<=denominator; zero denominator remains missing.
- event_mean / event_fraction: observation-weighted mean; fractions require explicit normalized 0/1 values. These are not time-weighted PHY rate estimates unless the population/weighting justifies that interpretation.
- event_count / event_sum: observations or summed values per declared exposure second, multiplied by scale. Empty windows become zero only when capture_complete is explicitly true; otherwise they remain unavailable. Header-only or filter-empty event populations are supported. If any selected event_sum amount is invalid, its window total stays unknown even for a complete capture. Event means/fractions describe only valid observations and expose excluded counts/rows; inspect potential selection bias.

Overlapping or unsorted interval rows are rejected. Split crossings are rejected unless uniform allocation is explicitly enabled. The tool preserves missing windows, aggregation numerators/denominators, scale, valid/invalid observation counts, invalid-source-row lists, a support status and exact valid source row lists. Normalized windows require definitions and finite times/values; downstream tools validate metadata, nonoverlap and agreement with stored aggregation primitives. Per-run means pool the counts for ratio and observation-mean metrics; time-weighted quantiles describe the distribution across valid time. A window value covers its valid exposure; coverage filtering must be explicit. Field absence is not zero. Multiple sources for the same run/metric require explicit reconciliation rather than silent summation.

## Wi-Fi primitive requests

`decode_compressed_ba`: operation, start_seq, wire_hex (octets in wire order), bitmap_bits (64 or 256), observed_sequences. Caller must establish compressed single-TID variant and correct transmission context. Returned zero-bit states mean not acknowledged in this bitmap, not proven final failures.

`observed_retry_chains`: operation, max_gap_s, frames. Each normalized frame requires capture_id, transmitter, receiver, tid, seq, fragment, time_s, retry (0/1) and source_row. Include interface/channel/link in capture_id when relevant. Unknown identity fields must stop reconstruction. Time must be ordered within each capture. Output preserves censoring and possible duplicate observations; no configured retry-limit estimate is returned.

`effective_rate_proxy`: operation, rate_mbps, failures, attempts. Inputs must already share the declared population/window and rate weighting. No PER is inferred from retry flags.

## Investigation and delivery interfaces

See [causal-investigation.md](causal-investigation.md) for the normalized record schema, controls/independent units, the implemented method registry, exact randomized-pair scope, validation, fallback and multiplicity contracts. See [end-to-end-investigation.md](end-to-end-investigation.md) for path-layer capabilities and the configured event interface. These backends do not impose a universal grid or infer interventions from filenames.

See [evidence-claims.md](evidence-claims.md) for atomic numeric claims, table/JSON locators, expression/unit rules, v3 assessment/provenance fields, legacy v2 support and separate report exporters. Evidence hashes, calculation checks and semantic/causal review have distinct meanings. Images are optional; if included they still require integrity and readability checks. New work uses ledger schema_version=3. Existing v2 reports remain readable with numerical verification explicitly not performed.

See [report-design.md](report-design.md) for presentation schema v1, shared theme/plot rules, source protection, table splitting/rounding and the browser/manual layout-review boundary. Browser rendering is optional and uses an existing Chromium executable plus optional websocket-client; the exporter does not install a browser or weaken its sandbox. Preserve analysis/evidence content across presentation changes.

Run all regression cases with `python -m unittest discover -s tools -p "test_*.py"`. A platform-denied hardlink integration test is reported as skipped, not passed. Keep runtime artifacts out of commits and do not claim a test ran merely because a planned check appears in a template.

## Extension acceptance

Add executable tests for changed semantics, not tests that merely mirror code. Include a different file/schema naming pattern and different units/durations. Check empty/missing data, unmatched identities, duplicate timestamps, overlapping intervals, counter resets when implemented, partial capture, wrong direction, no valid denominator and evidence-file changes. Separate implementation status from proposed methods.

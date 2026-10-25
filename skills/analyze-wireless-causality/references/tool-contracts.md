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
| plot_windows.py | normalized windows and mode | direction/condition/metric-separated ECDF or separate-run traces |
| wifi_frames.py | normalized JSON request | compressed BA decoding, observed retry chains or rate proxy |
| write_report.py | evidence ledger and local artifacts | verified Markdown report with one or two figures per item |
| test_tools.py / test_contracts.py | no private inputs | synthetic numerical, boundary, missingness and integrity checks |

Adapters for arbitrary free-text exports, cumulative counters, clock fitting, exact aggregate reconstruction, automatic BA matching, event-aligned overlays, advanced causal estimation and Tigramite execution are **not** silently supplied by these primitives. Implement the smallest missing adapter when required, or return an explicit unavailable capability. Do not imply the library is a fully automatic root-cause classifier.

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

## Report ledger

Store the ledger under logs/<run_id>. Use schema_version=2 and analysis_status=completed, partial or blocked. Migrate old ledgers explicitly: add these fields, figure hashes, structured locators and finding-to-phenomenon links. Blocked reports may have empty phenomena/findings and no figures; document why analysis cannot proceed. Completed reports require observed phenomena. Artifact paths are relative to the ledger directory. Every phenomenon/finding has an id, statement, evidence status, calculation/selection explanation, hashed evidence references with locators, one or two figures with explanatory captions, and limitations. Phenomena must use observed status. Findings add explains (existing phenomenon IDs), an ordinal priority and rationale, mechanism, support, counterevidence and next_test. Figures require SHA256 and a decodable PNG/JPEG/WebP or well-formed SVG, in addition to captions. Readability still requires visual review. Validated mechanisms additionally require validation design, replication, reviewer assessment and a hashed result artifact.

Supported locators are {"type":"json_pointer","pointer":"/rows/0/value"}, {"type":"line_range","start":2,"end":5}, {"type":"whole_file"}, or {"type":"description","text":"manual locator"}. JSON pointers resolve keys/list indices with ~0/~1 escaping; line ranges refer to physical text lines, not CSV records. Descriptions render as unverified and cannot alone locate a validated-mechanism result. A valid locator establishes existence, not claim correctness. The renderer includes validation design, replication and reviewer assessment.

The renderer verifies records and links, not causal truth. Validate figure readability separately. Use Markdown-safe artifact paths. Report generation does not upload any source data. All artifact writers reject collisions with declared inputs; JSON outputs and Markdown reports use atomic replacement. Plotting checks its manifest and image paths before writing. Keep each run in a separate directory.

Run all regression cases with `python -m unittest discover -s tools -p "test_*.py"`. A platform-denied hardlink integration test is reported as skipped, not passed.

## Extension acceptance

Add executable tests for changed semantics, not tests that merely mirror code. Include a different file/schema naming pattern and different units/durations. Check empty/missing data, unmatched identities, duplicate timestamps, overlapping intervals, counter resets when implemented, partial capture, wrong direction, no valid denominator and evidence-file changes. Separate implementation status from proposed methods.

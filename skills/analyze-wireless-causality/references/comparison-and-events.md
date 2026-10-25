# Comparisons and events

## Comparison unit

Define the estimand before choosing weights: equal independent runs, equal device pairs or traffic-weighted exposure answer different questions. Show the complete entity-by-peer coverage matrix and missing cells. Match pre-exposure conditions such as topology, transport, offered load, radio setup and scenario when available. Unknown conditions are not evidence of equivalence.

Treat repeated windows and simultaneous links as dependent measurements. Aggregate within the independent run/pair before uncertainty estimation. `compare_runs.py` computes equal-pair descriptive contrasts, with equal condition weights inside each pair. Its optional marginal pair-bootstrap intervals assume independent declared pairs. Outputs retain condition-level and pair-level contrasts so opposing peer/condition effects are visible. Check that every pair is targeting a defensible condition mixture before using the pooled result. Per-run valid_time_fraction and condition-level incomplete_observation flags describe usable exposure. Missing windows can select different states in each entity; a valid-data contrast is not automatically a whole-recording contrast. Do not extrapolate across informative missingness. For ratio/observation metrics, run means pool their stored numerators and denominators; quantiles describe time exposure. The operational minimum pair count is not a universal adequacy guarantee, and intervals do not identify a vendor's causal effect.

Do not claim graph or mechanism differences from 'significant in one group, nonsignificant in another'. Test the contrast or show uncertainty and comparable power. Do not claim equivalence from a nonsignificant difference. Prespecify primary outcomes, comparisons and multiplicity handling.

## Regular, irregular and unknown exposure schedules

A task-provided schedule is metadata, not a measured intervention log. Use actual anchors when available; otherwise propagate onset ranges and clearly label assumed alignment. Verify that schedule repetitions and durations agree with observed recordings. Preserve source-relative axes when alignment cannot be established.

For irregular motion or unknown exposures, use per-run distributions, duration-weighted lower/upper quantiles, spread, deficit area, dwell times and censored recovery. Minima and maxima are highly sample-size-sensitive; show them as observed extrema, not hard performance bounds. Do not infer a movement label from an outcome drop and then reuse it as independent proof that movement caused the drop.

For many entity pairs, use small multiples and a summary matrix. Keep direction, unit and primary window consistent. Show a few detailed event traces selected by an explicit rule, including counterexamples. The built-in timeline tool deliberately uses separate run axes; verified event-aligned figures require an adapter with anchor provenance.

## Event measures

Separate amplitude, duration, integrated deficit, response lag, oscillation, recovery time and post-event level. Supply units and definitions. Use an external SLA if known; otherwise baseline estimation is exploratory and must avoid future information for prospective detection. A relative detector can miss persistent low performance; inspect absolute levels as well.

The bundled excursion detector supports explicit below/above thresholds, minimum duration, coverage and sustained recovery. It does not identify motion or interventions. Mark the beginning as left-censored when a recording starts already abnormal. Leave recovery censored when the recording/gap ends before the recovery criterion is met. An observed relapse is `interrupted_by_relapse`, not censoring; it starts another contiguous excursion. Only `recovery_status=observed` confirms sustained recovery. Read `recovery_followup_end_s` and the stop reason. Partial-coverage bins have unknown within-bin gaps and therefore break continuity in the bundled detector; timing remains limited by the analysis grid.

Do not learn a causal model solely from outcome-selected events or result-selected clean reference windows. Such windows support diagnostics, but their selection can distort causal estimation.

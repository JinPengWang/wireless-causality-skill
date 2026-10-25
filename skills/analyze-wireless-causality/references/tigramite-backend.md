# Optional Tigramite backend

Status: integration specification; Tigramite is not a bundled dependency and no Tigramite run is implied by using this skill. The generic tools remain usable without it.

Use a backend only when conditional time-series discovery can discriminate a stated mechanism. Install into the task-selected environment only with the user's applicable authorization. Pin a tested version and its dependencies; record code/data hashes, seed, runtime, memory and assumptions. Consult the version's actual signatures rather than copying a stale example.

## Preconditions

Prepare regular-grid, semantically distinct variables, valid masks and continuity segments. Define seconds-to-lags conversion from the chosen grid. Do not flatten overlapping windows into independent observations or concatenate unrelated runs into fictitious temporal adjacency. Do not duplicate deterministic transforms of the same measurement in a discovery graph.

Assess mechanism stability, nonlinear/heteroskedastic behavior, missingness and usable samples relative to conditioning dimension. These checks do not certify stationarity, causal sufficiency, Markov or faithfulness assumptions. Keep unmeasured load/environment/control variables in the limitations. Select variables using mechanism knowledge, retaining relevant common causes; top-correlation screening can remove them.

Use appropriately comparable background data, not only hand-picked anomalous seconds. Group multiple datasets only with a justified shared-model interpretation; multi-dataset support does not remove device heterogeneity.

## Method selection

- PCMCI: lagged discovery under the applicable no-hidden-confounding and contemporaneous assumptions.
- PCMCI+: lagged and contemporaneous discovery under causal sufficiency; retain ambiguous contemporaneous directions.
- LPCMCI: allow latent confounding under its assumptions; retain PAG/partial ancestral edge marks.
- J-PCMCI+: a specialized route for multiple contexts, not a shortcut to causal device ranking.
- CausalEffects: a separate effect-identification and estimation step conditional on a suitable graph and design. It does not automatically validate a discovered graph.

Match the conditional independence test to continuous, categorical or mixed data and functional assumptions. Use a cheap linear baseline only when scientifically meaningful; it is not an obligatory filter that eliminates all nonlinear candidates. Record method-specific parameter semantics and supported multiple-testing correction. Do not apply one generic FDR flag to every algorithm.

## Wrapper contract

Expose `audit_timeseries`, `discover_time_graph` and `validate_time_graph` behind a small deterministic interface. Accept data/artifact handles, selected scope, grid, lag range, declared priors, method/test profile, seed and resource budget. Return status, full configuration, graph artifact, edge summaries, valid-sample diagnostics, uncertainties, limitations and source lineage. Define statuses for unsupported data, insufficient evidence, timeout and completion. Never label a timed-out partial graph as complete.

Explicitly configure `mask_type` where masks are used. Validate the complete `link_assumptions` dictionary: missing entries can mean forbidden links. Distinguish required edges from merely permitted edges; do not report forced priors as empirical discoveries. Preserve raw graph marks and method-specific p/statistic matrices. A test statistic is not an intervention effect or a causal probability.

Cache by data, transformation, variable-set, method-version and configuration hashes. Reuse caches only when those keys match. Return compact evidence to the language model and store large matrices locally. Limit expensive nonlinear tests and repeated fits through a prespecified budget, not by stopping when a desired graph appears.

Validate with known-direction, latent-confounder, nonlinear, feedback, no-edge, missingness and regime-change simulations, then held-out real runs. Include checks for schema permutations, masked samples, disjoint segments, forced-prior handling and timeout behavior. Preserve rejected/unstable results.

## License and sources

Tigramite uses GPLv3 terms. Evaluate the actual distribution/integration model before shipping a combined commercial product; a subprocess or MCP boundary is not automatically a license exemption. Keep third-party notices and method citations.

- Project and assumptions: https://github.com/jakobrunge/tigramite
- API: https://jakobrunge.github.io/tigramite/
- PCMCI+: https://proceedings.mlr.press/v124/runge20a.html
- LPCMCI: https://proceedings.neurips.cc/paper/2020/hash/94e70705efae423efda1088614128d0b-Abstract.html
- Causal effects: https://jakobrunge.github.io/tigramite/_modules/tigramite/causal_effects.html

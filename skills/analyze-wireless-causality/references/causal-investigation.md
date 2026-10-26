# Executable causal investigations

## Contents

- Method selection and scope
- Request and normalized data contracts
- Implemented backends
- Validation, failures and multiplicity
- Extension and sources

## Method selection and scope

Choose the method from the current question, design and observable quantities. Descriptive comparisons, threshold events, conditional association, incremental prediction and intervention effects answer different questions. No backend is mandatory, no device is the default winner, and no universal grid or experimental schedule is imposed.

Use `causal_analysis.py` for its supported designs. Keep ordinary descriptive work in `compare_runs.py`, `detect_events.py` and source-specific summaries when those are the appropriate answers. An unsupported effect design does not prohibit useful association or mechanism investigation. If a suitable nonlinear, categorical, longitudinal or other estimator is needed, add an explicit backend rather than forcing it through a linear model.

The implemented backend registry contains:

| Method | Numerical result | Permitted interpretation |
|---|---|---|
| `adjusted_association` | Per-recording outcome-on-exposure/control linear coefficients and diagnostics | Conditional association under the stated model |
| `lagged_prediction` | Baseline versus expanded out-of-sample MSE, by recording and held-out independent unit | Incremental predictive information at a nominal lag |
| `paired_contrast` | Per-recording means, matched independent-pair differences and influence summaries | Observed matched contrast; conditional intervention interpretation only for a defensible declared randomized paired design |

Tigramite remains an optional **integration specification**, not an implemented backend in this registry. Naming an unavailable method returns `unsupported`. See [tigramite-backend.md](tigramite-backend.md) for its distinct assumptions and future integration requirements.

## Request and normalized data contracts

Copy `assets/causal_request.template.json` into the current run. Resolve placeholders and change a task from `mode: plan` to `execute` only when execution is intended. Paths are relative to the request file. `data` contains the normalized JSON path and SHA256. Its schema is `assets/causal_data.template.json`:

```json
{
  "schema_version": 1,
  "sources": [],
  "records": [
    {
      "recording_id": "recording-identity",
      "unit_id": "independent-design-unit-or-null",
      "time_s": 0.0,
      "values": {"outcome": 1.0, "factor": 0.0}
    }
  ]
}
```

This is a normalized interface example, not an acquisition schedule. Keep the adapter's source-row mapping and measurement contract alongside the data; optional `sources` entries contain source paths and SHA256, relative to the data file. Raw file names and vendor schemas do not enter the backend. Read only source formats authorized by the current task.

Declare:

- Question, population/scope and the actual independent experimental unit. Several recordings may share one unit. A recording cannot change its unit midstream. Null/unknown unit identity allows per-recording descriptive exploration, but does not create independent replication.
- Variables: `meaning`, `unit`, `time_scale`, `role`, and `derived_from` names. Audit deterministic aliases and transforms before fitting. The tool rejects declared derivation relationships among selected variables; it cannot discover every undocumented alias.
- Explicit outcome, exposure, `controls` list (possibly empty), and a substantive `control_rationale` for every control. The bundled adjustment rejects declared mediators, colliders and post-treatment controls. A filled role/rationale is not a proof that the control set is valid.
- Model/design assumptions, applicability boundaries and selection rules. Use reviewed numeric encodings; keep missing values null. Do not silently assign ordinal meaning to a categorical label.
- `observation_weighting: equal_rows_within_recording`. These particular backends operate on that estimand. Other weighting schemes require an adapter/backend with its own contract; do not mislabel irregular point samples as time-weighted observations.
- `relative_clock_uncertainty_s`: a reviewed bound or null. A predictive lag is never automatically a physical response delay, even when its clock error is bounded.

All recording/time pairs must be unique. Keep unrelated recordings separate, without manufactured temporal adjacency. A row is a source observation or reviewed analysis interval, **not** an independent experiment. Results retain zero-based `included_rows`/`excluded_rows`, or train/test indices, into `records`. Those indices refer to the normalized file, not directly to worksheet rows; retain the adapter's source mapping separately.

```text
python tools/causal_analysis.py --request logs/<run>/causal_request.json --output logs/<run>/causal_results.json
```

## Implemented backends

### Adjusted association

Fit `outcome = intercept + exposure + controls` separately in each recording using complete cases. Require a full-rank design and more observations than parameters. Record coefficients, numerical condition number, residual RMSE and descriptive lag-1 residual correlation. The latter follows retained observation order; inspect gaps and time semantics before interpreting it.

Aggregate coefficients equally within declared independent units, then equally across units. Retain unit values, range and leave-one-unit-out estimates. These summaries expose heterogeneity and influence; they do not supply window-iid standard errors or prove linearity, independence, stationarity or confounding control. No p-values are generated by this backend. For unknown unit identities, report individual fits and omit independent-unit pooling.

### Lagged incremental prediction

Specify `prediction.step_s`, positive integer `lag_steps`, `train_fraction`, `min_test_rows`, and optional `gap_steps` at least as large as the lag. The selected recording must already have a regular grid at this scale; the backend does not interpolate or silently resample.

At time t, the baseline uses lagged outcome and lagged controls. The expanded model additionally uses lagged exposure. Fit on each recording's earlier portion and score its later portion after the declared gap. Preserve complete-case exclusions and the exact held-out rows. Also fit with one whole independent unit held out, using other units only; never split one unit across training and testing. Cross-unit training weights rows equally, and scores retain separate recordings.

`delta_mse = baseline_mse - expanded_mse`; negative improvements and failed/rank-deficient models remain in the result. Report forward-holdout and independent-unit-holdout completion separately. Hyperparameter/variable/lag selection on these validation scores requires a new outer holdout or an explicitly exploratory label. Similarity of independent units and stability of the conditional prediction problem need substantive review.

### Independent paired contrast

Each recording has one binary exposure (0/1). Average eligible outcomes within recording, then recordings within exposure condition, then pair differences equally across independent pairs. Declared matched controls must be observed and constant within a pair; varying controls require another design rather than an unnoticed adjustment.

An `observational_paired` design returns a matched association and `inference.status: not_identified`. For `randomized_paired`, require `assignment_unit: independent_pair` and explicit `assignment_evidence`, `estimand`, `population`, `time_horizon`, `carryover_assessment`, `interference_assessment`, and `missingness_assessment`.

The randomized backend enumerates all independent-pair sign assignments for **2–16 pairs** and tests the absolute equal-pair mean under the sharp null of no effect. This computational bound is not a scientific adequacy threshold. Outside that range, retain descriptive differences and mark inference unsupported; do not silently switch tests. Its conditional intervention interpretation depends on the declared assignment and design being valid. Software does not verify randomization, exchangeability, missingness ignorability, no carryover or no interference.

Missing/unmatched units and recording failures remain visible. Complete-case selection can change the target population. The backend does not estimate confidence intervals, heterogeneous causal effects or individual-event counterfactuals.

## Validation, failures and multiplicity

Record every requested analysis as `planned`, `executed`, `partial`, `unsupported` or `failed`, with configuration, assumptions and actual attempts. Per-recording and held-out-unit statuses remain available. A configured fallback is an explicit alternative, not an undisclosed substitution; choose it only if its different question and assumptions remain useful. Retain failed/unsupported preferred-method results. Numerical execution failures yield a nonzero CLI exit while preserving results when the input contract permits execution. Invalid top-level inputs are rejected before a valid result can be produced.

Declare the family of tests before inspecting p-values. `multiplicity` requires `method` (`holm` or `none`), a rationale and named disjoint `families` of analysis IDs. Every computed p-value must belong to a family. Holm retains the full declared family size, treating unexecuted members conservatively as p=1 internally while exposing their p-values as null and status as `not_tested`. No unexecuted test is called passed. `none` needs an explicit scientific justification; a single selected discovery among many unrecorded scans is not a single-test family.

Choose validation appropriate to the design: independent replication, held-out units, influence, heterogeneity, diagnostic plots, negative controls, timing/window sensitivity, falsification or randomized contrasts. Do not insist that every method use the same validation. Preserve the strongest alternative explanation, observations that contradict the favored mechanism and negative/unstable results. `execution_summary` does not state whether the scientific question or delivery requirements were satisfied.

## Extension and sources

Implement a new backend as a callable returning claim type, configuration, per-recording/unit diagnostics, included/excluded rows, assumptions, scope, uncertainty limits and failed results. Register it explicitly. Add positive, null, confounded, missing, ill-conditioned and incompatible-design tests appropriate to that method. Do not install optional packages or change the user's environment silently.

The CLI records actual interpreter/dependency versions, request/data/tool hashes and argv. JSON parsing uses the exact bytes whose hash was checked, followed by input-change checks. Keep the adapter, variable-selection decisions and full commands with the run as well.

Primary methodological/API references, consulted 2026-10-26:

- NumPy least squares and rank: https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html
- Temporal and grouped validation: https://scikit-learn.org/stable/modules/cross_validation.html
- Paired randomization semantics: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html
- Holm multiple testing: https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html

These sources support method definitions, not the validity of any particular recording or causal conclusion. The bundled implementations do not require scikit-learn, SciPy or statsmodels.

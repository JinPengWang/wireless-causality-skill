# Numerical claims, evidence and delivery contracts

## Verification boundaries

Keep three distinct checks:

- **Integrity and location:** a hash matches and a specified file, JSON path, worksheet row/column or text line exists.
- **Arithmetic and declared units:** selected values reproduce an atomic numerical statement within the stated tolerance under its declared unit contract.
- **Meaning and scientific validity:** the measurement, population, selection, wording, competing explanations and causal design actually support the claim. This requires substantive review; neither of the checks above certifies it.

Keep those distinctions in results and final prose. `meaning_verified` and `causal_truth_verified` remain false in automatic numerical results. A claimed data unit can agree with an artifact field and still have the wrong physical interpretation.

## Atomic numerical claim bundle

Copy `assets/numeric_claims.template.json`. Artifacts are identified by path and SHA256, relative to the claim bundle or enclosing ledger directory. Each claim has a unique ID, a precise statement, operands, expression, asserted value, output unit, and explicit absolute/relative tolerance. Split compound statements into independently supported components; one file citation is not a check of every number in a sentence.

An operand names its artifact, exact locator, unit and reviewed `unit_basis`. Optional `unit_locator` checks a corresponding stored unit field. Without it, the unit is explicitly a declared measurement contract, not an automatically verified physical fact.

Supported value locators:

```json
{"type":"json_pointer","pointer":"/recordings/0/mean"}
{"type":"table_cell","sheet":"Measurements","header_row":1,"row":2,"field":"exact_column_name"}
{"type":"table_rows","sheet":"Measurements","header_row":1,"rows":[2,3],"field":"exact_column_name"}
```

JSON pointers select a scalar or nonempty numeric vector. `table_cell` selects one scalar. `table_rows` always yields a vector, even for one row. XLSX rows are worksheet row numbers; CSV/TSV rows are logical table-record positions, with the header row counted. They are not physical text lines when CSV contains quoted newlines. Duplicate/blank headers, missing fields and missing selected rows fail. A source-row mapping in an adapter remains necessary when the cited artifact is an intermediate result rather than the raw table.

Supported arithmetic is deliberately small: named operands, finite numeric constants, unary signs, `+ - * /`, scalar `abs`, and vector `sum`, `mean`, `min`, `max`, `count`. Every declared evidence operand must be used. No arbitrary Python, indexing, attribute access or `eval` is allowed. More complex calculations belong in a tested analysis tool whose output is then cited precisely.

Built-in units include dimensionless `1`/`%`, time, information, rates, counts, frequency and `dB`; see `DEFAULT_UNITS` for exact spellings/scales. Unit algebra prevents adding unlike dimensions and converts results into the requested unit. Add a custom unit through `units: {"name": {"dimensions": {"dimension": 1}, "scale": 1}}`; do not redefine built-ins. This is a unit-consistency check, not a universal ontology. In particular, distinct layer metrics sharing a dimension are not automatically comparable, and logarithmic quantities need domain-appropriate formulas.

The checker currently uses finite float64 arithmetic. Integer and integer-string inputs/constants/assertions outside the exact integer range are rejected rather than silently rounding them. Use an exact-arithmetic adapter when required. Select tolerances to cover justified numerical/rounding error, not to excuse a scientific mismatch. Arithmetic tolerance is not measurement uncertainty or a confidence interval.

The pass criterion is:

`abs(asserted - recomputed) <= absolute + relative * abs(recomputed)`

```text
python tools/verify_claims.py --request logs/<run>/numeric_claims.json --output logs/<run>/claim_checks.json
```

Per-claim outputs preserve source values, locators, units, expression and errors. Wrong numbers produce `mismatch`; invalid inputs/expressions produce `failed`. The CLI returns nonzero for those results while saving the diagnostic output. Files are checked again for changes during verification. A manual claim uses `verification: manual` with a reason and remains `not_checked` by this tool. Figures and textual evidence are valid evidence carriers, but do not become automatically verified numerical values through an image/file hash.

## Ledger v3 and legacy v2

Use `assets/evidence_ledger.template.json` for new work. V3 retains the v2 core fields (`question`, `scope`, `measurement_contract`, phenomena, findings, limitations and reproduction) and adds:

- `language`, `title` and the machine-readable `numeric_claims` bundle.
- `claim_ids` on each item, plus an exact `supports` component on each evidence reference. Every numerical claim is linked to an item. Qualitative items may use an empty claim list.
- Candidate `prediction`, `strongest_alternative` and `claim_type` (`association`, `incremental_prediction`, `mechanism_candidate` or `intervention_effect`), in addition to explained phenomena, mechanism, support, counterevidence and next test.
- Four independent assessment records: execution (`completed/partial/blocked`), data capability (`sufficient/limited/unsupported`), question answer (`answered/partial/unanswered`) and delivery quality (`passed/partial/not_checked`). Each needs a reason. `analysis_status` mirrors execution only.
- Actual delivery checks (`passed/failed/not_checked/not_applicable`). Unfinished or failed checks cannot produce passed delivery quality.
- `claim_review`: manual semantic/completeness review status, reviewer, note and unmapped statements. The software cannot discover all unregistered numbers in prose; review the final text, tables and figure annotations.
- Provenance: skill revision or working-tree hash, actual interpreter and dependency versions, executed commands as argv arrays, and hashed artifacts with source/configuration/tool roles. Do not fill command history with unexecuted plans.

A validated mechanism or intervention-effect item additionally needs design, independent replication, reviewer assessment, identification scope and a specifically located result artifact. Those records are attestations for review, not software proof of identification.

Figures are optional, without a fixed count. Choose text, tables, structured results and plots according to the evidence and requested delivery. When used, figure hashes and decodability are checked; readability, selection and whether the image supports the statement require a separate check. Evidence locators support JSON pointers, table cells/rows, physical text-line ranges, whole-file references or explicitly unverified descriptions. A whole-file reference establishes only file scope.

Legacy v2 ledgers remain readable. They do not receive v3 numerical or assessment verification by implication. Migrate explicitly when those checks are needed. Do not rewrite old records as if the new checks had already been performed.

## Separate analysis from presentation

`evidence_model.py` validates the ledger independently of rendering. `write_report.py` exports a presentation-independent JSON model (ledger plus verification results), Markdown or offline HTML. The reader editions share one semantic rendering path, with a summary/body and linked audit appendix:

```text
python tools/write_report.py --ledger logs/<run>/evidence_ledger.json --format json --output results/<run>/analysis.json
python tools/write_report.py --ledger logs/<run>/evidence_ledger.json --format markdown --output results/<run>/diagnosis.md
python tools/write_report.py --ledger logs/<run>/evidence_ledger.json --presentation logs/<run>/presentation.json --format html --output results/<run>/diagnosis.html
```

Reader editions have English and Chinese labels. Other languages supply `--presentation labels.json` with matching `language` and a complete `labels` mapping; exact keys are in `report_labels.EN` (also re-exported by `write_report.py`). Statement content must itself be authored in the requested language. JSON export does not impose a presentation language. See [report-design.md](report-design.md) for summary selection, claim-backed numeric tables, theme overrides, offline HTML, optional Chromium PDF export and actual visual-review requirements. Other document formats require separate exporters. Do not rename a file or mark an unimplemented/unreviewed export as complete.

Renderers retain exact claim values, formulas, units and locators in a complete audit JSON sidecar, linked from compact appendix entries; the JSON analysis export also retains complete source vectors. Reader prose does not repeat long arrays. Matching Markdown/HTML editions share the same sidecar, and differing existing audit records are protected from replacement. Presentation tables round only the displayed value and link back to the original claim. Material limitations/counterevidence remain in the body. HTML includes a protected-artifact manifest so layout outputs cannot replace source/claim/provenance files. Layout review does not certify numerical or scientific meaning, and a recorded ledger assessment does not automatically certify a newly rendered artifact.

All referenced artifacts are protected against output collisions. Keep source hashes, adapter code, configuration, model versions, commands and limitations with the run. Finishing the renderer does not mean the scientific question, requested checks or requested export formats have all been satisfied.

For durable re-exports, use `snapshot_report.py` before modifying the checkout. Its ledger copy remaps artifacts and tools to an immutable package while preserving recorded hashes and claim/assessment values. The manifest retains original locations, the original ledger hash and snapshot execution details. A matching archived source root can recover a historical renderer; changed evidence never becomes valid by refreshing its expected hash. Export with the packaged renderer and assess that new export separately. See [report-design.md](report-design.md) for commands and the historical review boundary.

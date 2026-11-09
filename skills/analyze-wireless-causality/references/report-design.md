# Technical whitepaper reports

## Contents

- Reading structure and editorial rules
- Shared visual system and figures
- Presentation configuration and claim-backed tables
- Export and layout review
- Reproducibility and extension boundaries

## Reading structure and editorial rules

For a requested formal report, use a restrained, single-column technical whitepaper. Lead with the question and a short executive summary, then scope/measurement definitions and observed results. Include candidate explanations and discriminating checks when diagnosis is in scope. Purely descriptive reports may use `findings: []`; assess their completeness against the descriptive question. A requested PDF changes delivery checks, not the analysis question. Show the four recorded assessment dimensions in a compact table. Put compact exact locators and calculation summaries in an audit appendix linked from the text. Keep complete checks, selected values, configuration, commands and rendering provenance in the linked `<report>.audit.json` sidecar, shared by Markdown/HTML editions with the same basename and semantic inputs. Do not print large raw JSON/vector records in the reading edition.

Keep material limitations, counterevidence, null/failed results affecting interpretation, competing explanations and next discriminating checks in the body. Aesthetic compression must not remove them or turn a candidate into a confirmed cause. Do not manufacture findings, vendor rankings or missing results to populate a template. A blocked investigation can have no phenomena or figures.

Choose summary items explicitly through `summary_ids`. Selection points to existing ledger statements/statuses/limitations; it does not generate a new conclusion. Aim for a few material points, including an unresolved or negative result when relevant. The renderer never picks a winner. An empty selection displays an honest notice. Keep full items below regardless of summary selection.

Author concise, plain-text ledger prose in the requested language. Use short paragraphs and descriptive item titles; place lengthy explanations in the body. Prefer at most three heading levels, restrained bold emphasis and compact comparable tables. Do not put raw HTML, Markdown tables, external images or a complete second document inside a prose field. The renderer escapes prose; structure belongs in the presentation configuration. Review titles and table text for new/unmapped numerical or causal claims too.

Treat density targets as reflow/splitting signals, not permission to discard evidence. Do not fix page counts, word counts or numbers of figures. Use a compact opening for short reports and navigation for longer ones. No invented company logo, author, classification or affiliation.

## Shared visual system and figures

`assets/report/theme.json` controls reports and bundled plots. Defaults: white background, dark gray text, navy headings, a restrained teal accent; screen body 16 px / 1.65 line height, content width 840 px; print A4 with 22 mm margins and 11 pt body. These are project defaults, not an industry standard. `whitepaper.css` defines hierarchy, spacing, table rules, figure captions and print behavior. Custom theme JSON overrides known keys only; unsafe values, illegible sizes and insufficient text contrast fail validation.

Use numbered figures/tables, visible units, informative captions and accessible figure text. Captions explain population, selection, window, weighting and uncertainty. Verify final-size readability, including labels inside images. PNG and SVG are supported; embedded HTML figures must be self-contained and non-executable. HTML embeds images/CSS and does not fetch fonts or scripts. Evidence links are relative local links, with local file-URI fallback for Windows cross-drive sources; deliver their referenced artifacts if a recipient needs the audit sources.

Apply `plot_style.context(load_theme(...))` to run-specific plotting code as well as the bundled plotter. Preserve metric meaning, gaps, aggregation and comparable axis limits. The plotter separates directions/conditions/metrics; its default ECDF panels have at most six series, and timeline pages at most three run rows. All eligible series remain present across panels. Entity color/line mappings are consistent throughout one plot invocation and recorded in the figure manifest; preserve that manifest or explicitly reuse a mapping across separately authored charts. A new entity set is not guaranteed the same palette assignment across separate invocations. Colors encode identity, not superiority or causal confidence.

Use matching language for figure labels. Built-in plot labels cover English and Chinese; other languages use `--labels` with `ecdf`, `time` and `runs`. Metric/entity names come from the reviewed adapter. Never shrink a plot indefinitely to fit a page: split panels or use a suitable separate figure. Inspect the exported size. Print CSS keeps figures with captions where possible, keeps small tables together, starts long tables on their own print page, repeats table headers and discourages orphan headings; those rules still require actual PDF review.

## Presentation configuration and claim-backed tables

Start new reader editions from `assets/report/presentation.template.json` (presentation schema version 2). Give each displayed ledger figure a stable `id` and retain the existing logical `id` on each authored table. IDs use ASCII letters, digits, underscores and hyphens and must be unique within each kind across the report. Preserve them in run-specific adapters. Version 1 presentations and legacy calls without a presentation retain their existing export behavior. The evidence ledger uses its own schema version.

For every figure and logical table, supply a plain-text paragraph in `readings`, keyed by `figure:<id>` or `table:<id>`. It will appear beside the visual in the reader edition. A grouped multi-panel figure can direct the reader to individual panels in a single reading. In a series of reference plots, describe the shared method once and give each separately displayed figure a short pointer to its own data. Use a stable reference such as `{{figure:delivery_by_condition}}` or `{{table:delivery}}` in reader prose, captions and readings. Numbering follows the final display order. A reference to a wide table identifies its first part.

Write the reading in the report language. Point to the particular curve, panel, row or cells that answer the question. Describe the main comparison, its relevance to the investigation and any exception, sparse support or timing limit that changes the interpretation. If no consistent difference is visible, say so. Keep measurement definitions in the caption or note. Explain colors, symbols and line styles on the figure or in its caption. Tie quantitative statements in the reading to the owning item's evidence and verified claims.

At the final display size, find the described marks or cells, check the legend and look for visible counterexamples. Verify the endpoint and time range that support each comparison. A reader should be able to distinguish an observation from a proposed explanation using the visual and its adjacent text. The exporter checks coverage and resolves cross-references. Record the result of the substantive visual and text comparison in the report review.

Other presentation settings include:

- `language`: must agree with the ledger; custom languages also provide all `labels` keys in `report_labels.EN`.
- `summary_ids`: distinct existing phenomenon/finding IDs, chosen for relevance.
- `item_titles`: optional short titles keyed by existing IDs.
- `tables`: optional tables owned by an existing evidence item.

Example (replace IDs and wording with actual supported items):

```json
{
  "schema_version": 2,
  "language": "en",
  "summary_ids": ["P1"],
  "item_titles": {"P1": "Delivery comparison"},
  "readings": {"table:delivery": "The delivery column records a result for recording A alone. Comparing devices requires a corresponding recording under the same condition."},
  "tables": [{
    "id": "delivery",
    "owner": "P1",
    "title": "Recording-level delivery",
    "note": "State population, weighting and uncertainty here.",
    "columns": [{"label": "Recording"}, {"label": "Mean delivery", "unit": "Mbit/s"}],
    "rows": [["Recording A", {"claim_id": "C1", "significant_digits": 4}]]
  }]
}
```

Numeric cells reference passed atomic claims linked to the owner item. Their column unit must exactly match the claim's declared output unit; rendering performs no scientific unit conversion. Display precision uses 1..15 significant digits without turning a nonzero number into a rounded zero. The appendix links to exact asserted/recomputed values, unit contracts and tolerances in the complete audit sidecar; source locators remain visible. Display rounding never changes the verified model. A row-label column repeats when a wide table is split; every data column and row is retained. Plain text cells remain subject to semantic/claim-mapping review and are not automatically numerically certified.

## Export and layout review

Resolve formats/language from the current task. For report deliverables with unspecified formats, provide Markdown for editable prose and offline HTML for controlled reading; retain JSON for structured results. These defaults do not require report exports for a concise question or an exploratory brief. Use the same ledger and presentation configuration for both reader formats. JSON remains presentation-independent. Export PDF only when requested, with an existing compatible Chromium browser and the optional websocket-client package; do not install optional dependencies automatically or describe HTML as a completed PDF.

```text
python -B "<skill_root>/tools/write_report.py" --ledger logs/evidence_ledger.json --presentation logs/presentation.json --format markdown --output results/diagnosis.md
python -B "<skill_root>/tools/write_report.py" --ledger logs/evidence_ledger.json --presentation logs/presentation.json --format html --output results/diagnosis.html
python -B "<skill_root>/tools/check_report_layout.py" --html results/diagnosis.html --output logs/layout_checks.json --preview-dir results/previews
```

Add `--theme logs/theme.json` to report/plot commands when overriding defaults. For a requested PDF, add `--pdf results/diagnosis.pdf` to the layout command. `--browser <executable>` selects an existing Chrome/Edge/Chromium; `--static-only` records browser checks as not checked. Use fresh report basenames and check/preview/PDF paths after revisions so stale files cannot be mistaken for successful outputs. An existing audit sidecar with different content is never overwritten; the `.audit.json` suffix is reserved for these sidecars, including against direct JSON export. `--work-dir` optionally selects an existing writable parent for the temporary browser profile. Browser startup failures remain failures; the shipped tool does not weaken the browser sandbox or use a personal profile.

The checker validates local links, anchors, heading hierarchy and offline resource structure. Browser checks use DevTools to set and verify exact desktop/narrow viewport widths, then inspect horizontal overflow, decoded images and completed font loading. They do not prove glyph coverage, vertical pagination quality, chart readability, numeric agreement or aesthetics. Screenshot previews show the first viewport only; inspect figures and later sections too. PDF export success means a fresh PDF was created, not that pagination passed.

Inspect actual HTML previews and, when requested, PDF pages: no clipped/overlapping text, missing glyphs, unreadable legends, isolated headings, excessively wide tables or detached captions. Review all materially different page types and dense/long sections; extend the review when an issue appears. Check short/long, multilingual, dense-comparison and insufficient-data reports when changing reusable presentation code. Compare claims/units/item coverage across formats. Record manual reviewer, artifact hashes, reviewed scope, findings and unresolved issues under logs; do not set delivery quality to passed until required checks actually finish. The renderer preserves recorded ledger assessments and clearly distinguishes them from checks on this new export.

## Reproducibility and extension boundaries

The renderer records theme, presentation settings and resource hashes in the audit sidecar linked from the appendix and checks protected inputs for mutation before saving. Keep run presentation/theme files, commands, layout results and review records with the analysis. Preserve v2/v3 ledger compatibility and JSON output; neither layout review nor file hashes certify scientific meaning or causal truth.

Freeze retained runs before later source edits. `snapshot_report.py` creates a fresh directory with a ledger copy, referenced artifacts, renderer source tree and `snapshot_manifest.json`. It remaps paths while preserving expected artifact hashes, numerical claims and historical assessments. Export from the packaged renderer so its HTML source manifest refers to stable archived resources rather than a mutable checkout:

```text
python -B "<skill_root>/tools/snapshot_report.py" --ledger logs/evidence_ledger.json --presentation logs/presentation.json --export-audit results/diagnosis.audit.json --output-dir results/frozen
python -B results/frozen/reexport.py --output-dir results/reexported --format html
python -B "<skill_root>/tools/check_report_layout.py" --html results/reexported/report.html --output logs/frozen_layout_checks.json --static-only
```

The package directory must not already exist. New packages save the source `SKILL.md` bytes as `skill/skill_instructions.md`, with the correct new path and unchanged hash in the manifest; an already archived `skill_instructions.md` is also retained when snapshotting again. This preserves instruction evidence without creating another skill entry. Keep packages outside skill-discovery directories and leave existing packages, filenames, manifests and expected hashes unchanged. Missing/changed source or numerical artifacts are rejected. `--skill-root` identifies the original renderer tree; optional `--source-root` supplies an archived tree with exact expected tool bytes for historical recovery. A historical snapshot must still match every recorded tool hash; this is not permission to update expected hashes or to waive evidence validation. Preserve the original ledger/report and the snapshot's path mapping. Old visual/semantic review records remain historical records; perform and record checks for each new export separately. Snapshot creation neither executes archived scripts nor installs dependencies.

Pass the original `--presentation` and any `--theme` override to the snapshot. Supply the original reading edition's `<basename>.audit.json` with `--export-audit` so a mismatched ledger, missing presentation or different effective theme fails before publication. For the default presentation, omit `--presentation` on both the original export and the snapshot. The manifest records the audit hash and the comparison result. Portable re-export reapplies the archived files and checks the settings recorded in the new reading edition's sidecar. This check covers ledger and configuration consistency; inspect tables, readings and layout in the final output. A ledger-only snapshot remains possible when no source reading edition is available; its `source_reader_edition.status` is `not_checked`.

New snapshots of the current renderer package their runtime tools and explicitly referenced evidence. Maintenance `test_*.py` files enter only when the ledger references them. Alternate or explicitly recovered renderer trees retain their complete top-level Python source for compatibility.

New packages also contain a standard-library `reexport.py` entry. After relocating the entire trusted package, use the desired installed Python:

```text
python -B "<moved-package>/reexport.py" --output-dir "<fresh-sibling-export-directory>"
```

Optional repeated `--format html`, `--format markdown`, or `--format json` selects exports (default all three). The entry verifies ledger, evidence, runtime and explicit-configuration hashes before invoking the packaged renderer with that Python. It does not use historical absolute execution paths, install dependencies or rerun original analyses. `reexport_commands` remains historical provenance. A new external directory preserves prior reports and sidecars, whose absolute audit context legitimately changes after relocation. After preflight succeeds, each export attempt records commands, exit codes and integrity status in the new `reexport_result.json`; exporter failures retain their diagnostic output. Failed preflight leaves no export directory. Hashes do not establish trust in archived executable code, and successful export does not establish new visual or semantic acceptance.

Add new language, presentation or export adapters without changing the analysis model or dataset assumptions. Use fresh synthetic probes and unchanged semantic inputs to verify that a visual revision preserves evidence. Keep generated reports, screenshots, PDFs and browser profiles out of skill commits.

Design references: [Cisco technical whitepaper](https://www.cisco.com/c/en/us/products/collateral/wireless/white-paper-c11-740788.pdf), [IBM Carbon typography](https://www.carbondesignsystem.com/building-blocks/foundations/typography/style-strategies). Browser implementation references: [Chrome DevTools protocol](https://chromedevtools.github.io/devtools-protocol/) and [Chrome Headless command line](https://developer.chrome.com/docs/automation-and-testing/headless-cli). Borrow reading hierarchy and consistency; do not copy corporate branding or scientific claims.

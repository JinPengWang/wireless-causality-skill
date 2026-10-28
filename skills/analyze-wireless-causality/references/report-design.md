# Technical whitepaper reports

## Contents

- Reading structure and editorial rules
- Shared visual system and figures
- Presentation configuration and claim-backed tables
- Export and layout review
- Reproducibility and extension boundaries

## Reading structure and editorial rules

Use a restrained, single-column technical whitepaper. Lead with the question and a short executive summary, then scope/measurement definitions, observed phenomena, candidate explanations and discriminating checks. Show the four recorded assessment dimensions in a compact table. Put compact exact locators and calculation summaries in an audit appendix linked from the text. Keep complete checks, selected values, configuration, commands and rendering provenance in the linked `<report>.audit.json` sidecar, shared by Markdown/HTML editions with the same basename and semantic inputs. Do not print large raw JSON/vector records in the reading edition.

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

Start from `assets/report/presentation.template.json`. Schema version 1 supports:

- `language`: must agree with the ledger; custom languages also provide all `labels` keys in `report_labels.EN`.
- `summary_ids`: distinct existing phenomenon/finding IDs, chosen for relevance.
- `item_titles`: optional short titles keyed by existing IDs.
- `tables`: optional tables owned by an existing evidence item.

Example (replace IDs and wording with actual supported items):

```json
{
  "schema_version": 1,
  "language": "en",
  "summary_ids": ["P1"],
  "item_titles": {"P1": "Delivery comparison"},
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

Resolve formats/language from the current task. When unspecified, provide Markdown for editable prose and offline HTML for controlled reading; retain JSON for structured results. Use the same ledger and presentation configuration for both reader formats. JSON remains presentation-independent. Export PDF only when requested, with an existing compatible Chromium browser and the optional websocket-client package; do not install optional dependencies automatically or describe HTML as a completed PDF.

```text
python tools/write_report.py --ledger logs/<run>/evidence_ledger.json --presentation logs/<run>/presentation.json --format markdown --output results/<run>/diagnosis.md
python tools/write_report.py --ledger logs/<run>/evidence_ledger.json --presentation logs/<run>/presentation.json --format html --output results/<run>/diagnosis.html
python tools/check_report_layout.py --html results/<run>/diagnosis.html --output logs/<run>/layout_checks.json --preview-dir results/<run>/previews
```

Add `--theme logs/<run>/theme.json` to report/plot commands when overriding defaults. For a requested PDF, add `--pdf results/<run>/diagnosis.pdf` to the layout command. `--browser <executable>` selects an existing Chrome/Edge/Chromium; `--static-only` records browser checks as not checked. Use fresh report basenames and check/preview/PDF paths after revisions so stale files cannot be mistaken for successful outputs. An existing audit sidecar with different content is never overwritten; the `.audit.json` suffix is reserved for these sidecars, including against direct JSON export. `--work-dir` optionally selects an existing writable parent for the temporary browser profile. Browser startup failures remain failures; the shipped tool does not weaken the browser sandbox or use a personal profile.

The checker validates local links, anchors, heading hierarchy and offline resource structure. Browser checks use DevTools to set and verify exact desktop/narrow viewport widths, then inspect horizontal overflow, decoded images and completed font loading. They do not prove glyph coverage, vertical pagination quality, chart readability, numeric agreement or aesthetics. Screenshot previews show the first viewport only; inspect figures and later sections too. PDF export success means a fresh PDF was created, not that pagination passed.

Inspect actual HTML previews and, when requested, PDF pages: no clipped/overlapping text, missing glyphs, unreadable legends, isolated headings, excessively wide tables or detached captions. Review all materially different page types and dense/long sections; extend the review when an issue appears. Check short/long, multilingual, dense-comparison and insufficient-data reports when changing reusable presentation code. Compare claims/units/item coverage across formats. Record manual reviewer, artifact hashes, reviewed scope, findings and unresolved issues under logs; do not set delivery quality to passed until required checks actually finish. The renderer preserves recorded ledger assessments and clearly distinguishes them from checks on this new export.

## Reproducibility and extension boundaries

The renderer records theme, presentation settings and resource hashes in the audit sidecar linked from the appendix and checks protected inputs for mutation before saving. Keep run presentation/theme files, commands, layout results and review records with the analysis. Preserve v2/v3 ledger compatibility and JSON output; neither layout review nor file hashes certify scientific meaning or causal truth.

Add new language, presentation or export adapters without changing the analysis model or dataset assumptions. Use fresh synthetic probes and unchanged semantic inputs to verify that a visual revision preserves evidence. Keep generated reports, screenshots, PDFs and browser profiles out of skill commits.

Design references: [Cisco technical whitepaper](https://www.cisco.com/c/en/us/products/collateral/wireless/white-paper-c11-740788.pdf), [IBM Carbon typography](https://www.carbondesignsystem.com/building-blocks/foundations/typography/style-strategies). Browser implementation references: [Chrome DevTools protocol](https://chromedevtools.github.io/devtools-protocol/) and [Chrome Headless command line](https://developer.chrome.com/docs/automation-and-testing/headless-cli). Borrow reading hierarchy and consistency; do not copy corporate branding or scientific claims.

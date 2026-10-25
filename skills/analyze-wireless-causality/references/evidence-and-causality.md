# Evidence and causal reasoning

Keep observations, explanations and interventions separate. Use these operational labels, not numerical cause probabilities:

- `observed`: a reproducible measurement or phenomenon.
- `candidate`: a plausible mechanism with incomplete supporting tests.
- `supported_candidate`: consistent temporal/mechanistic evidence with explicit alternatives still possible.
- `validated_mechanism`: a documented identification/experimental design, independent replication and reviewer assessment support a scoped mechanism.
- `unresolved` / `refuted`: state the missing discriminator or the contradicting evidence.

Ranking is a decision aid, not validation by itself. Use an explicit ordinal priority with reasons: evidence quality, impact consistent with the outcome, replication, temporal ordering, resistance to competing explanations and actionable follow-up. Do not convert these dimensions into an arbitrary confidence percentage. Avoid double-counting multiple indicators of the same latent process.

Each finding must specify the phenomenon it explains, a mechanism, what would be expected if true, source-linked support, counterevidence, validity limits and a next discriminating test. Compare cases where the suspected factor changes without the symptom and where the symptom occurs without that factor. Check whether apparent parameter changes are consequences of an already deteriorating link.

Statistical association, Granger-style predictability, feature importance, a discovered edge and an anomalous parameter are not interchangeable with causal identification. A short-window association cannot distinguish all feedback and unmeasured common causes. Selecting only extreme outcomes or only 'clean' references can introduce selection bias.

For intervention effects, define a manipulable treatment, outcome, time horizon, population and estimand. Select a valid design: randomized repeated interventions, justified observational adjustment, interrupted series, or another defensible approach. Verify exchangeability/randomization, common support, consistency, temporal alignment, carryover and dependent units as applicable. Do not adjust away mediators when estimating total effects. In closed-loop systems, past treatment can influence future confounders; simple static adjustment may be inadequate.

Use counterfactual or individual-event attribution only under an independently supported structural model and explicit assumptions. Otherwise describe a prioritized diagnostic candidate. Do not assign an unobserved treatment from a throughput threshold or periodicity alone.

Preserve failed hypotheses and sensitivity results. Select/tune on discovery runs and assess on held-out independent runs when available. For small samples, report descriptive contrasts and uncertainty limitations rather than creating false precision. A failed falsification attempt is not proof that identifying assumptions hold.

The version 2 Markdown report generator checks evidence and figure hashes, image structure, supported locator existence, phenomenon links and required validation records. JSON pointers and physical line ranges are machine checked. A whole-file locator establishes only file scope; a descriptive locator remains unverified. Legacy ledgers need an explicit migration to the current template. Report output cannot replace its inputs or evidence artifacts. A filled JSON field is an attestation, not automatic confirmation that an experiment was valid.

# End-to-end bottlenecks and event investigation

Start from the requested outcome and decision. A throughput dip, stable plateau, jitter, slow convergence or device contrast is a possible phenomenon, not an assumed finding. Preserve ordinary and counterexample runs alongside anomalies. Use the same population definitions, eligibility rules and statistical policies for every compared device; explain justified deviations.

## Map the measured path

Describe offered traffic, sender, host stack, wired interfaces/path, AP or bridge, wireless link, peer, receiver and measurement locations as applicable. Separate traffic direction and control/acknowledgement direction. Compare measurements at their actual layer and endpoint. PHY rate, observed air-interface bytes, application goodput and offered load are not interchangeable.

Use a run-specific capability/competition table. The following rows are prompts for checking available evidence, not mandatory sensors or diagnostic rules:

| Explanation family | Useful discriminators when measured | Alternatives and common ambiguities |
|---|---|---|
| Offered load / application | Intended versus actual offered traffic, sender pacing, flow/session lifecycle, transport mode | Radio degradation can reduce sender output through feedback; a load drop can also originate upstream |
| Sender/receiver endpoint | CPU scheduling, socket/driver drops, processing queues, receive limits, offload/capture point | A busy endpoint may be an effect or a capture artifact; one host average can hide a bottleneck |
| Wired path / interfaces | Negotiated links, errors/drops, queues, port counters, cross traffic, an independent wired baseline | A numerical plateau alone does not establish a link speed, shaper or vendor limit |
| Wireless / control | Channel occupancy, measured propagation, retry burden, adaptation, scheduling, acknowledged delivery | Contention, interference, receiver behavior, load feedback and capture loss can produce similar traces |
| Transport / feedback | RTT, congestion/recovery evidence, loss accounting, pacing and acknowledgements | Transport symptoms do not alone locate the loss or prove wireless causation |
| Measurement / timing | Capture completeness, counter semantics, endpoint clocks, decoding and window boundaries | Missing observations, duplicated frames and uncertain alignment can manufacture apparent loss or response order |

For each family record `available`, `conditional` or `unavailable`, inspected evidence, consistency with the phenomenon, counterevidence, and the next discriminating measurement. An unmeasured layer is unknown, not healthy. Do not require all measurements before doing useful analysis. Choose follow-up checks by how well they distinguish remaining explanations and by their practical cost.

## Use events as observations, not automatic interventions

Record whether each anchor is external, assumed from a schedule, or selected from the outcome itself. Keep source provenance, coordinate transforms and uncertainty bounds. A filename or periodic drop is not an independent intervention log. Compare event-negative cases and repeated events without treating every event/window as a new independent experiment.

`event_analysis.py` consumes normalized interval means and explicit event-to-recording mappings. It can summarize multiple named layers without fixed field names, filenames or phase durations:

```text
python tools/event_analysis.py --request logs/<run>/event_request.json --output logs/<run>/event_results.json
```

Copy `assets/event_request.template.json`. Configure the pre/post ranges, selected signals, anchor uncertainty and each signal's relative clock-error bound. Input signals must already use the declared common anchor coordinate. The tool does not fit clock transforms or infer movement labels. One recording must retain the same independent unit across events.

Per event and signal, retain duration-weighted pre/post interval means, observed exposure, coverage, selected input window indices and the nominal contrast. By default, exclude windows that straddle requested phase boundaries. `split_policy: uniform` explicitly assumes a constant mean within such windows; it is an assumption, not recovered sub-window detail. Partially observed windows are excluded because their within-window coverage is unknown. Other estimands require a reviewed adapter rather than averaging ratios or counts as interval means.

If an uncertainty is unknown, report nominal alignment only. With known anchor and relative clock bounds, propagate their sum conservatively; check whether both comparison phases are separated from the uncertain anchor. Do not interpret an unresolved ordering as measured response latency.

An optional signal threshold, bad direction and hold duration locate sustained threshold-classified intervals. Record the onset window, gaps and left/gap censoring. Returned timing bounds concern threshold-bin classification, not the physical onset of a mechanism. A recording that starts or resumes already abnormal cannot establish when deterioration began. No observed crossing within follow-up is not evidence that a mechanism never acted.

Use `detect_events.py` for excursion duration, deficit and sustained recovery/censoring in a selected series. Use the event-relative tool for cross-layer context and externally anchored comparison. Add tailored analyses of hysteresis, variability, convergence or recovery only when the data resolve them; keep selection and censoring rules explicit. Neither tool automatically identifies an intervention effect.

## Candidate record

Every mechanism candidate must state:

1. The phenomenon(s) and scope it explains.
2. A falsifiable expected observation, including timing only where identifiable.
3. Its strongest alternative explanation.
4. Current support and the strongest existing counterevidence, including cases without the symptom.
5. The next check that can distinguish the explanations, and what result would weaken each one.

A high retry count, a rate plateau, an AP difference or a successful optimization is task-specific evidence. Do not turn it into a universal diagnosis threshold, device ranking or prescribed optimization. Report a useful narrowed candidate set when identification is not possible, together with the relation exploration and discriminating checks actually completed.

# Metrics and time

## Three different rates

1. **Application receive throughput:** `8 * received_application_bytes / elapsed_seconds`. Prefer receiver-side measurements for delivery claims. State transport, stream aggregation, endpoint and units. Keep sender-side values separate. iperf client/server roles do not alone determine traffic direction; reverse mode changes the sender [1].
2. **Capture-derived delivery estimate:** only when reception/ACK evidence, payload definitions and deduplication support it. State capture incompleteness and acknowledgment matching assumptions. Observed frame bytes per second are a capture traffic rate, not verified delivered goodput.
3. **Effective PHY-rate proxy:** `R_window * (1 - PER_window)`. Honor this requested comparison metric when both quantities are defensible, label it explicitly and show application throughput separately. It does not account for all channel access, framing, aggregation, acknowledgment, idle-time or transport overhead [2].

For variable rates, declare how `R_window` is weighted (attempt, byte, airtime or another defensible measure). If rate/error strata are available, also inspect `sum(weight_k * R_k * (1 - PER_k))`; it generally differs from multiplying two pooled means. Do not mix populations or compare different weighting schemes silently.

## Error and retry definitions

Specify whether PER concerns transmission attempts, first attempts, final delivery failures, MPDUs or another unit. Use `sum(failed)/sum(eligible)` within each common window. A retry flag means a transmission is a retry; its fraction is not universally equal to any of these PER definitions. A missing sequence number may be an uncaptured frame rather than a lost frame. Zero-denominator windows are missing, not error-free.

Report the raw counts, observation coverage and censoring. Missing ACKs can be capture loss; zero BA bits can refer to sequence positions not transmitted in the observed exchange. Do not replace unknown outcomes with failures.

## Window policy

There is no universal PER measurement window established by the sources used here for arbitrary passive captures. iperf's documented default reporting interval is a software default, not a PER standard [1]. Select a common primary time grid based on:

- The mechanism's plausible delay and the measurement refresh/aggregation periods.
- Timestamp and alignment uncertainty.
- Sufficient valid trials per window and comparable coverage across entities.
- Retention of short events without letting very small denominators dominate.

Record the choice before examining vendor rankings. Use a small prespecified sensitivity set, e.g. coarser and finer grids around that primary choice; these are task parameters, not universal constants. Flag low-count windows. Retain invalid-source-row lists and sample counts. An event-sum window with an unknown amount has an unknown total; complete capture does not repair a missing decoded value. A validated complete empty event population can have a zero count/rate, whereas an incomplete empty capture remains missing. Independent-binomial intervals are inappropriate when attempt outcomes are materially dependent; use run/block-aware uncertainty with explicit assumptions.

Never compress missing time. Preserve discontinuities and measurement masks. Do not bridge long gaps by interpolation. Amount splitting across source interval boundaries assumes uniform accrual unless finer observations exist; make that assumption explicit or choose aligned/coarser bins.

## Semantic checks

Check plausible field ranges before numerical integration. An exported length much larger than any plausible row object can indicate decoding, encryption, endian or field-selection issues. Preserve the raw value and classify the field as unresolved. Do not derive airtime from an ambiguous `Duration` column: an 802.11 Duration/ID value can be a reservation value, not measured frame airtime.

Sources: [1] https://software.es.net/iperf/invoking.html ; [2] https://inet.omnetpp.org/docs/showcases/wireless/throughput/doc/index.html

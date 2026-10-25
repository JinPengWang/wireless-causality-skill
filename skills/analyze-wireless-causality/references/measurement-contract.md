# Measurement and adapter contract

Keep acquisition metadata outside reusable code. Create one resolved run manifest with source hashes, clock definitions, topology, comparison factors, field mappings, available capabilities and unresolved contradictions.

## Common semantic model

Use protocol-neutral identities: run/session, entity, peer entity, link, direction, scenario/condition, source and independent experimental unit. Map AP/STA into these roles for Wi-Fi; map other technologies explicitly. A link handle, interface index or file serial number is not automatically a device identity or independent replicate.

A measurement specifies: name, layer, direction, physical/statistical unit, value type, numerator, denominator, eligible population, time interval, source location, validity and interpretation. Preserve primitive fields alongside derived metrics. A shared `measurement_id` is an explicit assertion that normalized layer, eligibility, unit, direction and weighting agree across sources; record the reviewed definition in the run manifest. Without that identifier, the tools require identical definitions. A shared label must not conceal different estimands. Track cumulative counters separately from interval amounts. Difference cumulative counters only within the same identity and continuity segment; treat resets and unknown rollover as missing transitions.

For packets, record whether a row is an MPDU, MSDU, aggregate, control frame, application interval or another object. Frame length, payload length and successfully delivered bytes are not interchangeable. Do not count the same payload once per retransmission or once at multiple observation points.

## Adapter responsibilities

Implement only source-specific reading, decoding, mapping and normalization. Declare:

- Supported formats and protocol/export versions; exact header and value mappings.
- Timestamp interpretation, unit conversion, interval construction and source-row provenance.
- Categorical values and explicit parsers for hexadecimal numbers, unit-bearing strings and flags.
- Sentinels, valid ranges, reset rules, duplicate semantics and unsupported variants.
- Capability predicates, including required combinations of fields.
- Known ambiguity and validation fixtures.

Keep filename parsing optional and configurable. Record metadata origin as user-supplied, instrument-recorded, filename-derived or inferred. Retain conflicts instead of silently overwriting them. Validate units against measurement content and instrument documentation.

## Capture pairing and clock alignment

Match application and radio files by run identity, endpoints, direction, acquisition conditions and actual temporal overlap. Hash both sources. Do not pair every similarly named file.

Represent clock transforms explicitly, such as `t_common = offset_s + scale * t_source`, with anchor evidence and uncertainty. Distinguish clock offset, drift and genuine network/measurement delay. Cross-correlation can suggest an offset but cannot establish it independently when the analysis concerns causal lag. Do not silently shift signals until their peaks agree.

Keep coarse application measurements at their actual intervals. Aggregating radio observations onto those intervals is generally preferable to pretending interpolated application values are new high-rate observations.

## Extending beyond Wi-Fi

Map semantic roles, not spelling. A configured audio bitrate, a Wi-Fi PHY rate and an application goodput are distinct measurements. A timeout counter need not represent audible stutter. An RSSI-like uncalibrated number is not automatically dBm. Transfer comparison and evidence logic only after these distinctions are explicit.

The generic tools can consume any protocol's normalized intervals. New telemetry with unfamiliar counters or formats needs an adapter and tests, not changes to the comparison or reporting code.

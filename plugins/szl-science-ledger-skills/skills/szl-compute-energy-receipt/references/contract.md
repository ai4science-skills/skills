# Energy receipt contract

Classes: MEASURED (counter source in {nvml, rapl, metered_plug, pdu, ipmi} with >= 2 finite samples, monotone
time, max gap <= `max_gap_s`, default 5 s), REPORTED (single total, TDP x duration, vendor/estimate source, or
samples with gaps above the limit), UNAVAILABLE (nothing usable; the reason is recorded in `energy.note`).

Energy is the trapezoidal integral of watts over seconds. kWh = J / 3.6e6. CO2e grams = kWh x
`grid.g_co2e_per_kwh`, only when `grid.source` is a non-empty string; class REPORTED always.

`receipt_sha256` covers the receipt body before `status`. The methods sentence is generated from the
typed fields and states the class explicitly.

# PortOps Demo — Document Synthesis

All Run B documents are synthesized for the PortOps multimodal benchmark (public-style
operational data, no real company). Intent of each artifact:

## berth_schedule.csv
Fictional vessel traffic for "Meridian Harbour" across 5 berths over
December 2026. Columns: vessel, imo, eta, etd, berth, cargo, agent, loa_m,
draft_m. Contains the ground truth for berth-assignment and next-arrival
questions. 22 vessels, mixed cargo types, deliberately overlapping windows.

## bunker_prices.csv
Bunker price sheet: port, supplier, fuel_grade (VLSFO/HSFO/MGO),
price_usd_ton, valid_from. Three suppliers, grades vary by supplier so
lookup questions have a unique answer.

## port_tariffs.md
The arithmetic backbone: port dues per GT with a call minimum, berth
occupancy day-rates with a step after day 3, demurrage free time + per-day
charge, pilotage bands by LOA, tug rules, and a weather-stoppage rule
(operations suspended at wind > 25 m/s or swell > 3.5 m — the hook for the
open-meteo tool). All numbers chosen to make deterministic recomputation
by the judge's calculator exact.

## brief.md
One paragraph from a port operations coordinator: turnaround questions,
berth lookups, fee/demurrage arithmetic, current sea conditions at the
port (51.95 N, 4.14 E), next arriving vessel; refuse crew-visa and
cargo-insurance topics.

Regeneration: these documents are deterministic artifacts authored for the
demo; the synthesis intent above is the generation prompt of record.

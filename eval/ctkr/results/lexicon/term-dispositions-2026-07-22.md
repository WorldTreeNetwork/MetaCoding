# Term-proposal dispositions — 2026-07-22 (Duke)

16 open proposals from `term-proposals-log-family.jsonl` (4 others became the
io6 binding batch). Dispositioned by Duke via elicitation; standing policy set:
**identity terms bind DURING their feature's port** — when the recipe already
has the oracle warm — not speculatively before.

| # | term | disposition | why |
|---|---|---|---|
| 2,3,4,19 | conduct_laboratory_test, maintenance, transplant, medical | **DECLINED as terms** | They are features, not vocabulary: `record_log` already takes arbitrary kinds (wave 1 ported four log types with zero per-kind verbs). They enter the port inventory; their identity lives in their fields. |
| 13 | birth_mother | **BIND NOW** | Write path exists (`record_birth` takes parents), so a discriminating pack is authorable today; sharpens bound lineage semantics (the dam specifically vs generic `has_parent`). |
| 12,14,16 | application_method, purchase_date, input_provenance | **APPROVED, blocked on MetaCoding-xdt** | Input is ported (1/5 identity coverage — these raise it) but `record_log` has no write path for them; a pack could only observe `''` and the gate would rightly refuse (the lot_number lesson). Bind the moment the write-surface batch lands. |
| 18 | veterinarian | **APPROVED, blocked on MetaCoding-xdt** | Same write-path cap (`record_birth` takes no vet arg). |
| 1,6,8,9,10,15 | lab_sample_type, lab_test_measurement, laboratory, lab_processing_date, sample_received_date, soil_texture | **BIND-WITH-FEATURE (lab_test)** | Six terms, one feature's identity — the most lexically distinctive module in the family. Its identity-tier recipe observes and binds them in one pass. |
| 17 | days_to_transplant | **BIND-WITH-FEATURE (seeding/transplanting)** | Plant-type taxonomy planning field; travels with its feature. |

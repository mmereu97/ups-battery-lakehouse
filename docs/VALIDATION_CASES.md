# Known-good validation cases

Real replacements performed by the owner on his own UPS units. The Gold
compatibility logic must reproduce these — they play the same role the
"top 3 elite films" assertion played in the Cinemateca lakehouse: a ground
truth the pipeline is regression-tested against.

| # | UPS | Correct battery | The trap |
|---|-----|-----------------|----------|
| 1 | APC BVX2200LI / BVX2200LI-GR | 2 × Leoch DJW12-9.0 — 12 V, 9 Ah, AGM, wired in series (24 V) | needs **two identical units**, not one |
| 2 | APC Back-UPS 500VA | CSB UPS 12240 6 F2 — 12 V, 6 Ah, **151 × 51 × 94 mm**, F2 terminals (6.35 mm) | ordinary 12 V 7 Ah batteries are **65 mm wide, not 51** — they physically do not fit |

Assertions to encode:

1. For case 2, a naive V+Ah match (12 V ≥6 Ah) must NOT return a plain
   7 Ah / 65 mm battery as compatible once width tolerance is enforced:
   candidate dimensions must be **≤ the original's** (with a small
   tolerance), never "close enough" upward.
2. Terminal normalization: T1 = F1 = 4.8 mm, T2 = F2 = 6.35 mm — shop
   listings use T-codes, datasheets use F-codes; they must unify.
3. High-rate models encode watts-per-cell in the part number
   (e.g. CSB UPS 12240 → 240 W/cell; HR1234W → 34 W/cell): derive
   `watts_per_cell` from part-number patterns where present.
4. Equivalence groups build on: same voltage AND capacity within tolerance
   AND dimensions within tolerance AND compatible terminals — plus the
   shop's own `replaced_numbers` lists (OEM cross-references, incl. APC
   RBC codes) as explicit edges.

Known limitation (documented, not solved in v1): how many batteries a UPS
needs and their wiring (series/parallel) is not exposed by the scraped
sources; partially derivable from APC RBC pack definitions. Listed under
next steps.

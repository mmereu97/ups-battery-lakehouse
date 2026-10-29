"""Extract technical specifications from battery datasheet PDFs.

"Document-extracted data": pdfplumber pulls the text out of each PDF in
data/datasheets/ and a set of labelled regex patterns reads the spec block.
The patterns cover the two layout families seen in this catalogue:

  * Ultracell-style ("Nominal Voltage 12V", "Length: 151 ± 2 mm", ...) —
    used both by Ultracell's official sheets and 123accu's house sheets
  * CSB-style ("Voltage (Vdc) 12", "Length (L) (mm / in) 150.9±2.0", ...)

Everything is kept honest, Bronze-style: parsed fields where a pattern
matched, None where it did not, plus the full raw text for later reference —
normalization and validation happen in Spark, not here.

Usage:
    python extract_datasheets.py [pdf_dir] [out_dir]
Defaults:
    pdf_dir = data/datasheets, out_dir = data/raw/datasheets
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

NUM = r"(\d+(?:[.,]\d+)?)"

# field -> list of alternative patterns (first match wins)
PATTERNS: dict[str, list[str]] = {
    "part_number": [rf"Part Number:\s*(\S+)"],
    "voltage_v": [
        rf"(?:Nominal|Normal|Output Nominal)\s+Voltage\s*{NUM}\s*V",
        rf"Voltage\s*\(Vdc\)\s*{NUM}",
    ],
    "capacity_ah": [
        rf"(?:Nominal|Normal)\s+Capacity\s*\(20\s*HR?\)\s*{NUM}\s*A[Hh]",
        rf"Nominal Capacity[\s\S]{{0,40}}?{NUM}\s*Ah\s*@\s*20hr",
        rf"Rated Capacity\s*{NUM}\s*AH?/",
    ],
    "length_mm": [
        rf"Length:?\s*{NUM}\s*±",
        rf"Length\s*\(L\)\s*\(mm\s*/\s*in\)\s*{NUM}",
    ],
    "width_mm": [
        rf"Width:?\s*{NUM}\s*±",
        rf"Width\s*\(W\)\s*\(mm\s*/\s*in\)\s*{NUM}",
    ],
    "container_height_mm": [
        rf"Container Height:?\s*{NUM}\s*±",
        rf"Height\s*\(H\)\s*\(mm\s*/\s*in\)\s*{NUM}",
    ],
    "total_height_mm": [rf"Total Height[^:]*:?\s*{NUM}\s*±"],
    "weight_kg": [
        rf"(?:Approx\.?\s+)?Weight:?\s*Approx\.?\s*{NUM}\s*kg",
        rf"Weight\s*\(kg\.?\s*/\s*lb\.?,?\s*Approx\.?\)\s*{NUM}",
        rf"{NUM}\s*kg\s*Approx",
    ],
    "terminal": [
        r"Terminal Type\s+(?:Standard Terminal\s+)?(F\d+|T\d+)",
        r"Terminal Type\s+(F\d+)\s+terminal",
    ],
    "max_discharge_a": [rf"Max\.?\s+Discharge Current(?:\s*\(A\))?\s*{NUM}"],
    "internal_resistance_mohm": [
        rf"Internal Resistance(?:\s*\(m[ΩO]\))?\s*Approx\.?\s*{NUM}"
    ],
    "design_life_years": [
        rf"Design (?:Floating )?Life.{{0,40}}?{NUM}\s*Years",
        rf"Up to\s*{NUM}\s*Years in Standby",
    ],
}


def to_float(s: str) -> float:
    return float(s.replace(",", "."))


def extract_one(pdf_path: Path) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
    record: dict = {
        "file": pdf_path.name,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": n_pages,
    }
    for field, patterns in PATTERNS.items():
        value = None
        for pat in patterns:
            m = re.search(pat, text, flags=re.IGNORECASE)
            if m:
                raw = m.group(1)
                value = raw if field in {"part_number", "terminal"} else to_float(raw)
                break
        record[field] = value

    # Fallback for drawing-style dimension lines ("Technical Dimensions (mm)
    # 99±3 93.5±3 65±3 151±3"): assign by magnitude — length is the largest,
    # width the smallest, the middle two are total/container height.
    if record["length_mm"] is None:
        m = re.search(
            rf"Technical Dimensions \(mm\)\s*((?:{NUM}\s*±\s*\d+\s*){{3,4}})", text
        )
        if m:
            nums = sorted(to_float(n) for n in re.findall(NUM + r"\s*±", m.group(1)))
            if len(nums) >= 3:
                record["width_mm"] = nums[0]
                record["length_mm"] = nums[-1]
                record["container_height_mm"] = nums[1]
                if len(nums) == 4:
                    record["total_height_mm"] = nums[2]

    # Part-number fallback: the model code in the first few text lines
    # (UL7-12, GPL 1272, HR1234W ...).
    if record["part_number"] is None:
        for line in text.strip().splitlines()[:4]:
            m = re.search(r"\b([A-Z]{2,4}\s?\d[\w.-]*)\b", line)
            if m:
                record["part_number"] = m.group(1).replace(" ", "")
                break

    n_parsed = sum(1 for f in PATTERNS if record.get(f) is not None)
    record["fields_parsed"] = n_parsed
    record["raw_text"] = text
    return record


def main() -> None:
    pdf_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/datasheets")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/raw/datasheets")
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"datasheets_{stamp}.jsonl"

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    print(f"{len(pdfs)} PDFs in {pdf_dir}")
    with out_path.open("w", encoding="utf-8") as fh:
        for pdf_path in pdfs:
            try:
                record = extract_one(pdf_path)
            except Exception as exc:  # noqa: BLE001 — quarantine, don't crash
                record = {"file": pdf_path.name, "error": str(exc), "fields_parsed": 0}
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  {record.get('fields_parsed', 0):>2} fields  {pdf_path.name}")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

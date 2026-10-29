"""Unit tests for the datasheet spec-extraction patterns.

Run with:  python -m pytest tests/ -v
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper"))

from extract_datasheets import PATTERNS, to_float

ULTRACELL_STYLE = """UL 12-6
6V 12AH
Part Number: UL12-6
Length: 151 ± 2 mm (5.94 inches)
Width: 51 ± 2 mm (2.01 inches)
Container Height: 94 ± 2 mm
Total Height (with terminal): 100 ± 2 mm
Approx Weight: Approx 1.62kg
Normal Voltage 6V
Normal Capacity (20HR) 12AH
Terminal Type Standard Terminal F1
Max Discharge Current 180A (5s)
Internal Resistance Approx 15mΩ
Design Floating Life at 20°C 5 Years
"""

CSB_STYLE = """GPL Series
GPL 1272 Datasheet
Voltage (Vdc) 12
Nominal Capacity
7.2 Ah @20hr-rate
Max Discharge Current (A) 130 *
Internal Resistance (mΩ) Approx. 22.0
Terminal Type F2 terminal -Faston Tab 250 *
Weight (kg. / lb., Approx.) 2.60 / 5.73
Length (L) (mm / in) 150.9±2.0 / 5.94±0.08
Width (W) (mm / in) 64.8±1.0
Height (H) (mm / in) 98.6±1.0
Up to 8 Years in Standby Service at 25°C
"""


def first_match(field, text):
    for pat in PATTERNS[field]:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


class TestUltracellStyle:
    def test_core_fields(self):
        assert first_match("part_number", ULTRACELL_STYLE) == "UL12-6"
        assert to_float(first_match("voltage_v", ULTRACELL_STYLE)) == 6.0
        assert to_float(first_match("capacity_ah", ULTRACELL_STYLE)) == 12.0
        assert to_float(first_match("width_mm", ULTRACELL_STYLE)) == 51.0
        assert first_match("terminal", ULTRACELL_STYLE) == "F1"
        assert to_float(first_match("design_life_years", ULTRACELL_STYLE)) == 5.0


class TestCsbStyle:
    def test_core_fields(self):
        assert to_float(first_match("voltage_v", CSB_STYLE)) == 12.0
        assert to_float(first_match("capacity_ah", CSB_STYLE)) == 7.2
        assert to_float(first_match("length_mm", CSB_STYLE)) == 150.9
        assert to_float(first_match("width_mm", CSB_STYLE)) == 64.8
        assert first_match("terminal", CSB_STYLE) == "F2"
        assert to_float(first_match("max_discharge_a", CSB_STYLE)) == 130.0
        assert to_float(first_match("design_life_years", CSB_STYLE)) == 8.0


def test_to_float_handles_comma():
    assert to_float("4,5") == 4.5

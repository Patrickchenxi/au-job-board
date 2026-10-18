"""Focused offline salary regressions, using only handwritten synthetic inputs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobs.salary import extract, parse  # noqa: E402


class SalaryTests(unittest.TestCase):
    def amounts(self, text, low, high, period="year"):
        result = parse(text)
        self.assertIsNotNone(result, text)
        self.assertEqual((result["min"], result["max"]), (low, high), text)
        self.assertEqual(result["period"], period)
        multiplier = {"year": 1, "hour": 1976, "day": 260, "month": 12}[period]
        self.assertEqual(result["annual_min"], None if low is None else low * multiplier)
        self.assertEqual(result["annual_max"], None if high is None else high * multiplier)
        return result

    def test_percent_is_not_money(self):
        for percent in ("11.5%", "12.5%", "12%", "11.50 %", "0.5%"):
            with self.subTest(percent=percent):
                self.amounts(f"$40 per hour + {percent} super", 40, 40, "hour")
                self.assertIsNone(parse(f"{percent} super per hour"))

    def test_decimal_money_survives_percentage_guard(self):
        self.amounts("$40.50 per hour + 11.5% super", 40.5, 40.5, "hour")
        self.amounts("$78,154.75 per annum + 12.5% super", 78154.75, 78154.75)
        self.amounts("$40.50 - $45.75 per hour", 40.5, 45.75, "hour")
        self.amounts("$40 per hour.", 40, 40, "hour")
        self.amounts("Salary,$40.50 per hour", 40.5, 40.5, "hour")

    def test_shared_k_range(self):
        for text in ("$80 - 100k per annum", "80-100k per annum",
                     "$80 - $100k per annum", "AUD 80 to 100K per annum",
                     "80–100k", "80—100k", "80.5-100.5k per annum",
                     "Band 5 salary $80-100k per annum"):
            with self.subTest(text=text):
                low, high = (80500, 100500) if "80.5" in text else (80000, 100000)
                self.amounts(text, low, high)

    def test_explicit_ranges_and_modes(self):
        self.amounts("$80k - $100k per annum", 80000, 100000)
        self.amounts("$80,000 - $100k per annum", 80000, 100000)
        self.amounts("$100k - $80k per annum", 80000, 100000)
        self.amounts("$80k per annum", 80000, 80000)
        self.amounts("Up to $100k per annum", None, 100000)
        self.amounts("$80k and above per annum", 80000, None)
        self.amounts("$80k or more per annum", 80000, None)
        self.amounts("AUD 400 - 700 per day", 400, 700, "day")
        self.amounts("$5000 per month", 5000, 5000, "month")

    def test_no_unmarked_scale_guess(self):
        for text in (None, "", "Competitive", "$80 - 100 per annum"):
            with self.subTest(text=text):
                if text == "$80 - 100 per annum":
                    # No k marker: preserve explicit numbers, never invent thousands.
                    self.amounts(text, 80, 100)
                else:
                    self.assertIsNone(parse(text))
        self.amounts("Band 5 $78,154.75 per annum", 78154.75, 78154.75)
        self.assertIsNone(parse("$80 - 100"))
        self.assertIsNone(parse("80 - 100 per annum"))
        self.amounts("$80,000 - $100,000 per annum", 80000, 100000)
        self.amounts("$800 - $1k per annum", 800, 1000)

    def test_extract_keeps_correct_field_amounts(self):
        for text, low, high in (("$40 per hour + 11.5% super", 40, 40),
                                ("$80 - 100k per annum", 80000, 100000)):
            with self.subTest(text=text):
                result = extract(text, "", [])
                self.assertIsNotNone(result)
                self.assertEqual((result["min"], result["max"]), (low, high))
                self.assertEqual(result["origin"], "field")
                self.assertEqual(result["hint"], 0)


if __name__ == "__main__":
    unittest.main()

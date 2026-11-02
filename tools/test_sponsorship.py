"""Offline checks for the optional sponsorship add-on (jobs/sponsorship*.py).

Every employer name, ad and file below is handwritten synthetic data in a
temporary directory. No network: urllib and sockets are patched to fail unless a
test supplies a fake response.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from jobs import cli, db, sources, sponsorship, sponsorship_fit, sponsorship_panel  # noqa: E402

ACCREDITED = """Freedom of Information Request - FA 00/00/00000
SYNTHETIC CLOUDWORKS PTY LTD
Example Freight Holdings Limited
Sample Wholesale Australia Pty Ltd
001
"""
SANCTIONS = {"d": {"success": True, "data": [
    {"sponsorname": "Fictional Bakery Partners Pty Ltd", "tradingname": "Fictional Bakery Partners",
     "abn": "00000000000", "sanctionimposed": "Sanction bar", "sanctionimposeddatetext": "01-Jan-2020",
     "sanctionenddate": "01-Jan-2021", "state": "VIC"},
    {"sponsorname": "Holding Entity One Pty Ltd", "tradingname": "Placeholder Cafe",
     "abn": "11111111111", "sanctionimposed": "Sanction bar", "sanctionimposeddatetext": "02-Feb-2021",
     "sanctionenddate": "", "state": "NSW"},
]}}
ASX = "ASX listed companies as at synthetic\n\nCompany name,ASX code,GICS industry group\n" \
      '"SYNTHETIC CLOUDWORKS LIMITED","SYN","Software & Services"\n'

SDR_AD = ("Synthetic Cloudworks builds SaaS software for small businesses. As a Sales Development "
          "Representative you will book meetings for account executives. " * 3)


def _blocked(*_args, **_kwargs):
    raise AssertionError("network forbidden")


class Matching(unittest.TestCase):
    def test_accredited_exact_fuzzy_and_unrelated(self):
        index = sponsorship.NameIndex(["SYNTHETIC CLOUDWORKS PTY LTD", "Sample Wholesale Australia Pty Ltd"])
        self.assertEqual(index.match("Synthetic Cloudworks")[0], "exact")
        self.assertEqual(index.match("Sample")[0], "fuzzy")          # listed name adds a known tail
        self.assertEqual(index.match("Synthetic Bakery"), (None, None))
        self.assertEqual(index.match("Pty Ltd"), (None, None))

    def test_sanctions_confirmed_only_on_two_word_legal_name(self):
        register = sponsorship.Sanctions(SANCTIONS["d"]["data"])
        self.assertEqual(register.match("Fictional Bakery Partners Pty Ltd")[0], "confirmed")
        self.assertEqual(register.match("Placeholder Cafe")[0], "possible")   # trading name only
        self.assertEqual(register.match("Unrelated Example"), (None, None))

    def test_accredited_file_drops_ocr_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "accredited-synthetic.txt").write_text(ACCREDITED, encoding="utf-8")
            names = sponsorship.load_accredited(Path(tmp))
        self.assertEqual(len(names), 3)
        self.assertNotIn("001", names)


class AdText(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(sponsorship.scan_ad("Applicants must be an Australian citizen.")[0], "pr_only")
        self.assertIsNone(sponsorship.scan_ad(
            "Applicants must be an Australian citizen, permanent resident or hold a valid visa.")[0])
        self.assertEqual(sponsorship.scan_ad("Unfortunately we cannot offer visa sponsorship.")[0], "no")
        self.assertEqual(sponsorship.scan_ad("Visa sponsorship is available for the right candidate.")[0], "offers")
        self.assertEqual(sponsorship.scan_ad("A synthetic ad with nothing relevant."), (None, None))


class Likelihood(unittest.TestCase):
    company = {"asx": None, "ato": None}

    def assess(self, title, check, description=SDR_AD, salary=None, company=None):
        job = {"title": title, "company": "Synthetic Cloudworks", "description": description,
               "annual_min": salary, "annual_max": salary}
        base = {"acc": None, "ad": None, "agency": False, "sanction": None, "sanction_level": None}
        return sponsorship_fit.assess(job, {**base, **check}, company or self.company)

    def test_points_add_up_and_are_listed(self):
        fit = self.assess("Sales Development Representative", {"acc": "exact"})
        # 20 base + 35 accredited + 15 likely occupation (ICT Sales Representative) + 0 salary unknown
        self.assertEqual(fit["likelihood"], 70)
        self.assertEqual(fit["rating"], "high")
        self.assertTrue(fit["certain"])
        self.assertEqual(fit["occupation"]["code"], "225213")
        self.assertIn(("fit.r_accredited", {}, 35), fit["reasons"])

    def test_ad_rules_out_and_sanction_caps(self):
        self.assertEqual(self.assess("Sales Development Representative", {"ad": "no"})["likelihood"], 0)
        fit = self.assess("Sales Development Representative",
                          {"acc": "exact", "sanction": {"date": "01-Jan-2020"}, "sanction_level": "confirmed"})
        self.assertLessEqual(fit["likelihood"], sponsorship_fit.SANCTION_CAP)
        self.assertFalse(fit["certain"])

    def test_role_signals(self):
        self.assertEqual(self.assess("Retail Sales Assistant", {})["occupation"]["confidence"], "not_listed")
        generic = self.assess("Account Executive", {}, description="Sell courier services to local businesses. " * 10)
        self.assertEqual(generic["occupation"]["confidence"], "generic_sales")
        low = self.assess("Sales Development Representative", {}, salary=60_000)
        self.assertIn("fit.r_salary_low", [key for key, _, _ in low["reasons"]])


class AddOn(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket, "socket", side_effect=_blocked))
        self.enterContext(patch.object(socket, "create_connection", side_effect=_blocked))
        self.enterContext(patch("urllib.request.urlopen", side_effect=_blocked))
        self.directory = tempfile.TemporaryDirectory(prefix="sponsorship-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = self.root / "sponsors"
        self.data.mkdir()
        (self.data / "accredited-synthetic.txt").write_text(ACCREDITED, encoding="utf-8")
        (self.data / "sanctioned.json").write_text(json.dumps(SANCTIONS), encoding="utf-8")
        (self.data / "asx-listed.csv").write_text(ASX, encoding="utf-8")
        self.rules = self.root / "rules.yaml"
        self.rules.write_text(yaml.safe_dump({"version": 1, "exclude": [
            {"id": "citizenship.exclusive", "any": ["SYNTHETIC_CITIZEN_ONLY"]}]}))
        self.skills = self.root / "skills.yaml"
        self.skills.write_text("skills: []\n")
        self.cfg = {"db_path": str(self.root / "jobs.db"), "queries": ["synthetic"],
                    "seek": {"enabled": True}, "legacy_rule_profile": {"profile": "485"}}
        with closing(db.connect(self.cfg["db_path"])) as conn:
            for number, title, company, body in (
                    ("1", "Sales Development Representative", "Synthetic Cloudworks", SDR_AD),
                    ("2", "Business Analyst", "Fictional Bakery Partners Pty Ltd", "A synthetic role. " * 20),
                    ("3", "Account Manager", "Example Freight", "SYNTHETIC_CITIZEN_ONLY. " * 5)):
                job = sources.blank_job("seek", number)
                job.update(title=title, company=company, description=body, url="https://example.invalid/" + number)
                db.upsert_job(conn, job)
            conn.commit()

    def config(self, enabled: bool) -> dict:
        cfg = dict(self.cfg)
        if enabled:
            cfg["sponsorship"] = {"enabled": True, "data_dir": str(self.data)}
        path = self.root / ("on.yaml" if enabled else "off.yaml")
        path.write_text(yaml.safe_dump(cfg))
        return cfg, path

    def analyze(self, enabled: bool):
        cfg, path = self.config(enabled)
        with patch("sys.stdout", io.StringIO()):
            code = cli.cmd_analyze(argparse.Namespace(config=str(path), rules=str(self.rules), skills=str(self.skills)))
        self.assertEqual(code, 0)
        with closing(db.connect(self.cfg["db_path"])) as conn:
            scores = sorted(tuple(r) for r in conn.execute(
                "SELECT uid, tier, total_score, reasons FROM scores"))
            decisions = sorted(tuple(r) for r in conn.execute(
                "SELECT uid, is_excluded, rule_id FROM decisions"))
        return cfg, scores, decisions

    def test_off_by_default_writes_nothing_and_renders_nothing(self):
        cfg, _scores, _decisions = self.analyze(enabled=False)
        self.assertFalse(sponsorship.results_path(cfg).exists())
        self.assertEqual(sponsorship.load_results(cfg), {})
        self.assertEqual(sponsorship.refresh(cfg), [])
        rows = [{"uid": "seek:1"}]
        sponsorship_panel.attach(rows, cfg)
        self.assertNotIn(sponsorship_panel.ROW_KEY, rows[0])
        self.assertEqual(sponsorship_panel.card_tags(rows[0], "en"), "")
        self.assertEqual(sponsorship_panel.detail_block(rows[0], "en"), "")

    def test_enabled_leaves_scores_and_decisions_unchanged(self):
        _cfg, scores_off, decisions_off = self.analyze(enabled=False)
        cfg, scores_on, decisions_on = self.analyze(enabled=True)
        self.assertEqual(scores_on, scores_off)
        self.assertEqual(decisions_on, decisions_off)
        results = json.loads(sponsorship.results_path(cfg).read_text(encoding="utf-8"))["results"]
        self.assertEqual(results["seek:1"]["acc"], "exact")
        self.assertTrue(results["seek:1"]["fit"]["certain"])
        self.assertEqual(results["seek:2"]["sanction_level"], "confirmed")
        self.assertNotIn("fit", results.get("seek:3", {}))          # excluded jobs are not rated

    def test_panel_shows_tags_and_three_sections(self):
        cfg, _s, _d = self.analyze(enabled=True)
        rows = [{"uid": "seek:1"}, {"uid": "seek:2"}]
        sponsorship_panel.attach(rows, cfg)
        card = sponsorship_panel.card_tags(rows[0], "en")
        self.assertIn("Confirmed sponsor", card)
        self.assertIn('class="aumeter m-high"', card)
        self.assertIn("Sponsor sanction on record", sponsorship_panel.card_tags(rows[1], "en"))
        detail = sponsorship_panel.detail_block(rows[0], "en")
        self.assertEqual(detail.count('class="fit-sec"'), 3)
        # 20 base + 35 accredited + 10 ASX (synthetic list) + 15 likely occupation
        self.assertIn("aria-valuenow=\"80\"", detail)
        self.assertIn("(+35)", detail)
        # the evidence sits in hover popups, one per row
        self.assertEqual(detail.count('role="tooltip"'), 3)

    def test_refresh_downloads_only_stale_files_during_fetch(self):
        cfg, _path = self.config(enabled=True)
        (self.data / "asx-listed.csv").unlink()
        (self.data / "sanctioned.json").unlink()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake(request, timeout=0):
            url = request if isinstance(request, str) else request.full_url
            if url == sponsorship.SANCTIONS_URL:
                return Response(json.dumps(SANCTIONS).encode())
            if url == sponsorship.ASX_URL:
                return Response(ASX.encode())
            if url == sponsorship.ATO_PACKAGE_URL:
                return Response(json.dumps({"result": {"resources": []}}).encode())
            raise AssertionError("unexpected URL " + url)

        with patch("urllib.request.urlopen", side_effect=fake):
            self.assertEqual(sorted(sponsorship.refresh(cfg)), ["asx-listed.csv", "sanctioned.json"])
            self.assertEqual(sponsorship.refresh(cfg), [])           # fresh files are kept


if __name__ == "__main__":
    unittest.main()

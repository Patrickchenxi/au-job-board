"""Offline checks for the optional scam-risk add-on (jobs/authenticity*.py).

All ads, employers and domains are handwritten synthetic data. The scam examples
follow the patterns Scamwatch describes; the "genuine" examples are the kinds of
sentences real ads use innocently (anti-scam notices, paid training, products
that integrate messaging apps). No network: sockets and DNS are patched.
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
from jobs import authenticity, authenticity_panel, cli, db, sources  # noqa: E402

FILLER = " The role suits someone organised and friendly who enjoys working with customers." * 4
TASK_SCAM = ("Work from home! Earn $300 per day from home, no experience needed. Simply rate products on "
             "our app and earn commission per task. Message us on WhatsApp +61 400 000 000 to start." + FILLER)
GENUINE = ("We are a synthetic software company hiring a sales development representative. Paid training "
           "and competitive pay. Our platform sends messages via SMS and WhatsApp for our customers. "
           "We will never ask you to pay a fee or contact you via WhatsApp or Telegram; treat such requests "
           "as fraudulent." + FILLER)


def _blocked(*_args, **_kwargs):
    raise AssertionError("network forbidden")


def keys(text: str) -> set[str]:
    return {sign["key"] for sign in authenticity.scan_signs(text)}


class Signs(unittest.TestCase):
    def test_scamwatch_patterns_are_found(self):
        self.assertEqual(keys(TASK_SCAM), {"task_scam", "messaging_app", "easy_money"})
        self.assertIn("upfront_payment", keys("You will need to purchase a starter kit for $99 before your first shift."))
        self.assertIn("upfront_payment", keys("A refundable fee of $150 secures your place."))
        self.assertIn("crypto_topup", keys("Top up your account with USDT to unlock higher paying tasks."))
        self.assertIn("money_mule", keys("Receive payments on behalf of our company and forward the funds to suppliers."))
        self.assertIn("id_early", keys("Please send your passport and bank details with your application."))
        self.assertIn("no_interview", keys("No interview required, start tomorrow."))

    def test_innocent_wording_is_not_flagged(self):
        self.assertEqual(keys(GENUINE), set())
        self.assertEqual(keys("We build self-custody bitcoin wallets and crypto exchange software."), set())
        self.assertEqual(keys("The company receives its placement fee once a client is placed."), set())
        self.assertEqual(keys("Benefits include paid training and a uniform allowance."), set())

    def test_evidence_is_quoted(self):
        sign = authenticity.scan_signs(TASK_SCAM)[0]
        self.assertIn("rate products", sign["text"])


class Domains(unittest.TestCase):
    def test_company_name_matching(self):
        match = authenticity.domain_matches_company
        self.assertTrue(match("careers.synthetic.com.au", "Synthetic Widgets Pty Ltd"))
        self.assertTrue(match("au.example.com", "Example"))
        self.assertTrue(match("swbn.com.au", "Sample Water Board Northern"))          # initials
        self.assertTrue(match("admin.nsc.vic.edu.au", "Northside Sample College"))    # initials, school suffix
        self.assertFalse(match("cheap-offers.biz", "Synthetic Widgets Pty Ltd"))

    def test_mail_only_subdomain_is_not_missing(self):
        # mail.example.com has no address record, but its parent does
        exists = authenticity._exists("mail.example.com", lambda d: d == "example.com")
        self.assertTrue(exists)
        self.assertFalse(authenticity._exists("nowhere.example", lambda d: False))
        self.assertEqual(authenticity.registrable("admin.ex.vic.edu.au"), "ex.vic.edu.au")
        self.assertEqual(authenticity.contact_domains("Ask L.E.K. about it."), [])

    def test_freemail_mismatch_and_missing_domain(self):
        job = {"title": "Office Assistant", "company": "Synthetic Widgets Pty Ltd",
               "description": "Apply to jobs.synthetic@gmail.com or hr@cheap-offers.biz." + FILLER}
        result = authenticity.assess(job, domains={"cheap-offers.biz": {"resolves": False}},
                                     duplicates=0, employer={})
        found = {key for key, _, _ in result["reasons"]}
        self.assertTrue({"auth.r_freemail", "auth.r_domain_mismatch", "auth.r_domain_missing"} <= found)


class Scoring(unittest.TestCase):
    def test_levels_and_offsets(self):
        scam = authenticity.assess({"title": "Remote Assistant", "company": "", "description": TASK_SCAM},
                                   domains={}, duplicates=5, employer={})
        self.assertEqual(scam["level"], "high")
        self.assertEqual(scam["risk"], 100)
        genuine = authenticity.assess({"title": "SDR", "company": "Synthetic Software", "description": GENUINE},
                                      domains={}, duplicates=0, employer={"accredited": True, "listed": True})
        self.assertEqual(genuine["level"], "low")
        self.assertEqual(genuine["risk"], 0)


class AddOn(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket, "socket", side_effect=_blocked))
        self.enterContext(patch.object(socket, "create_connection", side_effect=_blocked))
        self.enterContext(patch.object(socket, "getaddrinfo", side_effect=_blocked))
        self.directory = tempfile.TemporaryDirectory(prefix="authenticity-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rules = self.root / "rules.yaml"
        self.rules.write_text(yaml.safe_dump({"version": 1, "exclude": []}))
        self.skills = self.root / "skills.yaml"
        self.skills.write_text("skills: []\n")
        self.cfg = {"db_path": str(self.root / "jobs.db"), "queries": ["synthetic"],
                    "seek": {"enabled": True}, "legacy_rule_profile": {"profile": "485"}}
        with closing(db.connect(self.cfg["db_path"])) as conn:
            for number, title, company, body in (
                    ("1", "Remote Assistant", "Private Advertiser", TASK_SCAM),
                    ("2", "Sales Development Representative", "Synthetic Software", GENUINE),
                    ("3", "Office Assistant", "Synthetic Widgets", "Email hr@cheap-offers.biz." + FILLER)):
                job = sources.blank_job("seek", number)
                job.update(title=title, company=company, description=body, url="https://example.invalid/" + number)
                db.upsert_job(conn, job)
            conn.commit()

    def config(self, enabled: bool):
        cfg = dict(self.cfg)
        if enabled:
            cfg["authenticity"] = {"enabled": True, "data_dir": str(self.root / "auth")}
        path = self.root / ("on.yaml" if enabled else "off.yaml")
        path.write_text(yaml.safe_dump(cfg))
        return cfg, path

    def analyze(self, enabled: bool):
        cfg, path = self.config(enabled)
        with patch("sys.stdout", io.StringIO()):
            self.assertEqual(cli.cmd_analyze(argparse.Namespace(
                config=str(path), rules=str(self.rules), skills=str(self.skills))), 0)
        with closing(db.connect(self.cfg["db_path"])) as conn:
            return cfg, (sorted(tuple(r) for r in conn.execute("SELECT uid, tier, total_score, reasons FROM scores")),
                         sorted(tuple(r) for r in conn.execute("SELECT uid, is_excluded, rule_id FROM decisions")))

    def test_off_by_default(self):
        cfg, _ = self.analyze(enabled=False)
        self.assertFalse(authenticity.results_path(cfg).exists())
        with closing(db.connect(self.cfg["db_path"])) as conn:
            self.assertEqual(authenticity.refresh(conn, cfg), 0)
        rows = [{"uid": "seek:1"}]
        authenticity_panel.attach(rows, cfg)
        self.assertEqual(authenticity_panel.card_tags(rows[0], "en"), "")
        self.assertEqual(authenticity_panel.detail_block(rows[0], "en"), "")

    def test_enabled_changes_no_scores_or_decisions(self):
        _cfg, off = self.analyze(enabled=False)
        cfg, on = self.analyze(enabled=True)
        self.assertEqual(on, off)
        results = json.loads(authenticity.results_path(cfg).read_text(encoding="utf-8"))["results"]
        self.assertEqual(results["seek:1"]["level"], "high")
        self.assertEqual(results["seek:2"]["level"], "low")

    def test_panel_badge_only_when_risky_and_detail_links(self):
        cfg, _ = self.analyze(enabled=True)
        rows = [{"uid": "seek:1", "company": "Private Advertiser"}, {"uid": "seek:2", "company": "Synthetic Software"}]
        authenticity_panel.attach(rows, cfg)
        self.assertIn("ar-high", authenticity_panel.card_tags(rows[0], "en"))
        self.assertEqual(authenticity_panel.card_tags(rows[1], "en"), "")
        detail = authenticity_panel.detail_block(rows[0], "zh")
        self.assertIn("abr.business.gov.au", detail)
        self.assertIn("scamwatch.gov.au", detail)
        self.assertIn("rate products", detail)

    def test_domain_check_runs_only_in_fetch_refresh(self):
        cfg, _ = self.config(enabled=True)
        seen = []
        with closing(db.connect(self.cfg["db_path"])) as conn:
            self.assertEqual(authenticity.refresh(conn, cfg, resolver=lambda d: seen.append(d) or False), 1)
            self.assertEqual(authenticity.refresh(conn, cfg, resolver=lambda d: seen.append(d) or False), 0)
        # one domain (plus its www. fallback) looked up once; a fresh cache means no second round
        self.assertEqual(seen, ["cheap-offers.biz", "www.cheap-offers.biz"])
        _cfg, _ = self.analyze(enabled=True)
        results = json.loads(authenticity.results_path(cfg).read_text(encoding="utf-8"))["results"]
        self.assertIn("auth.r_domain_missing", {k for k, _, _ in results["seek:3"]["reasons"]})


if __name__ == "__main__":
    unittest.main()

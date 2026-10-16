"""Synthetic/offline configuration roundtrip, mutation boundary and HTTP tests."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from jobs.config_edit import ConfigEditor, ConfigEditError
from jobs import panel, run_state


class ConfigEditorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="config-editor-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "non-default.yaml"
        self.original = ('# retained header\nqueries: [synthetic] # keyword note\n'
                         'db_path: "' + str(self.root / 'data/jobs.db') + '"\n'
                         'private_unknown:\n  password: "synthetic-secret" # private note\n'
                         'seek:\n  enabled: true\n  pages_per_query: 2 # keep note\n'
                         'legacy_rule_profile:\n  profile: "485"\n')
        self.path.write_text(self.original, encoding="utf-8")
        self.path.chmod(0o640)
        self.config = yaml.safe_load(self.original)
        self.editor = ConfigEditor(self.config, self.path, ROOT / "rules.yaml")

    def save(self, changes, digest=None):
        return self.editor.save({"digest": digest or self.editor.read()["digest"], "changes": changes})

    def error(self, code, action):
        with self.assertRaises(ConfigEditError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def test_public_example_and_roundtrip_yaml_numeric_subclasses(self):
        example = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
        self.path.write_text(example, encoding="utf-8")
        result = self.editor.read()
        self.assertEqual(result["values"]["seek.detail_sleep"], 0.25)
        result = self.save({"seek.detail_sleep": 0})
        self.assertEqual(result["values"]["seek.detail_sleep"], 0)
        result = self.save({"seek.detail_sleep": 0.05})
        self.assertEqual(result["values"]["seek.detail_sleep"], 0.05)
        result = self.save({"seek.pages_per_query": 3, "seek.daterange": 0,
                            "jobspy.indeed.results_wanted": 10})
        self.assertEqual(result["values"]["seek.daterange"], 0)
        self.assertEqual(result, self.editor.read())
        # Explicit formatted integers are ruamel ScalarInt instances as well.
        self.path.write_text("queries: [synthetic]\nseek:\n  pages_per_query: 02\n  daterange: 0\n  detail_sleep: 0\n")
        result = self.editor.read()
        self.assertEqual(result["values"]["seek.pages_per_query"], 2)
        self.assertEqual(result["values"]["seek.detail_sleep"], 0)
        for field in ("seek.detail_sleep", "seek.pages_per_query", "seek.daterange", "jobspy.indeed.results_wanted"):
            self.error("validation_failed", lambda field=field: self.save({field: True}))

    def test_saved_text_has_identical_cli_yaml_semantics(self):
        from jobs.config import load_config
        terms = ["on", "yes", "no", "off", "2026-10-17", "012", "null", "1e2", "1.25"]
        self.path.write_text(self.original + "unknown_bool: yes # keep boolean\nunknown_date: 2026-10-17\nunknown_octal: 012\nunknown_string: 'off'\n")
        before = load_config(self.path)
        changes = {"queries": terms, "seek.locations": terms,
                   "jobspy.indeed.location": "on", "jobspy.linkedin.location": "2026-10-17",
                   "jobspy.indeed.country_indeed": "012"}
        result = self.save(changes)
        actual = load_config(self.path)
        self.assertEqual(actual["queries"], terms)
        self.assertEqual(actual["seek"]["locations"], terms)
        self.assertEqual(actual["jobspy"]["indeed"]["location"], "on")
        self.assertEqual(actual["jobspy"]["linkedin"]["location"], "2026-10-17")
        self.assertEqual(actual["jobspy"]["indeed"]["country_indeed"], "012")
        for path, value in changes.items():
            self.assertEqual(result["values"][path], value)
        for key in ("unknown_bool", "unknown_date", "unknown_octal", "unknown_string"):
            self.assertEqual(actual[key], before[key])
            self.assertIs(type(actual[key]), type(before[key]))
        self.assertIn("# keep boolean", self.path.read_text())
        self.assertFalse(self.path.read_text().startswith("%YAML"))
        scalar_paths = ("jobspy.indeed.location", "jobspy.linkedin.location", "jobspy.indeed.country_indeed")
        for term in terms:
            result = self.save({path: term for path in scalar_paths})
            actual = load_config(self.path)
            for path in scalar_paths:
                _, source, field = path.split(".")
                self.assertEqual(actual["jobspy"][source][field], term)
                self.assertIs(type(actual["jobspy"][source][field]), str)
                self.assertEqual(result["values"][path], term)

    def test_external_yaml_uses_same_semantics_as_cli(self):
        self.path.write_text("queries: [on]\n")
        self.error("validation_failed", self.editor.read)
        self.path.write_text("queries: [synthetic]\njobspy: {indeed: {location: 2026-10-17}}\n")
        self.error("validation_failed", self.editor.read)
        self.path.write_text("queries: [synthetic]\nseek: {enabled: yes}\n")
        result = self.editor.read()
        self.assertIs(result["values"]["seek.enabled"], True)

    def test_actual_file_and_public_defaults_only(self):
        result = self.editor.read()
        self.assertEqual(result["values"]["seek.locations"], ["All Australia"])
        self.assertFalse(result["explicit"]["seek.locations"])
        self.assertTrue(result["explicit"]["queries"])
        serialized = json.dumps(result)
        self.assertNotIn("synthetic-secret", serialized)
        self.assertNotIn(str(self.path), serialized)
        self.assertNotIn("db_path", serialized)

    def test_roundtrip_unknown_comments_mode_and_readback(self):
        result = self.save({"queries": ["synthetic analyst"], "seek.pages_per_query": 4})
        text = self.path.read_text()
        self.assertIn("# retained header", text)
        self.assertIn("# keyword note", text)
        self.assertIn("# keep note", text)
        self.assertIn('password: "synthetic-secret" # private note', text)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual(result, self.editor.read())
        self.assertEqual(yaml.safe_load(text)["queries"], ["synthetic analyst"])
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_external_change_and_second_tab_conflict(self):
        initial = self.editor.read()
        self.save({"seek.pages_per_query": 3})
        newer = self.path.read_bytes()
        self.error("conflict", lambda: self.save({"seek.pages_per_query": 5}, initial["digest"]))
        self.assertEqual(self.path.read_bytes(), newer)
        current = self.editor.read()
        self.path.write_text(self.path.read_text()+"# external change\n")
        self.error("conflict", lambda: self.save({"seek.pages_per_query": 5}, current["digest"]))

    def test_invalid_fields_and_types_preserve_file(self):
        bad = ({"db_path": "/tmp/other"}, {"seek.enabled": "true"},
               {"seek.pages_per_query": True}, {"seek.pages_per_query": 0},
               {"seek.pages_per_query": 101}, {"queries": []},
               {"queries": ["x\nheader"]}, {"seek.daterange": -1},
               {"seek.detail_sleep": float("nan")}, {"seek.detail_sleep": 61},
               {"legacy_rule_profile.profile": "unknown"},
               {"legacy_rule_profile.exclude.unknown": False})
        for changes in bad:
            before = self.path.read_bytes()
            with self.subTest(changes=changes):
                with self.assertRaises(ConfigEditError):
                    self.save(changes)
                self.assertEqual(self.path.read_bytes(), before)

    def test_disabled_all_sources_can_be_saved(self):
        result = self.save({"seek.enabled": False, "jobspy.indeed.enabled": False,
                            "jobspy.linkedin.enabled": False})
        self.assertFalse(result["values"]["seek.enabled"])
        self.assertFalse(result["values"]["jobspy.indeed.enabled"])
        self.assertFalse(result["values"]["jobspy.linkedin.enabled"])

    def test_profile_overrides_and_reset_follow_preset(self):
        result = self.save({"legacy_rule_profile.profile": "citizen",
                            "legacy_rule_profile.exclude.citizenship.exclusive": True})
        document = yaml.safe_load(self.path.read_text())
        self.assertEqual(document["legacy_rule_profile"]["exclude"], {"citizenship.exclusive": True})
        self.assertTrue(result["effective_rules"]["exclude"]["citizenship.exclusive"])
        result = self.save({"legacy_rule_profile.exclude.citizenship.exclusive": None})
        self.assertFalse(result["effective_rules"]["exclude"]["citizenship.exclusive"])
        self.assertIsNone(result["values"]["legacy_rule_profile.exclude.citizenship.exclusive"])

    def test_busy_lock_blocks_save(self):
        handle = run_state.acquire_lock(self.config)
        try:
            self.error("run_busy", lambda: self.save({"seek.pages_per_query": 3}))
            self.assertEqual(self.path.read_text(), self.original)
        finally:
            handle.close()
        self.save({"seek.pages_per_query": 3})

    def test_atomic_replace_failure_preserves_original_and_cleans_temp(self):
        with patch("jobs.config_edit.os.replace", side_effect=PermissionError):
            self.error("write_failed", lambda: self.save({"seek.pages_per_query": 3}))
        self.assertEqual(self.path.read_text(), self.original)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_unsafe_duplicate_alias_merge_and_invalid_yaml_rejected(self):
        documents = ["queries: [x]\nqueries: [y]\n", "queries: !!python/object/apply:os.system [false]\n",
                     "queries: &q [synthetic]\nprivate: *q\n", "queries: [synthetic]\nprivate: {<<: {a: b}}\n",
                     "queries: [unterminated\n", "- list-root\n", "", "queries: [synthetic]\nseek: {enabled: true, enabled: false}\n"]
        for document in documents:
            with self.subTest(document=document):
                self.path.write_text(document)
                self.error("config_invalid", self.editor.read)
                self.assertEqual(self.path.read_text(), document)

    def test_external_edit_during_validation_is_not_overwritten(self):
        original_replace = self.editor._replace
        def concurrent(encoded, digest):
            self.path.write_text(self.path.read_text()+"# concurrent\n")
            original_replace(encoded, digest)
        with patch.object(self.editor, "_replace", side_effect=concurrent):
            self.error("conflict", lambda: self.save({"seek.pages_per_query": 3}))
        self.assertIn("# concurrent", self.path.read_text())
        self.assertIn("pages_per_query: 2", self.path.read_text())

    def test_saved_file_drives_next_update_without_restarting_panel(self):
        from jobs.panel_update import UpdateManager
        manager = UpdateManager(self.config, self.path, rules_path=ROOT / "rules.yaml")
        self.save({"queries": ["changed synthetic term"],
                   "seek.pages_per_query": 7, "legacy_rule_profile.profile": "whv"})
        fresh, preview = manager._fresh()
        self.assertEqual(fresh["legacy_rule_profile"]["profile"], "whv")
        self.assertEqual(preview["queries"], ["changed synthetic term"])
        self.assertEqual(preview["sources"][0]["pages_per_query"], 7)
        self.save({"seek.enabled": False, "jobspy.indeed.enabled": False,
                   "jobspy.linkedin.enabled": False})
        fresh, preview = manager._fresh()
        self.assertIsNone(fresh)
        self.assertEqual(preview["error"], "no_sources")

    def test_demo_refuses_reads_and_writes(self):
        editor = ConfigEditor({**self.config, "demo": {}}, self.path, ROOT/"rules.yaml")
        self.error("demo_disabled", editor.read)


class LocalRequestTest(unittest.TestCase):
    def handler(self, host="127.0.0.1:8090", origin="http://127.0.0.1:8090", payload=None):
        import email.message
        handler = object.__new__(panel.Handler)
        handler.headers = email.message.Message()
        body = json.dumps(payload if payload is not None else {}).encode()
        for key, value in {"Host": host, "Origin": origin, "Content-Type": "application/json", "Content-Length": str(len(body))}.items():
            handler.headers[key] = value
        handler.rfile = io.BytesIO(body)
        handler.server = type("Server", (), {"server_address": ("127.0.0.1", 8090)})()
        handler._json = lambda obj, status, started: setattr(handler, "response", (obj, status))
        return handler

    def test_local_request_accepted_and_foreign_origin_rejected(self):
        handler = self.handler(payload={"digest": "a"*64, "changes": {}})
        self.assertEqual(handler._local_json(0,65536)["digest"], "a"*64)
        for args in ({"host": "evil.test:8090"}, {"origin": "https://evil.test"}, {"host": "127.0.0.1:1"}):
            with self.subTest(args=args):
                handler = self.handler(**args)
                self.assertIsNone(handler._local_json(0))
                self.assertEqual(handler.response[1], 403)

    def test_container_wildcard_keeps_local_host_origin_boundary(self):
        with patch.dict(os.environ, {"JOBS_CONTAINER": "1"}):
            handler = self.handler()
            handler.server.server_address = ("0.0.0.0",8090)
            self.assertEqual(handler._local_json(0), {})
            handler = self.handler(host="evil.test:8090",origin="http://evil.test:8090")
            handler.server.server_address = ("0.0.0.0",8090)
            self.assertIsNone(handler._local_json(0))
            self.assertEqual(handler.response[1],403)


if __name__ == "__main__":
    unittest.main()

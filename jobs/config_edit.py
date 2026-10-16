"""Bounded, comment-preserving edits to the panel's actual configuration file.

Only public execution fields cross the HTTP boundary. Unknown configuration is
retained on disk. YAML aliases/merge keys, duplicate keys and non-safe tags are
rejected instead of guessing which value an editor meant to change.
"""
from __future__ import annotations

import copy
import hashlib
import io
import math
import os
from pathlib import Path
import stat
import tempfile

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from yaml.constructor import ConstructorError

from .config import ROOT, load_rules
from .legacy_rule_profiles import PROFILES, resolve_rule_profile

MAX_BYTES = 1024 * 1024
DEFAULTS = {
    "queries": [],
    "seek.enabled": True, "seek.locations": ["All Australia"],
    "seek.pages_per_query": 2, "seek.daterange": None, "seek.detail_sleep": 0.25,
    "jobspy.indeed.enabled": True, "jobspy.indeed.location": "Melbourne VIC",
    "jobspy.indeed.country_indeed": "australia", "jobspy.indeed.results_wanted": 40,
    "jobspy.linkedin.enabled": True, "jobspy.linkedin.location": "Melbourne VIC",
    "jobspy.linkedin.results_wanted": 40, "jobspy.linkedin.fetch_description": True,
    "legacy_rule_profile.profile": "custom",
}


class ConfigEditError(ValueError):
    def __init__(self, code, field=None):
        self.code, self.field = code, field
        super().__init__(code)


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise ConstructorError(None, None, "merge key rejected", key_node.start_mark)
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in result:
                raise ConstructorError(None, None, "duplicate key", key_node.start_mark)
            result[key] = loader.construct_object(value_node, deep=deep)
        except TypeError as exc:
            raise ConstructorError(None, None, "complex key", key_node.start_mark) from exc
    return result


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _document(raw):
    try:
        text = raw.decode("utf-8")
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(text)):
            raise ConfigEditError("config_invalid")
        plain = yaml.load(text, Loader=_StrictLoader)
        if not isinstance(plain, dict):
            raise ConfigEditError("config_invalid")
        parser = YAML(typ="rt")
        parser.preserve_quotes = True
        parser.allow_duplicate_keys = False
        document = parser.load(text)
        return parser, document, plain
    except (ValueError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigEditError("config_invalid") from exc
    except Exception as exc:
        # ruamel parser/constructor errors are deliberately not exposed verbatim.
        if exc.__class__.__module__.startswith("ruamel.yaml"):
            raise ConfigEditError("config_invalid") from exc
        raise


def _get(document, path, default):
    current = document
    for part in path.split("."):
        if not isinstance(current, dict):
            raise ConfigEditError("config_invalid", path)
        if part not in current:
            return copy.deepcopy(default), False
        current = current[part]
    return copy.deepcopy(current), True


def _set(document, path, value):
    parts = path.split(".", 2) if path.startswith("legacy_rule_profile.") else path.split(".")
    current = document
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        if not isinstance(current[part], dict):
            raise ConfigEditError("config_invalid", path)
        current = current[part]
    current[parts[-1]] = value


def _quoted_strings(value):
    """Keep JSON strings as strings for the CLI's YAML 1.1 loader as well."""
    if isinstance(value, str):
        return DoubleQuotedScalarString(value)
    if isinstance(value, list):
        return [_quoted_strings(item) for item in value]
    return value


def _apply_changes(document, changes, *, quote_strings=False):
    for path, value in changes.items():
        if path.startswith("legacy_rule_profile.") and path != "legacy_rule_profile.profile":
            if "legacy_rule_profile" not in document:
                _set(document, "legacy_rule_profile.profile", "custom")
            if value is None:
                _, namespace, rid = path.split(".", 2)
                document["legacy_rule_profile"].get(namespace, {}).pop(rid, None)
                continue
        _set(document, path, _quoted_strings(value) if quote_strings else value)


def _same_values(left, right):
    """Check complete CLI semantics, including unknown fields, before writing."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return len(left) == len(right) and all(
            _same_values(a, b) and _same_values(left[a], right[b])
            for a, b in zip(left, right))
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_values(a, b) for a, b in zip(left, right))
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return left == right


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1000 and not any(ord(c) < 32 for c in value)


def _validate(path, value, rule_ids):
    valid = False
    if path == "queries" or path == "seek.locations":
        valid = isinstance(value, list) and 0 < len(value) <= 100 and all(_text(v) for v in value)
    elif path.endswith(".enabled") or path.endswith(".fetch_description"):
        valid = type(value) is bool
    elif path.endswith(".pages_per_query"):
        valid = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 100
    elif path.endswith(".results_wanted"):
        valid = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000
    elif path == "seek.daterange":
        valid = value is None or (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 3650)
    elif path == "seek.detail_sleep":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 60
    elif path == "legacy_rule_profile.profile":
        valid = isinstance(value, str) and value in PROFILES
    elif path.startswith("legacy_rule_profile."):
        _, namespace, rid = path.split(".", 2)
        valid = namespace in rule_ids and rid in rule_ids[namespace] and (value is None or type(value) is bool)
    elif path in DEFAULTS:
        valid = _text(value)
    if not valid:
        raise ConfigEditError("validation_failed", path if path in DEFAULTS or path.startswith("legacy_rule_profile.") else None)


class ConfigEditor:
    def __init__(self, config, config_path=None, rules_path=None):
        self.config = copy.deepcopy(config)
        self.path = Path(config_path).resolve() if config_path is not None else ROOT / "config.yaml"
        self.rules_path = rules_path
        self.demo = "demo" in config

    def _read(self):
        if self.demo:
            raise ConfigEditError("demo_disabled")
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ConfigEditError("config_invalid")
            return raw, *_document(raw)
        except OSError as exc:
            raise ConfigEditError("config_unavailable") from exc

    def _view(self, raw, document):
        try:
            rules = load_rules(self.rules_path)
            resolution = resolve_rule_profile(document, rules)
        except (ValueError, TypeError, OSError, yaml.YAMLError) as exc:
            raise ConfigEditError("config_invalid") from exc
        values, explicit = {}, {}
        for path, default in DEFAULTS.items():
            value, present = _get(document, path, default)
            if path == "legacy_rule_profile.profile":
                value = resolution["profile"] or "custom"
            _validate(path, value, resolution)
            values[path], explicit[path] = value, present
        rule_ids = {}
        for namespace in ("exclude", "overrides"):
            rule_ids[namespace] = list(resolution[namespace])
            for rid in rule_ids[namespace]:
                path = "legacy_rule_profile." + namespace + "." + rid
                value = resolution["explicit_" + namespace].get(rid)
                values[path] = value
                explicit[path] = rid in resolution["explicit_" + namespace]
        return {"ok": True, "digest": hashlib.sha256(raw).hexdigest(),
                "values": values, "explicit": explicit, "profiles": list(PROFILES),
                "rule_ids": rule_ids, "effective_rules": {key: resolution[key] for key in rule_ids}}

    def read(self):
        raw, _, _, plain = self._read()
        return self._view(raw, plain)

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"digest", "changes"}:
            raise ConfigEditError("invalid_request")
        digest, changes = payload["digest"], payload["changes"]
        if not isinstance(digest, str) or len(digest) != 64 or not isinstance(changes, dict) or len(changes) > 200:
            raise ConfigEditError("invalid_request")
        from .run_state import acquire_lock
        try:
            handle = acquire_lock(self.config)
        except OSError as exc:
            raise ConfigEditError("config_unavailable") from exc
        if handle is None:
            raise ConfigEditError("run_busy")
        try:
            raw, parser, document, plain = self._read()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ConfigEditError("conflict")
            view = self._view(raw, plain)
            for path, value in changes.items():
                if path not in view["values"]:
                    raise ConfigEditError("invalid_request")
                _validate(path, value, view["rule_ids"])
            if not changes:
                return view
            expected = copy.deepcopy(plain)
            _apply_changes(document, changes, quote_strings=True)
            _apply_changes(expected, changes)
            stream = io.StringIO()
            parser.dump(document, stream)
            encoded = stream.getvalue().encode("utf-8")
            # Validate the complete candidate before any filesystem mutation.
            candidate = _document(encoded)[2]
            self._view(encoded, candidate)
            if not _same_values(expected, candidate):
                raise ConfigEditError("config_invalid")
            self._replace(encoded, digest)
            return self.read()
        finally:
            handle.close()

    def _replace(self, encoded, digest):
        temporary = None
        try:
            mode = stat.S_IMODE(self.path.stat().st_mode)
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix="." + self.path.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                os.fchmod(handle.fileno(), mode)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            # Catch external edits made during validation as well as stale tabs.
            if hashlib.sha256(self.path.read_bytes()).hexdigest() != digest:
                raise ConfigEditError("conflict")
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise ConfigEditError("write_failed") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

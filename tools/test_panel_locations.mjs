#!/usr/bin/env node
/* Synthetic group-level location search and save behavior; real panel.js. */
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../jobs/panel_assets/panel.js", import.meta.url), "utf8");
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

class El {
  constructor(tag = "div", dataset = {}) {
    this.tagName = tag.toUpperCase();
    this.dataset = dataset;
    this.value = "";
    this.defaultValue = "";
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.q = {};
    this.classes = new Set();
    this.attrs = {};
    this._html = "";
    this.classList = {
      contains: (key) => this.classes.has(key),
      add: (...keys) => keys.forEach((key) => this.classes.add(key)),
      remove: (...keys) => keys.forEach((key) => this.classes.delete(key)),
      toggle: (key, value) => {
        value = value ?? !this.classes.has(key);
        value ? this.classes.add(key) : this.classes.delete(key);
        return value;
      },
    };
  }
  set className(value) { this.classes = new Set(value.split(/\s+/)); }
  get className() { return [...this.classes].join(" "); }
  set innerHTML(value) { this._html = value; if (this.render) this.render(value); }
  get innerHTML() { return this._html; }
  querySelectorAll(selector) { return this.q[selector] || []; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest() { return null; }
  setAttribute(key, value) { this.attrs[key] = value; }
  removeAttribute(key) { delete this.attrs[key]; }
  focus() { this.focused = true; }
  addEventListener() {}
  removeEventListener() {}
  appendChild() {}
}

function setup() {
  const ids = new Map();
  const registry = {};
  const body = new El("body");
  const document = {
    body,
    activeElement: body,
    hidden: false,
    documentElement: { lang: "en" },
    getElementById: (key) => ids.get(key) || null,
    querySelectorAll: (selector) => registry[selector] || [],
    querySelector: (selector) => (registry[selector] || [])[0] || null,
    addEventListener() {},
    createElement: (tag) => new El(tag),
  };
  const sandbox = {
    document,
    console,
    URL,
    URLSearchParams,
    Map,
    Set,
    WeakMap,
    Promise,
    Date,
    JSON,
    Number,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: (callback) => callback(),
    addEventListener() {},
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    localStorage: { getItem() { return null; }, setItem() {} },
    sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    location: {
      href: "http://localhost/?view=all&geo=Carlton",
      pathname: "/",
      search: "?view=all&geo=Carlton",
      hash: "",
    },
    __LABELS__: { A: { action: "applied", note: "Synthetic；" } },
    __VIEW__: "all",
    confirm: () => false,
  };
  sandbox.window = sandbox;
  sandbox.history = {
    replaceState(_a, _b, url) {
      const next = new URL(url, sandbox.location.href);
      Object.assign(sandbox.location, {
        href: next.href,
        hash: next.hash,
        search: next.search,
      });
    },
  };
  const pane = new El();
  ids.set("detail", pane);
  ids.set("toast", new El());
  const scope = new El("div", {
    uid: "A",
    scopeLabel: JSON.stringify({ action: "applied", note: "Synthetic；" }),
  });
  scope.attrs["data-label-scope"] = "";
  registry['#detail [data-label-scope]'] = [scope];
  registry['#detail [data-uid="A"]'] = [scope];
  pane.render = (html) => {
    if (html.startsWith("DETAIL:")) {
      const uid = html.slice(7);
      scope.dataset.uid = uid;
      registry['#detail [data-uid="' + uid + '"]'] = [scope];
    }
  };

  const calls = [];
  let route = async (url, payload) => ({
    ok: true,
    json: async () => url.startsWith("/api/job")
      ? { html: "DETAIL:" + new URL(url, "http://localhost").searchParams.get("uid") }
      : { ok: true, field: payload?.field, value: payload?.value, label: payload?.value === null ? {} : { [payload?.field]: payload?.value } },
  });
  sandbox.fetch = async (url, options) => {
    const payload = options?.body ? JSON.parse(options.body) : null;
    calls.push({ url: String(url), payload });
    return route(String(url), payload);
  };
  vm.createContext(sandbox);
  vm.runInContext(source + `\n;globalThis.api={
    openJob,setNote,noteAdopt,setLabel,allowDetailNavigation,refreshDot,scopeLabel,
    detailHash,readDetailHash,viewParams,geoTyping,geoKeys,applyGeo,
    filterDraftBegin,filterDraftDiscard,filterDraftCount,navKeyIgnored,
    current(uid){OPEN_UID=uid;}, pending(){return LABEL_WRITES.size;}
  };`, sandbox);
  return {
    api: sandbox.api,
    sandbox,
    ids,
    registry,
    pane,
    calls,
    setRoute(callback) { route = callback; },
  };
}

let passed = 0;
async function test(name, callback) {
  await callback();
  passed += 1;
  console.log("[PASS]", name);
}

await test("detail hashes are uid-only and old scoped hashes remain readable", async () => {
  const t = setup();
  await t.api.openJob("A");
  const request = new URL(t.calls[0].url, "http://localhost");
  assert.equal(request.searchParams.has("location_id"), false);
  assert.equal(t.sandbox.location.hash, "#A");
  t.sandbox.location.hash = "#seek%3Aold&location_id=legacy";
  assert.deepEqual(JSON.parse(JSON.stringify(t.api.readDetailHash())), { uid: "seek:old" });
  assert.equal(t.api.detailHash("seek:A & B"), "#seek%3AA%20%26%20B");
});

await test("notes are group-scoped, serialized and keep the newest unsaved draft", async () => {
  const t = setup();
  const input = new El("input", { uid: "A" });
  t.api.noteAdopt(input, "");
  const first = deferred();
  let count = 0;
  t.setRoute(async (_url, payload) => {
    if (++count === 1) return first.promise;
    return {
      ok: true,
      json: async () => ({ value: payload.value + "；", label: { note: payload.value + "；" } }),
    };
  });
  input.value = "first";
  const one = t.api.setNote(input);
  input.value = "second";
  const two = t.api.setNote(input);
  input.value = "unsaved third";
  first.resolve({
    ok: true,
    json: async () => ({ value: "first；", label: { note: "first；" } }),
  });
  await Promise.all([one, two]);
  assert.deepEqual(t.calls.map((call) => call.payload.location_id), [undefined, undefined]);
  assert.equal(input.value, "unsaved third");
  assert.equal(t.api.scopeLabel("A").note, "second；");
});

await test("late group label response updates every matching card", async () => {
  const t = setup();
  const button = new El("button", { uid: "A", field: "action", value: "saved" });
  const dots = [new El("span"), new El("span")];
  dots.forEach((dot) => { dot.textContent = "unchanged"; });
  t.registry['.prog[data-prog-uid="A"]'] = dots;
  t.registry['[data-uid="A"][data-field]'] = [button];
  const reply = deferred();
  t.setRoute(() => reply.promise);
  const saving = t.api.setLabel("A", "action", "saved", button);
  assert.equal(button.disabled, true);
  reply.resolve({
    ok: true,
    json: async () => ({ value: "saved", label: { action: "saved" } }),
  });
  await saving;
  assert.equal(t.calls[0].payload.location_id, undefined);
  assert.deepEqual(dots.map((dot) => dot.textContent), [
    "value.action.saved",
    "value.action.saved",
  ]);
  assert.equal(button.disabled, false);
});

await test("failed group save keeps the navigation gate open for retry", async () => {
  const t = setup();
  const button = new El("button", { uid: "A", field: "action", value: "saved" });
  t.registry['[data-uid="A"][data-field]'] = [button];
  t.setRoute(async () => ({ ok: false, text: async () => '{"error":"write_failed"}' }));
  await t.api.setLabel("A", "action", "saved", button);
  const leave = { prevented: false, preventDefault() { this.prevented = true; } };
  await t.api.allowDetailNavigation();
  assert.equal(button.disabled, false);
  assert.equal(t.api.pending(), 0);
});

await test("location search applies explicitly, supports IME and discards mobile drafts", async () => {
  const t = setup();
  const geo = new El("input", { fkey: "geo" });
  geo.value = geo.defaultValue = "VIC";
  t.registry['[data-fkey="geo"]'] = [geo];
  t.registry['[data-fkey]'] = [geo];
  geo.value = "3053";
  t.api.geoTyping();
  assert.equal(t.api.viewParams().get("geo"), "VIC");
  let prevented = 0;
  t.api.geoKeys({ key: "Enter", target: geo, preventDefault() { prevented += 1; } });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(prevented, 1);
  assert.equal(t.api.viewParams().get("geo"), "3053");
  assert.equal(t.api.viewParams().has("mode"), false);
  const more = new El();
  t.registry["#more-panel"] = [more];
  t.ids.set("more-panel", more);
  t.sandbox.document.body.classes.add("portrait");
  t.api.filterDraftBegin();
  geo.value = "Carlton";
  t.api.geoTyping();
  assert.equal(t.api.filterDraftCount(), 1);
  t.api.filterDraftDiscard();
  assert.equal(geo.value, "3053");
});

await test("location input owns navigation keys; recommendation omits its control", () => {
  const t = setup();
  assert.equal(t.api.navKeyIgnored({ target: new El("input") }), true);
  assert.equal(t.api.navKeyIgnored({ target: new El("select") }), true);
});

console.log(`${passed} group-location behavior scenarios passed`);

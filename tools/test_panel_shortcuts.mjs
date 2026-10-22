#!/usr/bin/env node
/* v1.3 #16 详情上一条 / 下一条快捷键方案的合成 JS 行为检查
（Node 标准库 + 最小 DOM stub，无第三方依赖；执行 panel.js 里的真实函数）。

覆盖：
  - 没有偏好 = Default（← / →）；Vim（K / J）；Gamer（A / D）；只有当前方案的键生效，
    其它方案的键不拦截（不 preventDefault）
  - cookie 现读：设置页改了方案，已打开的面板立即只认新键；未知值回到 Default
  - setKeys 写 cookie（Default 删除 cookie）并同步设置页选项的选中态
  - 每种方案都保留：修饰键 / 自动重复 / IME / 已处理 过滤，输入框 / textarea / select /
    contenteditable、地点控件、自带方向键语义的控件（分栏拖条、dialog 等）、抽屉、
    筛选面板、标注抽屉、更新确认、Display 弹出层、复制手动框 打开时不导航
  - 方向键配 Shift（扩选）不导航；正文已有非空文字选区时方向键留给浏览器，字母键照常
  - 已打开页面在别处改了方案后，按钮提示（含竖屏底栏）随当前方案重写
  - 列表首尾提示、不在本页列表里的岗位提示、保存中等待且重复按键不排队

用法：
    node tools/test_panel_shortcuts.mjs
*/

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PANEL_JS = process.env.PANEL_JS_PATH
  ? path.resolve(process.env.PANEL_JS_PATH)
  : path.join(ROOT, "jobs", "panel_assets", "panel.js");

const failures = [];
process.exitCode = 4;
process.on("beforeExit", () => { console.log("\n未跑完：有异步步骤一直没有完成（视为失败）"); process.exit(4); });
function check(label, ok, detail = "") {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? "  " + detail : ""}`);
  if (!ok) failures.push(label);
}
function eq(label, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  check(label, ok, ok ? "" : `got=${JSON.stringify(got)} want=${JSON.stringify(want)}`);
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const settle = async () => { await tick(); await tick(); };

class ClassList {
  constructor() { this.set = new Set(); }
  add(...n) { n.forEach((x) => this.set.add(x)); }
  remove(...n) { n.forEach((x) => this.set.delete(x)); }
  contains(n) { return this.set.has(n); }
  toggle(n, force) { const on = force === undefined ? !this.set.has(n) : !!force; on ? this.set.add(n) : this.set.delete(n); return on; }
}
let ACTIVE = null;
class El {
  constructor(tag = "div", props = {}) {
    Object.assign(this, { tagName: tag.toUpperCase(), style: {}, classList: new ClassList(), dataset: {}, attrs: {},
      q: {}, closestMap: {}, hidden: false, disabled: false, textContent: "", _html: "", listeners: {} });
    Object.assign(this, props);
  }
  set className(v) { this.classList = new ClassList(); String(v).split(/\s+/).filter(Boolean).forEach((n) => this.classList.add(n)); }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); }
  querySelector(s) { return (this.q[s] || [])[0] || null; }
  querySelectorAll(s) { return this.q[s] || []; }
  closest(s) { for (const part of s.split(",")) { const hit = this.closestMap[part.trim()]; if (hit) return hit; } return null; }
  contains(el) { return el === this; }
  focus() { if (ACTIVE) ACTIVE.activeElement = this; }
  blur() { if (ACTIVE && ACTIVE.activeElement === this) ACTIVE.activeElement = ACTIVE.body; }
  scrollIntoView() {}
  getBoundingClientRect() { return { left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }; }
}

function loadPanel({ cookie = "", cards = ["A", "B", "C", "D"] } = {}) {
  const ids = new Map(), reg = {}, docListeners = new Map();
  const body = new El("body");
  const document = {
    body, activeElement: body, hidden: false, cookie,
    documentElement: { style: { setProperty() {} }, dataset: {}, lang: "en", classList: new ClassList() },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (s) => (reg[s] || [])[0] || null,
    querySelectorAll: (s) => reg[s] || [],
    createElement: (tag) => new El(tag),
    addEventListener(t, fn) { if (!docListeners.has(t)) docListeners.set(t, []); docListeners.get(t).push(fn); },
    removeEventListener() {},
    selectionText: "",   // 页面文字选区（测试直接设置）；空 = 只有光标
    getSelection() {
      const text = document.selectionText;
      return { rangeCount: 1, isCollapsed: !text, type: text ? "Range" : "Caret", toString: () => text };
    },
  };
  ACTIVE = document;
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, Math, JSON, String, Number,
    Object, Array, RegExp, Error, Map, Set, WeakMap, URLSearchParams, URL, Node: El, document,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    history: { replaceState(_s, _t, url) { const n = new URL(url, sandbox.location.href); Object.assign(sandbox.location, { href: n.href, hash: n.hash, search: n.search }); } },
    location: { href: "http://localhost/?view=all#A", pathname: "/", search: "?view=all", hash: "#A", reload() {} },
    matchMedia: (q) => ({ matches: String(q).includes("reduce"), addEventListener() {}, removeEventListener() {} }),
    innerWidth: 1280, innerHeight: 800, addEventListener() {}, removeEventListener() {}, confirm: () => false,
    __I18N__: {}, __LABELS__: {}, __NOTE_TAGS__: [], __NOTE_TAG_LABELS__: {}, __SKILLS__: [], __SKILL_OWNERS__: [],
    __VIEW__: "all", __STALE_AFTER_DAYS__: 2, __RESULT_GENERATION__: "generation-1",
  };
  sandbox.window = sandbox;
  const cardEls = cards.map((uid) => { const c = new El("div"); c.className = "card"; c.dataset.uid = uid; return c; });
  reg[".list .card"] = cardEls; reg[".card"] = cardEls;
  const pane = new El("div"); pane.id = "detail";
  // 服务端按页面载入时的方案渲染的按钮（Default 提示）
  const hint = (step, glyph, aria, name) => {
    const b = new El("button"); b.dataset.step = step; b.attrs = { "aria-keyshortcuts": aria, "aria-label": name };
    b.title = `${name} (${glyph})`; const kbd = new El("kbd", { textContent: glyph }); b.q.kbd = [kbd]; b.kbd = kbd; return b;
  };
  const prev = hint("-1", "←", "ArrowLeft", "Previous"), next = hint("1", "→", "ArrowRight", "Next");
  const barPrev = hint("-1", "←", "ArrowLeft", "Previous"), barNext = hint("1", "→", "ArrowRight", "Next");
  pane.q[".stepbtn"] = [prev, next, barPrev, barNext]; pane.q[".d-pos"] = [new El("span")];
  reg["#detail .stepbtn"] = [prev, next, barPrev, barNext];
  ids.set("detail", pane); ids.set("toast", new El("div"));
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(PANEL_JS, "utf8") + `
;globalThis.__T__ = { openJob, setKeys, keyProfile,
  uid(){return OPEN_UID;}, addPendingNote(p){NOTE_REQUESTS.add(p);p.finally(()=>NOTE_REQUESTS.delete(p));} };`,
  sandbox, { filename: "panel.js" });
  const calls = [];
  sandbox.fetch = async (url) => {
    calls.push(String(url));
    if (String(url).startsWith("/api/job")) return { ok: true, json: async () => ({ html: "<detail>" }) };
    throw new Error("unexpected " + url);
  };
  const t = {
    api: sandbox.__T__, sandbox, document, ids, reg, pane, calls, steps: [prev, next, barPrev, barNext],
    docEvent: (type) => (docListeners.get(type) || []).forEach((fn) => fn({ type })),
    jobCalls: () => calls.filter((u) => u.startsWith("/api/job")).map((u) => decodeURIComponent(u.split("uid=")[1].split("&")[0])),
    toast: () => ids.get("toast").textContent,
    /* 返回是否被拦截（preventDefault） */
    key(ev) {
      let prevented = false;
      const e = { target: body, preventDefault() { prevented = true; }, ...ev };
      (docListeners.get("keydown") || []).forEach((fn) => fn(e));
      return prevented;
    },
  };
  return t;
}

const PROFILES = {
  default: { cookie: "", prev: "ArrowLeft", next: "ArrowRight" },
  vim: { cookie: "jobs_keys=vim", prev: "k", next: "j" },
  gamer: { cookie: "jobs_keys=gamer", prev: "a", next: "d" },
};
const ALL_KEYS = ["ArrowLeft", "ArrowRight", "j", "k", "a", "d"];

async function testProfiles() {
  for (const [name, p] of Object.entries(PROFILES)) {
    console.log(`\n-- ${name}：只认 ${p.prev} / ${p.next} --`);
    const t = loadPanel({ cookie: p.cookie });
    eq(name + "：解析到方案", t.api.keyProfile(), name);
    await t.api.openJob("A");
    for (const key of ALL_KEYS.filter((k) => k !== p.prev && k !== p.next)) {
      const prevented = t.key({ key }); await settle();
      eq(`${name}：其它方案的键 ${key} 不导航也不拦截`, [t.api.uid(), prevented], ["A", false]);
    }
    eq(name + "：下一条", [t.key({ key: p.next }), (await settle(), t.api.uid())], [true, "B"]);
    const upper = p.next.length === 1 ? p.next.toUpperCase() : p.next;
    t.key({ key: upper, shiftKey: p.next.length === 1 }); await settle();
    eq(name + "：大写 / Shift 字母同样下一条（与原 J/K 行为一致）", t.api.uid(), p.next.length === 1 ? "C" : "C");
    t.key({ key: p.prev }); await settle();
    eq(name + "：上一条", t.api.uid(), "B");
    t.key({ key: p.prev }); await settle();
    t.key({ key: p.prev }); await settle();
    eq(name + "：首条再按上一条：留在 A 并提示", [t.api.uid(), t.toast()], ["A", "js.detail_first"]);
    for (let i = 0; i < 3; i++) { t.key({ key: p.next }); await settle(); }
    t.key({ key: p.next }); await settle();
    eq(name + "：末条再按下一条：留在 D 并提示", [t.api.uid(), t.toast()], ["D", "js.detail_last"]);
    await filtersFor(name, p);
  }
}

async function filtersFor(name, p) {
  const t = loadPanel({ cookie: p.cookie });
  await t.api.openJob("B");
  const withRole = (role) => { const el = new El("div"); el.closestMap[`[role="${role}"]`] = new El("div", { attrs: { role } }); return el; };
  /* 每个用例独立：上一个用例误导航时回到 B，不连锁影响后面的断言 */
  const reset = async () => { if (t.api.uid() !== "B") await t.api.openJob("B"); };
  const cases = [
    ["input", { target: new El("input") }], ["textarea", { target: new El("textarea") }],
    ["select", { target: new El("select") }], ["contenteditable", { target: new El("div", { isContentEditable: true }) }],
    ["地点搜索框", { target: new El("input") }], ["分栏拖条 role=separator", { target: withRole("separator") }],
    ["dialog 内", { target: withRole("dialog") }],
    ["IME isComposing", { isComposing: true }], ["IME keyCode 229", { keyCode: 229 }],
    ["Ctrl", { ctrlKey: true }], ["Meta", { metaKey: true }], ["Alt", { altKey: true }],
    ["自动重复", { repeat: true }], ["已被处理", { defaultPrevented: true }],
  ];
  for (const [label, ev] of cases) {
    const prevented = t.key({ key: p.next, ...ev }); await settle();
    eq(`${name} 忽略：${label}`, [t.api.uid(), prevented], ["B", false]);
    await reset();
  }
  t.document.activeElement = new El("input");
  t.key({ key: p.next }); await settle();
  eq(`${name} 忽略：焦点在输入框（事件来自别处）`, t.api.uid(), "B");
  t.document.activeElement = t.document.body; await reset();
  for (const id of ["drawer", "more-panel", "update-confirm", "display-pop", "copy-modal"]) {
    const el = new El("div"); t.ids.set(id, el);
    t.key({ key: p.next }); await settle();
    eq(`${name} 忽略：${id} 打开`, t.api.uid(), "B");
    el.hidden = true; await reset();
  }
  t.pane.classList.add("label-open");
  t.key({ key: p.next }); await settle();
  eq(`${name} 忽略：标注抽屉打开`, t.api.uid(), "B");
  t.pane.classList.remove("label-open"); await reset();
  if (p.next.startsWith("Arrow")) {
    const prevented = t.key({ key: p.next, shiftKey: true }); await settle();
    eq(`${name}：Shift+方向键（扩选）不导航不拦截`, [t.api.uid(), prevented], ["B", false]);
    await reset();
  }
  t.key({ key: p.next }); await settle();
  eq(`${name}：浮层都关闭后恢复`, t.api.uid(), "C");
  // 保存中：等待；重复按键不排队
  let release; t.api.addPendingNote(new Promise((r) => { release = r; }));
  t.key({ key: p.next }); await tick();
  t.key({ key: p.next }); t.key({ key: p.next }); await tick();
  eq(`${name}：保存中按键等待`, t.api.uid(), "C");
  release(); await settle(); await settle();
  eq(`${name}：保存完成只前进一条`, [t.api.uid(), t.jobCalls().slice(-2)], ["D", ["C", "D"]]);
  // 不在本页列表里的岗位
  const u = loadPanel({ cookie: p.cookie });
  await u.api.openJob("Z");
  u.key({ key: p.next }); await settle();
  eq(`${name}：不在列表的岗位不导航并提示`, [u.api.uid(), u.toast()], ["Z", "js.detail_not_in_list"]);
  // 设置页（无详情面板）
  const s = loadPanel({ cookie: p.cookie }); s.ids.delete("detail");
  eq(`${name}：无详情面板不拦截`, [s.key({ key: p.next }), s.calls.length], [false, 0]);
}

async function testLiveSwitchAndSetKeys() {
  console.log("\n-- 设置：setKeys 写 cookie、现读生效、未知值回 Default --");
  const t = loadPanel();
  const opts = ["default", "vim", "gamer"].map((code) => { const b = new El("button"); b.dataset.keysChoice = code; return b; });
  t.reg["[data-keys-choice]"] = opts;
  await t.api.openJob("A");
  t.api.setKeys("vim");
  check("Vim：写入一年期 cookie", /^jobs_keys=vim; max-age=31536000; path=\/; SameSite=Lax$/.test(t.document.cookie), t.document.cookie);
  eq("Vim：选项选中态", opts.map((b) => b.attrs["aria-pressed"]), ["false", "true", "false"]);
  eq("Vim：提示当前键", t.toast(), "js.keys_saved");
  t.key({ key: "ArrowRight" }); await settle();
  eq("改为 Vim 后 → 立即失效", t.api.uid(), "A");
  t.key({ key: "j" }); await settle();
  eq("改为 Vim 后 J 生效", t.api.uid(), "B");
  t.api.setKeys("gamer");
  t.key({ key: "j" }); await settle();
  t.key({ key: "d" }); await settle();
  eq("改为 Gamer：J 失效、D 生效", t.api.uid(), "C");
  t.api.setKeys("default");
  check("Default：删除 cookie", /^jobs_keys=; max-age=0/.test(t.document.cookie), t.document.cookie);
  t.document.cookie = "";
  eq("Default：选项选中态", opts.map((b) => b.attrs["aria-pressed"]), ["true", "false", "false"]);
  t.key({ key: "ArrowLeft" }); await settle();
  eq("Default：← 生效", t.api.uid(), "B");
  t.api.setKeys("emacs");
  eq("未知方案按 Default 保存", opts.map((b) => b.attrs["aria-pressed"]), ["true", "false", "false"]);
  for (const cookie of ["jobs_keys=emacs", "jobs_keys=", "other=1; jobs_keys=__proto__", "xjobs_keys=vim"]) {
    eq("未知或缺失 cookie → default：" + cookie, loadPanel({ cookie }).api.keyProfile(), "default");
  }
  eq("多个 cookie 中识别 jobs_keys", loadPanel({ cookie: "jobs_lang=en; jobs_keys=gamer; jobs_theme=dark" }).api.keyProfile(), "gamer");
}

async function testTextSelection() {
  console.log("\n-- 正文已有文字选区：方向键留给浏览器（收起选区 / 移动光标） --");
  const t = loadPanel();
  await t.api.openJob("B");
  t.document.selectionText = "Python and SQL";
  for (const key of ["ArrowRight", "ArrowLeft"]) {
    const prevented = t.key({ key }); await settle();
    eq(`Default：有选区时 ${key} 不切条、不拦截`, [t.api.uid(), prevented], ["B", false]);
  }
  t.document.selectionText = "";
  eq("Default：选区收起后（只剩光标）→ 正常下一条", [t.key({ key: "ArrowRight" }), (await settle(), t.api.uid())], [true, "C"]);
  t.key({ key: "ArrowLeft" }); await settle();
  eq("Default：无选区 ← 正常上一条", t.api.uid(), "B");
  for (const [name, next] of [["vim", "j"], ["gamer", "d"]]) {
    const u = loadPanel({ cookie: "jobs_keys=" + name });
    await u.api.openJob("B");
    u.document.selectionText = "Python and SQL";
    u.key({ key: next }); await settle();
    eq(`${name}：字母键没有原生选区动作，有选区时照常切条`, u.api.uid(), "C");
  }
}

async function testHintsFollowCurrentProfile() {
  console.log("\n-- 已打开页面：设置改方案后按钮提示与生效键一致 --");
  const t = loadPanel();
  await t.api.openJob("A");
  const hints = () => t.steps.map((b) => [b.attrs["aria-keyshortcuts"], b.kbd.textContent, b.title]);
  eq("Default：服务端提示保持", hints(), [["ArrowLeft", "←", "Previous (←)"], ["ArrowRight", "→", "Next (→)"],
    ["ArrowLeft", "←", "Previous (←)"], ["ArrowRight", "→", "Next (→)"]]);
  t.document.cookie = "jobs_keys=vim";           // 另一个标签的设置页改成 Vim
  t.docEvent("visibilitychange");
  eq("回到本页：提示改为 K / J（含底栏按钮）", hints(), [["K", "K", "Previous (K)"], ["J", "J", "Next (J)"],
    ["K", "K", "Previous (K)"], ["J", "J", "Next (J)"]]);
  t.key({ key: "j" }); await settle();
  eq("提示与生效键一致：J 下一条", t.api.uid(), "B");
  t.document.cookie = "jobs_keys=gamer";
  await t.api.openJob("C");                     // 打开 / 切条后同步
  eq("切条后提示改为 A / D", hints().map((h) => h[0]), ["A", "D", "A", "D"]);
  t.document.cookie = "";
  t.docEvent("visibilitychange");
  eq("cookie 删除后回到 Default 提示", hints().map((h) => h[1]), ["←", "→", "←", "→"]);
}

await testProfiles();
await testTextSelection();
await testHintsFollowCurrentProfile();
await testLiveSwitchAndSetKeys();
console.log(failures.length ? `\n${failures.length} 项失败` : "\n全部通过");
process.exit(failures.length ? 1 : 0);

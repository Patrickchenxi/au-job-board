#!/usr/bin/env node
/* v1.2.2 PR-B 面板导航与异步的合成 JS 行为检查
（Node 标准库 + 最小 DOM stub，无第三方依赖；执行 panel.js 里的真实函数）。

覆盖：
  - UX-1①：上一条 / 下一条 + J/K 基于页面载入时冻结的列表；标注改变视图成员后
    顺序不变、不跳条；首/末条提示；经过 allowDetailNavigation（保存中等待、草稿确认）；
    等待期间重复按键不排队；待应用新结果（UPDATE_PENDING）时整页载入一次并把目标
    uid 带进 hash，之后的按键不再发起导航；快速连按只认最后一次响应
  - 按键忽略：输入框 / textarea / select / contenteditable、IME 组字（isComposing、
    keyCode 229）、修饰键、自动重复、抽屉或筛选面板打开，以及移动端标注抽屉、
    更新确认窗和顶栏 Display 弹出层打开
  - UX-5：竖屏标注抽屉开合、收起时备注走原保存队列、换条/关闭时收起、Esc 先收抽屉
  - BUG-1：标注 / 备注写入后重拉只读统计；失败保留原数字；乱序响应只认最后一次；
    /api/label 请求体不变
  - UX-11：竖屏筛选抽屉只推迟 applyFilter：改动不跳转、按钮计数、关闭即按快照还原、
    「应用」一次跳转且不再自动展开；桌面即改即生效；有未应用草稿时新结果不整页载入、
    信号保留，关闭后载入一次；搜索防抖与抽屉内输入只进草稿；抽屉内「清除全部」只复位草稿
  - UX-10：固定新增首行、相似优先、完整字母表不按输入过滤；已占用提前提示且不发请求；
    大小写与空白口径与后端一致；点展示名写入规范名

用法：
    node tools/test_panel_navigation.mjs
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
/* 某个 promise 永不完成时 Node 会清空事件循环后直接退出 —— 必须算失败，不能是 0。 */
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

class ClassList {
  constructor() { this.set = new Set(); }
  add(...names) { names.forEach((n) => this.set.add(n)); }
  remove(...names) { names.forEach((n) => this.set.delete(n)); }
  contains(name) { return this.set.has(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.set.has(name) : !!force;
    on ? this.set.add(name) : this.set.delete(name);
    return on;
  }
}

let ACTIVE = { doc: null };
/* 最小元素：选择器查询由测试显式登记（el.q[selector] = [...]），不解析 HTML。 */
class El {
  constructor(tag = "div", props = {}) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.style = {};
    this.classList = new ClassList(this);
    this.dataset = {};
    this.attrs = {};
    this.q = {};
    this.value = "";
    this.checked = false;
    this.type = "";
    this.textContent = "";
    this.hidden = false;
    this.disabled = false;
    this.offsetWidth = 0;
    this.offsetHeight = 0;
    this.scrollTop = 0;
    this.listeners = {};
    this.inside = new Set();
    this.closestMap = {};
    this._html = "";
    Object.assign(this, props);
  }
  set className(v) { this.classList = new ClassList(this); String(v).split(/\s+/).filter(Boolean).forEach((n) => this.classList.add(n)); }
  get className() { return [...this.classList.set].join(" "); }
  set innerHTML(v) { this._html = String(v); if (!v) this.children = []; }
  get innerHTML() { return this._html; }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  fire(type, ev = {}) { (this.listeners[type] || []).forEach((fn) => fn({ type, target: this, preventDefault() {}, ...ev })); }
  querySelector(s) { return (this.q[s] || [])[0] || null; }
  querySelectorAll(s) { return this.q[s] || []; }
  closest(s) { return this.closestMap[s] || null; }
  contains(el) { return el === this || this.inside.has(el); }
  getBoundingClientRect() { return { left: 0, top: 0, right: 200, bottom: 20, width: 200, height: 20 }; }
  focus() { if (ACTIVE.doc) ACTIVE.doc.activeElement = this; }
  blur() {
    const doc = ACTIVE.doc;
    if (doc && doc.activeElement === this) doc.activeElement = doc.body;
    if (this.onblur) this.onblur();
  }
  scrollIntoView() { this.scrolled = (this.scrolled || 0) + 1; }
}

function loadPanel({ lang = "en", cards = ["A", "B", "C", "D"], skills = [], owners = [], portrait = false } = {}) {
  const ids = new Map();
  const reg = {};
  const docListeners = new Map();
  const winListeners = new Map();
  const body = new El("body");
  if (portrait) body.classList.add("portrait");
  const document = {
    body, activeElement: body, hidden: false, cookie: "",
    documentElement: { style: { setProperty() {} }, dataset: {}, lang },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (s) => (reg[s] || [])[0] || null,
    querySelectorAll: (s) => reg[s] || [],
    createElement: (tag) => new El(tag),
    addEventListener(type, fn) { if (!docListeners.has(type)) docListeners.set(type, []); docListeners.get(type).push(fn); },
    removeEventListener() {},
  };
  ACTIVE.doc = document;
  const session = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, Math, JSON, String,
    Number, Object, Array, RegExp, Error, Map, Set, WeakMap, URLSearchParams, URL,
    Node: El,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: (k) => (session.has(k) ? session.get(k) : null), setItem: (k, v) => session.set(k, String(v)), removeItem: (k) => session.delete(k) },
    history: { replaceState() {} },
    location: { href: "", pathname: "/", search: "", hash: "", reload() {} },
    document,
    // 减少动态效果 = 开：reveal/conceal 立即完成，测试不用等动画计时器
    matchMedia: (q) => ({ matches: String(q).includes("reduce"), addEventListener() {}, removeEventListener() {} }),
    innerWidth: 390, innerHeight: 844,
    addEventListener(type, fn) { if (!winListeners.has(type)) winListeners.set(type, []); winListeners.get(type).push(fn); },
    removeEventListener() {},
    confirm: () => false,
    fetch: async () => { throw new Error("fetch 未配置"); },
  };
  sandbox.window = sandbox;
  Object.assign(sandbox, {
    __I18N__: {}, __LABELS__: {}, __NOTE_TAGS__: [], __NOTE_TAG_LABELS__: {}, __SKILLS__: skills,
    __SKILL_OWNERS__: owners, __VIEW__: "all", __STALE_AFTER_DAYS__: 2, __RESULT_GENERATION__: "generation-1",
  });
  let reloads = 0;
  Object.assign(sandbox.location, {
    href: "http://localhost/?view=recommend&since=2026-10-20T00%3A00%3A00#A", pathname: "/",
    search: "?view=recommend&since=2026-10-20T00%3A00%3A00", hash: "#A", reload() { reloads++; },
  });
  sandbox.history.replaceState = (_s, _t, url) => {
    const next = new URL(url, sandbox.location.href);
    Object.assign(sandbox.location, { href: next.href, pathname: next.pathname, search: next.search, hash: next.hash });
  };
  /* 列表卡片（页面载入时的顺序）与详情面板里的固定节点 */
  const cardEls = cards.map((uid) => { const c = new El("div"); c.className = "card"; c.dataset.uid = uid; return c; });
  reg[".list .card"] = cardEls.slice();
  reg[".card"] = cardEls.slice();
  const pane = new El("div"); pane.id = "detail";
  const prev = new El("button"); prev.className = "stepbtn"; prev.dataset.step = "-1"; prev.disabled = true;
  const next = new El("button"); next.className = "stepbtn"; next.dataset.step = "1"; next.disabled = true;
  const pos = new El("span"); pos.className = "d-pos";
  pane.q[".stepbtn"] = [prev, next];
  pane.q[".d-pos"] = [pos];
  pane.q[".note input"] = [];
  pane.q[".label-toggle"] = [];
  ids.set("detail", pane);
  ids.set("toast", new El("div"));
  vm.createContext(sandbox);
  const src = fs.readFileSync(PANEL_JS, "utf8") + `
;globalThis.__T__ = { stepDetail, syncDetailNav, openJob, closeDetail, setLabel, setNote, noteAdopt, noteBlur,
  refreshStats, renderUpdateState, toggleLabelSheet, toggleMore, filterChanged, moreDone, clearHidden, clearFilter,
  applyFilter, searchTyping, filterDraftCount, skillRows, skillRender,
  skillKeys, skillClean, skillOwner, LABELS,
  state(){return {uid:OPEN_UID,pending:UPDATE_PENDING,applying:UPDATE_APPLYING,gates:NAV_GATES,draft:!!FILTER_DRAFT};},
  setUpdate(v){OPEN_UID=v.uid||null;UPDATE_BASELINE=v.baseline||'';UPDATE_PENDING=v.pending||null;UPDATE_APPLYING=false;},
  addPendingNote(p){NOTE_REQUESTS.add(p);p.finally(()=>NOTE_REQUESTS.delete(p));} };
`;
  vm.runInContext(src, sandbox, { filename: "panel.js" });
  const t = {
    api: sandbox.__T__, sandbox, document, ids, reg, pane, prev, next, pos, cards: cardEls,
    reloads: () => reloads,
    key: (ev) => (docListeners.get("keydown") || []).forEach((fn) => fn({ target: body, preventDefault() { this.prevented = true; }, ...ev })),
    calls: [],
  };
  /* fetch 记录：/api/job 默认立即返回该 uid 的详情；其它路由按测试覆盖 */
  t.routes = {
    job: (uid) => ({ ok: true, json: async () => ({ html: "<detail " + uid + ">" }) }),
    label: (body) => ({ ok: true, json: async () => ({ ok: true, field: body.field, value: body.value }), text: async () => "" }),
    stats: () => ({ ok: true, json: async () => ({ labelled: 1, saved: 0, applied: 0 }) }),
    skills: () => ({ ok: true, json: async () => ({ ok: true }) }),
  };
  sandbox.fetch = async (url, opts) => {
    const u = String(url);
    const call = { url: u, body: opts && opts.body ? JSON.parse(opts.body) : null, opts };
    t.calls.push(call);
    if (u.startsWith("/api/job")) return t.routes.job(decodeURIComponent(u.split("uid=")[1]));
    if (u === "/api/label") return t.routes.label(call.body);
    if (u === "/api/stats") return t.routes.stats();
    if (u === "/api/skills") return t.routes.skills(call.body);
    throw new Error("unexpected " + u);
  };
  t.jobCalls = () => t.calls.filter((c) => c.url.startsWith("/api/job")).map((c) => decodeURIComponent(c.url.split("uid=")[1]));
  return t;
}

async function testMobileReopenLoading() {
  console.log("\n-- 移动端重新打开：新请求期间不显示旧详情 --");
  const t = loadPanel({ portrait: true });
  await t.api.openJob("A");
  await t.api.closeDetail();
  t.pane.scrollTop = 300;
  t.pane.classList.add("label-open");
  let respond;
  t.routes.job = () => new Promise((resolve) => { respond = resolve; });
  const opening = t.api.openJob("B");
  eq("入场前替换旧详情为加载占位", t.pane.innerHTML.includes('class="skeleton"'), true);
  eq("不展示旧 A", t.pane.innerHTML.includes("<detail A>"), false);
  eq("入场从顶部开始", t.pane.scrollTop, 0);
  eq("不继承上一条标注抽屉", t.pane.classList.contains("label-open"), false);
  respond({ ok: true, json: async () => ({ html: "<detail B>" }) });
  await opening;
  eq("响应后显示 B", t.pane.innerHTML, "<detail B>");

  // 关闭动画尚未结束时重新打开，也必须先清除旧内容。
  t.pane.classList.add("leaving");
  const reopening = t.api.openJob("B");
  eq("关闭动画中重开也显示加载占位", t.pane.innerHTML.includes('class="skeleton"'), true);
  await t.api.closeDetail();
  respond({ ok: true, json: async () => ({ html: "<detail B late>" }) });
  await reopening;
  eq("关闭后不接纳迟到响应", t.pane.innerHTML.includes("late"), false);

  const desktop = loadPanel();
  await desktop.api.openJob("A");
  await desktop.api.closeDetail();
  desktop.routes.job = () => new Promise((resolve) => { respond = resolve; });
  const desktopOpening = desktop.api.openJob("B");
  eq("桌面保留原有延迟加载占位行为", desktop.pane.innerHTML, "<detail A>");
  respond({ ok: true, json: async () => ({ html: "<detail B>" }) });
  await desktopOpening;
}

async function testFrozenList() {
  console.log("\n-- UX-1①：冻结列表上的上一条 / 下一条 --");
  const t = loadPanel();
  await t.api.openJob("A");
  eq("打开A：位置 1 / 4", t.pos.textContent, "js.detail_pos");
  t.sandbox.__I18N__ = undefined;
  eq("打开A：上一条不可用、下一条可用", [t.prev.disabled, t.next.disabled], [true, false]);
  await t.api.stepDetail(1);
  eq("下一条：A→B，经 openJob 请求B", t.jobCalls(), ["A", "B"]);
  eq("下一条：hash 指向 B 且保留 query", t.sandbox.location.href,
    "http://localhost/?view=recommend&since=2026-10-20T00%3A00%3A00#B");
  eq("B：两侧都可用", [t.prev.disabled, t.next.disabled], [false, false]);
  // 标注让 B、C 离开视图成员（例如标完不再是“未标注”）：DOM 里的列表变了，冻结顺序不变
  t.reg[".list .card"] = [t.cards[0], t.cards[3]];
  await t.api.stepDetail(1);
  eq("视图成员变化后：B→C，不跳过", t.api.state().uid, "C");
  await t.api.stepDetail(-1);
  eq("视图成员变化后：C→B", t.api.state().uid, "B");
  await t.api.stepDetail(1); await t.api.stepDetail(1);
  eq("走到最后一条 D", t.api.state().uid, "D");
  eq("末条：下一条不可用", t.next.disabled, true);
  const before = t.jobCalls().length;
  await t.api.stepDetail(1);
  eq("末条再按下一条：不请求、留在 D", [t.jobCalls().length, t.api.state().uid], [before, "D"]);
  eq("末条再按下一条：提示最后一条", t.ids.get("toast").textContent, "js.detail_last");
  eq("下一条后左栏卡片滚到可见", t.cards[3].scrolled > 0, true);
  {
    const u = loadPanel();
    await u.api.openJob("Z");                     // 从别处（hash）打开的岗位不在本页列表里
    eq("不在列表里的岗位：两个按钮都不可用、无位置", [u.prev.disabled, u.next.disabled, u.pos.textContent], [true, true, ""]);
    await u.api.stepDetail(1);
    eq("不在列表里的岗位：按键不导航", u.api.state().uid, "Z");
    eq("不在列表里的岗位：提示不在本页列表中（不再静默）", u.ids.get("toast").textContent, "js.detail_not_in_list");
  }
  {
    const u = loadPanel();
    u.api.setUpdate({ baseline: "generation-1" });
    await u.api.stepDetail(1);
    eq("没打开详情时 J：打开第一条", u.api.state().uid, "A");
  }
}

async function testNavigationGate() {
  console.log("\n-- UX-1①：保存中 / 草稿 / 待应用新结果 --");
  {
    const t = loadPanel();
    await t.api.openJob("A");
    let release; t.api.addPendingNote(new Promise((r) => { release = r; }));
    const first = t.api.stepDetail(1); await tick();
    eq("备注保存中：等待，不切换", t.api.state().uid, "A");
    t.key({ key: "j" }); t.key({ key: "j" }); const extra = t.api.stepDetail(1); await tick();
    eq("等待期间重复按 J：不排队", t.jobCalls(), ["A"]);
    release(); await first; await extra; await tick();
    eq("保存完成：只前进一条到 B", [t.api.state().uid, t.jobCalls()], ["B", ["A", "B"]]);
    eq("等待结束后门闩归零", t.api.state().gates, 0);
  }
  {
    const t = loadPanel();
    await t.api.openJob("A");
    const input = new El("input"); input.dataset.noteLoaded = "saved"; input.value = "draft";
    t.reg[".note input"] = [input];
    let asked = 0; t.sandbox.confirm = () => { asked++; return false; };
    await t.api.stepDetail(1);
    eq("草稿取消：留在A、hash 不变", [t.api.state().uid, t.sandbox.location.hash], ["A", "#A"]);
    t.key({ key: "k" }); await tick(); await tick();
    eq("首条按 K：只提示，不询问草稿", asked, 1);
    t.sandbox.confirm = () => true;
    await t.api.stepDetail(1);
    eq("草稿确认：继续到B", t.api.state().uid, "B");
  }
  {
    const t = loadPanel();
    await t.api.openJob("A");
    t.api.setUpdate({ uid: "A", baseline: "generation-1", pending: "generation-2" });
    await t.api.stepDetail(1);
    eq("待应用新结果：整页载入一次", t.reloads(), 1);
    eq("待应用新结果：目标B带进 hash、保留 since 冻结参数", t.sandbox.location.href,
      "http://localhost/?view=recommend&since=2026-10-20T00%3A00%3A00#B");
    eq("待应用新结果：不再单独请求B", t.jobCalls(), ["A"]);
    t.key({ key: "j" }); await tick(); await t.api.stepDetail(1); await tick();
    eq("载入中再按 J：不改 hash、不重复载入", [t.sandbox.location.hash, t.reloads(), t.jobCalls().length], ["#B", 1, 1]);
  }
}

async function testRapidKeys() {
  console.log("\n-- UX-1①：快速连按 J/K --");
  const t = loadPanel();
  await t.api.openJob("A");
  const pending = [];
  t.routes.job = (uid) => new Promise((resolve) => pending.push({ uid, resolve }));
  t.key({ key: "j" }); await tick();
  t.key({ key: "j" }); await tick();
  t.key({ key: "J", shiftKey: true }); await tick();
  t.key({ key: "k" }); await tick();
  eq("连按 J J J K：当前目标依次推进到 C", t.api.state().uid, "C");
  eq("连按：每次都基于上一个目标", pending.map((p) => p.uid), ["B", "C", "D", "C"]);
  // 响应乱序回来：只认最后一次请求
  for (const i of [3, 0, 2, 1]) {
    const uid = pending[i].uid;
    pending[i].resolve({ ok: true, json: async () => ({ html: "<detail " + uid + "#" + i + ">" }) });
    await tick();
  }
  await tick();
  eq("乱序响应：详情是最后一次请求的内容", t.pane.innerHTML, "<detail C#3>");
  eq("乱序响应：位置按当前目标", [t.prev.disabled, t.next.disabled], [false, false]);
}

async function testKeyFilters() {
  console.log("\n-- UX-1①：按键忽略条件 --");
  const t = loadPanel();
  await t.api.openJob("A");
  const cases = [
    ["输入框", { target: new El("input") }],
    ["textarea", { target: new El("textarea") }],
    ["select", { target: new El("select") }],
    ["contenteditable", { target: new El("div", { isContentEditable: true }) }],
    ["IME isComposing", { isComposing: true }],
    ["IME keyCode 229", { keyCode: 229 }],
    ["Ctrl", { ctrlKey: true }],
    ["Meta", { metaKey: true }],
    ["Alt", { altKey: true }],
    ["自动重复", { repeat: true }],
    ["已被处理", { defaultPrevented: true }],
  ];
  for (const [name, ev] of cases) {
    t.key({ key: "j", ...ev }); await tick(); await tick();
    eq("忽略：" + name, t.api.state().uid, "A");
  }
  const focused = new El("input"); t.document.activeElement = focused;
  t.key({ key: "j" }); await tick(); await tick();
  eq("忽略：焦点仍在输入框（事件来自别处）", t.api.state().uid, "A");
  t.document.activeElement = t.document.body;
  const drawer = new El("div"); t.ids.set("drawer", drawer);
  t.key({ key: "j" }); await tick(); await tick();
  eq("忽略：汉堡抽屉打开", t.api.state().uid, "A");
  drawer.hidden = true;
  const more = new El("div"); t.ids.set("more-panel", more);
  t.key({ key: "j" }); await tick(); await tick();
  eq("忽略：筛选面板打开", t.api.state().uid, "A");
  more.hidden = true;
  let ev = {}; t.key(Object.assign(ev, { key: "x" }));
  eq("其它键不拦截", ev.prevented, undefined);
  t.key({ key: "j" }); await tick(); await tick();
  eq("普通 J：下一条", t.api.state().uid, "B");
  t.key({ key: "K" }); await tick(); await tick();
  eq("大写 K：上一条", t.api.state().uid, "A");
  {
    const s = loadPanel();
    s.ids.delete("detail");
    s.key({ key: "j" }); await tick();
    eq("设置页（无详情面板）：不处理", s.calls.length, 0);
  }
}

async function testOverlayKeyOwnership() {
  console.log("\n-- UX-1①：浮层打开时 J/K 不切条 --");
  {
    const t = loadPanel({ portrait: true });
    await t.api.openJob("B");
    const sheet = new El("div"); t.ids.set("label-sheet", sheet);
    t.api.toggleLabelSheet(true);
    const j = { key: "j", target: sheet };
    t.key(j); await tick(); await tick();
    eq("标注抽屉：焦点在容器时 J 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    const k = { key: "k", target: sheet };
    t.key(k); await tick(); await tick();
    eq("标注抽屉：焦点在容器时 K 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    t.key({ key: "Escape" });
    eq("标注抽屉：Esc 仍只收抽屉", [t.pane.classList.contains("label-open"), t.api.state().uid], [false, "B"]);
    t.key({ key: "j" }); await tick(); await tick();
    eq("标注抽屉关闭后：J 恢复", t.api.state().uid, "C");
    t.key({ key: "k" }); await tick(); await tick();
    eq("标注抽屉关闭后：K 恢复", t.api.state().uid, "B");
  }
  {
    const t = loadPanel();
    await t.api.openJob("B");
    const confirm = new El("div", { hidden: false });
    const cancel = new El("button");
    confirm.q["[data-update-cancel]"] = [cancel];
    t.ids.set("update-confirm", confirm);
    cancel.focus();
    const j = { key: "j", target: cancel };
    t.key(j); await tick(); await tick();
    eq("更新确认：焦点在按钮时 J 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    const k = { key: "k", target: cancel };
    t.key(k); await tick(); await tick();
    eq("更新确认：焦点在按钮时 K 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    confirm.hidden = true; t.document.activeElement = t.document.body;
    t.key({ key: "j" }); await tick(); await tick();
    eq("更新确认关闭后：J 恢复", t.api.state().uid, "C");
    t.key({ key: "k" }); await tick(); await tick();
    eq("更新确认关闭后：K 恢复", t.api.state().uid, "B");
  }
  {
    const t = loadPanel();
    await t.api.openJob("B");
    const btn = new El("button"), pop = new El("div", { hidden: false }), choice = new El("button");
    choice.className = "on"; pop.q["button.on"] = [choice];
    t.ids.set("display-btn", btn); t.ids.set("display-pop", pop);
    choice.focus();
    const j = { key: "j", target: choice };
    t.key(j); await tick(); await tick();
    eq("Display：焦点在弹出层内时 J 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    const k = { key: "k", target: choice };
    t.key(k); await tick(); await tick();
    eq("Display：焦点在弹出层内时 K 不切条", [t.api.state().uid, t.jobCalls()], ["B", ["B"]]);
    t.key({ key: "Escape" });
    eq("Display：Esc 仍收起并把焦点还给按钮", [pop.hidden, t.document.activeElement === btn], [true, true]);
    t.key({ key: "j" }); await tick(); await tick();
    eq("Display 关闭后：J 恢复", t.api.state().uid, "C");
    t.key({ key: "k" }); await tick(); await tick();
    eq("Display 关闭后：K 恢复", t.api.state().uid, "B");
  }
}

async function testLabelSheet() {
  console.log("\n-- UX-5：竖屏标注抽屉 --");
  const t = loadPanel({ portrait: true });
  await t.api.openJob("A");
  const sheet = new El("div"); t.ids.set("label-sheet", sheet);
  const labelled = new El("b"); labelled.dataset.stat = "labelled"; t.reg["[data-stat]"] = [labelled];
  const toggle = new El("button"); t.pane.q[".label-toggle"] = [toggle];
  const input = new El("input"); input.dataset.uid = "A"; t.api.noteAdopt(input, "Old；");
  input.onblur = () => t.api.noteBlur(input);
  sheet.inside.add(input);
  t.api.toggleLabelSheet();
  eq("打开：detail.label-open + aria-expanded", [t.pane.classList.contains("label-open"), toggle.attrs["aria-expanded"]], [true, "true"]);
  check("打开：焦点进抽屉", t.document.activeElement === sheet);
  input.focus(); input.value = "Draft text";
  let release;
  t.routes.label = (body) => new Promise((resolve) => { release = () => resolve({ ok: true, json: async () => ({ ok: true, value: body.value + "；" }) }); });
  t.api.toggleLabelSheet(false);
  eq("收起：抽屉关闭", t.pane.classList.contains("label-open"), false);
  const notes = t.calls.filter((c) => c.url === "/api/label");
  eq("收起时备注失焦 → 走原保存队列", notes.map((c) => c.body), [{ uid: "A", field: "note", value: "Draft text" }]);
  const step = t.api.stepDetail(1); await tick();
  eq("保存中按下一条：等待保存完成", t.api.state().uid, "A");
  release(); await step; await tick();
  eq("保存完成后切到B", t.api.state().uid, "B");
  eq("统计在备注保存后重拉", t.calls.some((c) => c.url === "/api/stats"), true);
  t.api.toggleLabelSheet(true);
  await t.api.stepDetail(1);
  eq("换条：抽屉收起", t.pane.classList.contains("label-open"), false);
  t.api.toggleLabelSheet(true);
  t.key({ key: "Escape" });
  eq("Esc：先收起标注抽屉，详情不关", [t.pane.classList.contains("label-open"), t.api.state().uid], [false, "C"]);
  t.api.toggleLabelSheet(true);
  await t.api.closeDetail();
  eq("关闭详情：抽屉收起", t.pane.classList.contains("label-open"), false);
}

async function testStats() {
  console.log("\n-- BUG-1：标注后重拉统计 --");
  const t = loadPanel();
  await t.api.openJob("A");
  const stat = (key, text) => { const el = new El("b"); el.dataset.stat = key; el.textContent = text; return el; };
  const els = [stat("labelled", "13"), stat("saved", "4"), stat("applied", "2"), stat("labelled", "13")];
  t.reg["[data-stat]"] = els;
  const btn = new El("button"); btn.dataset.uid = "A"; btn.dataset.field = "action";
  t.reg['[data-uid="A"][data-field="action"]'] = [btn];
  const sum = new El("span"); t.reg["#detail .label-sum"] = [sum]; t.reg['#detail [data-uid="A"]'] = [btn];
  t.routes.stats = () => ({ ok: true, json: async () => ({ labelled: 14, saved: 5, applied: 2 }) });
  await t.api.setLabel("A", "action", "saved", btn); await tick(); await tick();
  eq("写入请求体不变", t.calls.filter((c) => c.url === "/api/label").map((c) => c.body), [{ uid: "A", field: "action", value: "saved" }]);
  eq("统计按键回填（含抽屉里的同键）", els.map((e) => e.textContent), ["14", "5", "2", "14"]);
  eq("统计请求不缓存", t.calls.find((c) => c.url === "/api/stats").opts.cache, "no-store");
  eq("底栏标注摘要同步", sum.textContent, "value.action.saved");
  t.routes.stats = () => { throw new Error("offline"); };
  await t.api.setLabel("A", "action", "saved", btn); await tick(); await tick();
  eq("统计失败：数字保持、按钮照常切换", [els.map((e) => e.textContent), btn.classList.contains("on")], [["14", "5", "2", "14"], false]);
  eq("取消后摘要回到未标注", sum.textContent, "js.detail_unlabelled");
  t.routes.stats = () => ({ ok: false, json: async () => ({}) });
  await t.api.refreshStats(); await tick();
  eq("统计非 2xx：数字保持", els[0].textContent, "14");
  t.routes.stats = () => ({ ok: true, json: async () => ({ labelled: "x", saved: -1, applied: 3.5 }) });
  await t.api.refreshStats(); await tick();
  eq("非法数值：不写入", els.map((e) => e.textContent), ["14", "5", "2", "14"]);
  // 乱序：先发的请求后回来，只认最后一次
  const waiting = [];
  t.routes.stats = () => new Promise((resolve) => waiting.push(resolve));
  const a = t.api.refreshStats(), b = t.api.refreshStats();
  await tick();
  waiting[1]({ ok: true, json: async () => ({ labelled: 16, saved: 6, applied: 2 }) }); await b;
  waiting[0]({ ok: true, json: async () => ({ labelled: 15, saved: 5, applied: 2 }) }); await a;
  eq("乱序响应：保留最后一次请求的结果", els[0].textContent, "16");
  t.routes.label = () => ({ ok: false, text: async () => "boom" });
  const callsBefore = t.calls.length;
  await t.api.setLabel("A", "action", "applied", btn); await tick();
  eq("标注失败：不重拉统计", t.calls.slice(callsBefore).map((c) => c.url), ["/api/label"]);
}

function filterFixture(portrait) {
  const t = loadPanel({ portrait });
  const sel = (key, value) => {
    const el = new El("select"); el.dataset.fkey = key; el.value = value;
    const box = new El("label"); box.className = "ctl" + (value ? " on" : ""); el.closestMap[".ctl"] = box; el.box = box;
    return el;
  };
  const chk = (key, checked, value) => {
    const el = new El("input"); el.type = "checkbox"; el.dataset.fkey = key; el.checked = checked; el.value = value || "1";
    const box = new El("label"); box.className = "ctl tog" + (checked ? " on" : ""); el.closestMap[".ctl"] = box; el.box = box;
    return el;
  };
  const q = new El("input"); q.type = "search"; q.dataset.fkey = "q"; q.value = "python"; q.defaultValue = "python";
  const interest = sel("interest", "");
  const sort = sel("sort", "score"); sort.box.className = "ctl";
  sort.options = [{ value: "score" }, { value: "date" }];
  Object.defineProperty(sort, "selectedIndex", { set(i) { this.value = this.options[i].value; } });
  const salary = chk("salary", false);
  const skillA = chk("skill", true, "Python"), skillB = chk("skill", false, "SQL");
  skillA.nextElementSibling = { textContent: "Python" }; skillB.nextElementSibling = { textContent: "SQL" };
  t.reg["[data-fkey]"] = [q, interest, sort, salary, skillA, skillB];
  t.reg['[data-fkey="interest"]'] = [interest];
  t.reg['[data-fkey="salary"]'] = [salary];
  const pick = new El("div"); pick.q["input[type=checkbox]"] = [skillA, skillB];
  const pickBtn = new El("button"); pickBtn.className = "ctl on"; const pickV = new El("span"); pickV.textContent = "Python";
  pick.querySelector = (s) => (s === "button.ctl" ? pickBtn : s === ".v" ? pickV : null);
  t.ids.set("skillpick", pick);
  const more = new El("div"); more.hidden = true; more.dataset.keys = "interest salary"; t.ids.set("more-panel", more);
  const done = new El("button"); done.textContent = "filter.done"; t.ids.set("more-done", done);
  t.api.setUpdate({ baseline: "generation-1" });
  Object.assign(t.sandbox.location, { href: "http://localhost/?view=all&q=python&skill=Python", search: "?view=all&q=python&skill=Python", hash: "" });
  t.ids.set("update-start", new El("button")); t.ids.set("update-status", new El("span"));
  return { t, q, interest, sort, salary, skillA, skillB, pickBtn, pickV, more, done };
}

async function testFilterDrawer() {
  console.log("\n-- UX-11：竖屏筛选抽屉批量应用 --");
  {
    const f = filterFixture(true);
    const { t } = f;
    const start = t.sandbox.location.href;
    t.api.toggleMore(true);
    eq("打开抽屉：记下快照", t.api.state().draft, true);
    f.interest.value = "want"; t.api.filterChanged(); await tick();
    eq("改一项：不跳转", t.sandbox.location.href, start);
    eq("改一项：按钮写应用（1）", f.done.textContent, "js.filter_apply");
    eq("改一项：控件外观跟随草稿", f.interest.box.classList.contains("on"), true);
    f.salary.checked = true; t.api.filterChanged();
    f.skillB.checked = true; f.skillA.checked = false; t.api.filterChanged(); await tick();
    eq("技能多选摘要跟随草稿", [f.pickV.textContent, f.pickBtn.classList.contains("on")], ["SQL", true]);
    eq("仍未跳转", t.sandbox.location.href, start);
    f.salary.checked = false; t.api.filterChanged();
    f.skillB.checked = false; f.skillA.checked = true; t.api.filterChanged();
    eq("改回原值：不计入改动", f.done.textContent, "js.filter_apply");
    f.interest.value = ""; t.api.filterChanged();
    eq("全部改回：按钮恢复完成", f.done.textContent, "filter.done");
    f.interest.value = "maybe"; f.sort.value = "newest"; t.api.filterChanged();
    t.api.toggleMore(false); await tick();
    eq("关闭：草稿丢弃、控件按快照还原", [f.interest.value, f.sort.value, f.salary.checked, f.skillA.checked], ["", "score", false, true]);
    eq("关闭：外观还原", [f.interest.box.classList.contains("on"), f.done.textContent], [false, "filter.done"]);
    eq("关闭：不跳转", t.sandbox.location.href, start);
    t.api.toggleMore(true);
    f.interest.value = "want"; t.api.filterChanged();
    t.api.clearHidden(); await tick();
    eq("抽屉内清除隐藏条件：同样只改草稿", [t.sandbox.location.href, f.interest.value], [start, ""]);
    f.interest.value = "want"; f.salary.checked = true; t.api.filterChanged();
    t.sandbox.sessionStorage.setItem("jobs.panel.more", "1");
    t.api.moreDone(); await tick(); await tick();
    const url = new URL(t.sandbox.location.href, "http://localhost");
    eq("应用：一次跳转，参数来自控件", [url.searchParams.get("interest"), url.searchParams.get("salary"),
      url.searchParams.getAll("skill"), url.searchParams.get("q"), url.searchParams.get("view")],
    ["want", "1", ["Python"], "python", "all"]);
    eq("应用后不再自动展开抽屉", t.sandbox.sessionStorage.getItem("jobs.panel.more"), null);
  }
  {
    const f = filterFixture(true);
    f.t.api.toggleMore(true);
    f.t.api.moreDone(); await tick();
    eq("无改动点完成：只收起", [f.more.hidden, f.t.sandbox.location.hash], [true, ""]);
    eq("无改动点完成：不跳转", f.t.sandbox.location.href, "http://localhost/?view=all&q=python&skill=Python");
  }
  {
    const f = filterFixture(false);
    f.interest.value = "want"; f.t.api.filterChanged(); await tick(); await tick();
    eq("桌面：即改即生效", new URL(f.t.sandbox.location.href, "http://localhost").searchParams.get("interest"), "want");
  }
  {
    // 新结果版本到达时抽屉里有未应用草稿（且没开岗位）：不整页载入，信号保留；关闭后载入一次
    const f = filterFixture(true); const { t } = f;
    t.api.toggleMore(true);
    f.interest.value = "want"; t.api.filterChanged();
    f.salary.checked = true; t.api.filterChanged();
    t.api.renderUpdateState({ state: "success", generation: "generation-2" }, true); await tick();
    eq("草稿中来了新结果：不载入", t.reloads(), 0);
    eq("草稿中来了新结果：草稿保留、信号保留", [f.interest.value, f.salary.checked, t.api.state().pending], ["want", true, "generation-2"]);
    t.api.renderUpdateState({ state: "success", generation: "generation-2" }, true); await tick();
    eq("下一次轮询仍不载入", t.reloads(), 0);
    t.api.toggleMore(false); await tick();
    eq("关闭抽屉（丢弃草稿）：立刻载入一次", t.reloads(), 1);
    t.api.renderUpdateState({ state: "success", generation: "generation-2" }, true); await tick();
    eq("之后的轮询不再重复载入", t.reloads(), 1);
  }
  {
    const f = filterFixture(true); const { t } = f;
    t.api.toggleMore(true);
    t.api.renderUpdateState({ state: "success", generation: "generation-2" }, true); await tick();
    eq("抽屉开着但没有改动：新结果照常载入", t.reloads(), 1);
  }
  {
    // 搜索防抖窗口内打开抽屉：定时器作废，搜索词进草稿
    const f = filterFixture(true); const { t } = f;
    const start = t.sandbox.location.href;
    f.q.value = "python sql"; t.api.searchTyping({ target: f.q });
    t.api.toggleMore(true);
    await new Promise((r) => setTimeout(r, 450));
    eq("防抖内打开抽屉：不跳转", t.sandbox.location.href, start);
    eq("搜索词计入「应用（N）」", t.api.filterDraftCount(), 1);
    f.q.value = "python sql aws"; t.api.searchTyping({ target: f.q });
    t.api.applyFilter();
    await new Promise((r) => setTimeout(r, 450));
    eq("抽屉内继续输入 / 直接 applyFilter：只更新草稿", [t.sandbox.location.href, t.api.filterDraftCount()], [start, 1]);
    t.api.toggleMore(false); await tick();
    eq("丢弃：搜索框还原为 URL 里的词", f.q.value, "python");
    f.q.value = "rust"; t.api.searchTyping({ target: f.q });
    t.api.toggleMore(true);
    t.api.moreDone(); await tick();
    eq("应用：搜索词一起提交", new URL(t.sandbox.location.href, "http://localhost").searchParams.get("q"), "rust");
  }
  {
    // 抽屉里的「清除全部筛选」：只复位草稿，不跳转
    const f = filterFixture(true); const { t } = f;
    const start = t.sandbox.location.href;
    f.sort.value = "date";
    t.api.toggleMore(true);
    f.salary.checked = true; t.api.filterChanged();
    t.api.clearFilter(); await tick();
    eq("抽屉内清除全部：不跳转", t.sandbox.location.href, start);
    eq("抽屉内清除全部：全部控件复位（排序回默认第一项）",
      [f.q.value, f.interest.value, f.salary.checked, f.skillA.checked, f.sort.value], ["", "", false, false, "score"]);
    eq("抽屉内清除全部：应用（N）计入 q、skill、sort", t.api.filterDraftCount(), 3);
    t.api.toggleMore(false); await tick();
    eq("关闭：清除被丢弃、控件还原",
      [f.q.value, f.salary.checked, f.skillA.checked, f.sort.value], ["python", false, true, "date"]);
    t.api.toggleMore(true); t.api.clearFilter(); t.api.moreDone(); await tick();
    const url = new URL(t.sandbox.location.href, "http://localhost");
    eq("应用清除：一次跳转到默认条件", [url.searchParams.get("q"), url.searchParams.getAll("skill"), url.searchParams.get("sort"), url.searchParams.get("view")],
      [null, [], "score", "all"]);
  }
  {
    const f = filterFixture(false);
    f.t.api.clearFilter(); await tick();
    eq("桌面清除全部：照旧立即跳转", f.t.sandbox.location.href, "/?view=all");
  }
}

async function testSkillCandidates() {
  console.log("\n-- UX-10：技能候选 --");
  const skills = [
    { name: "Amazon Web Services", display_name: "AWS", aliases: ["AWS"] },
    { name: "Kubernetes", display_name: "Kubernetes", aliases: ["K8s"] },
    { name: "Google Cloud Platform", display_name: "Google Cloud Platform", aliases: [] },
    { name: "Python", display_name: "Python", aliases: [] },
    { name: "Ansible", display_name: "Ansible", aliases: [] },
    { name: "TypeScript", display_name: "TypeScript", aliases: ["TS"] },
  ];
  const owners = [["amazon web services", "Amazon Web Services"], ["ansible", "Ansible"], ["aws", "Amazon Web Services"],
    ["google cloud platform", "Google Cloud Platform"], ["k8s", "Kubernetes"], ["kubernetes", "Kubernetes"],
    ["python", "Python"], ["ts", "TypeScript"], ["typescript", "TypeScript"]];
  const t = loadPanel({ skills, owners });
  const alpha = ["Ansible", "AWS", "Google Cloud Platform", "Kubernetes", "Python", "TypeScript"];
  const kinds = (rows) => rows.map((r) => r.kind);
  const labels = (rows, kind) => rows.filter((r) => r.kind === kind).map((r) => r.label);
  {
    const { rows } = t.api.skillRows("GCP");
    eq("首行固定新增", rows[0].kind, "add");
    eq("可能是组：首字母缩写优先", rows[2].label, "Google Cloud Platform");
    const all = rows.slice(rows.findLastIndex((r) => r.kind === "group") + 1);
    eq("完整字母表：不按输入过滤、按显示名排序", all.map((r) => r.label), alpha);
    eq("可用的别名行写入规范名", all.map((r) => r.target), ["Ansible", "Amazon Web Services", "Google Cloud Platform", "Kubernetes", "Python", "TypeScript"]);
    eq("别名灰字：规范名与别名（不重复展示名）", all[1].extra, ["Amazon Web Services"]);
  }
  {
    const { rows } = t.api.skillRows("Google Cloud");
    eq("词重叠/子串：GCP 在可能是组", labels(rows.slice(1, rows.findLastIndex((r) => r.kind === "group")), "alias"), ["Google Cloud Platform"]);
    const { rows: r2 } = t.api.skillRows("Kube");
    eq("子串：Kube → Kubernetes", r2[2].label, "Kubernetes");
    const { rows: r3 } = t.api.skillRows("zzzz");
    eq("无相似：没有可能是组，仍列全部", [kinds(r3).filter((k) => k === "group").length, labels(r3, "alias")], [1, alpha]);
  }
  {
    const empty = t.api.skillRows("   ");
    eq("空输入：提示行 + 全部（不可点）", [empty.rows[0].kind, empty.rows.filter((r) => r.kind === "alias").every((r) => r.off)], ["hint", true]);
    for (const token of ["aws", "AWS", " Aws ", "Amazon  Web　Services", "amazon web services", "k8S", "\x1cpython\x1f"]) {
      const r = t.api.skillRows(token);
      eq("已占用（同后端小写/空白口径）：" + JSON.stringify(token),
        [r.owner, r.rows[0].kind, r.rows.some((x) => x.kind === "add"), r.rows.filter((x) => x.kind === "alias").every((x) => x.off)],
        [skills.find((s) => s.name === r.owner) ? r.owner : null, "taken", false, true]);
    }
    eq("已占用提示写展示名", t.api.skillRows("amazon web services").rows[0].label, "js.skill_taken");
    eq("\\ufeff 不是 Python 空白：不算占用", t.api.skillOwner("﻿aws"), null);
    eq("清理与 skills._clean 一致", t.api.skillClean("  a \t b　c\n"), "a b c");
    eq("中间多空格不等于后端 token", t.api.skillOwner("Amazon WebServices"), null);
  }
  {
    // 渲染与点选：写入规范名
    const input = new El("input"); input.id = "skill-q"; input.value = "cloud-aws";
    const menu = new El("div"); t.ids.set("skill-q", input); t.ids.set("skill-menu", menu);
    t.api.skillRender();
    const items = menu.children.filter((c) => c.classList.contains("note-item"));
    eq("渲染：首个可点项为新增", items[0].classList.contains("note-add"), true);
    const aws = items.find((c) => c.dataset.target === "Amazon Web Services");
    eq("渲染：显示展示名 AWS", aws.textContent, "AWS");
    aws.fire("mousedown");
    await tick(); await tick();
    const post = t.calls.filter((c) => c.url === "/api/skills").map((c) => c.body);
    eq("点 AWS：写入规范名 Amazon Web Services", post, [{ token: "cloud-aws", action: "alias", target: "Amazon Web Services" }]);
  }
  {
    const u = loadPanel({ skills, owners });
    const input = new El("input"); input.id = "skill-q"; input.value = "K8S";
    const menu = new El("div"); u.ids.set("skill-q", input); u.ids.set("skill-menu", menu);
    u.api.skillRender();
    eq("已占用：菜单首行是提示，不出现新增", [menu.children[0].classList.contains("note-warn"), menu.children.some((c) => c.classList.contains("note-add"))], [true, false]);
    menu.children.find((c) => c.dataset.target === "Python").fire("mousedown");
    u.api.skillKeys({ key: "Enter", target: input, preventDefault() {} });
    await tick();
    eq("已占用：点别名 / 回车都不发请求", u.calls.filter((c) => c.url === "/api/skills").length, 0);
    eq("已占用：回车给出提示", u.ids.get("toast").textContent, "js.skill_taken");
    input.value = "Helm";
    u.api.skillKeys({ key: "Enter", target: input, preventDefault() {} });
    await tick();
    eq("新词回车：新增", u.calls.filter((c) => c.url === "/api/skills").map((c) => c.body), [{ token: "Helm", action: "add", target: "" }]);
  }
}

async function main() {
  console.log("== v1.2.2 PR-B 面板导航与异步（合成数据，Node vm + 最小 DOM stub）==");
  console.log(`Node ${process.version}；加载 ${path.relative(ROOT, PANEL_JS)}`);
  await testMobileReopenLoading();
  await testFrozenList();
  await testNavigationGate();
  await testRapidKeys();
  await testKeyFilters();
  await testOverlayKeyOwnership();
  await testLabelSheet();
  await testStats();
  await testFilterDrawer();
  await testSkillCandidates();
  console.log();
  if (failures.length) {
    console.log(`失败 ${failures.length} 项：\n  - ${failures.join("\n  - ")}`);
    process.exit(2);
  }
  console.log("全部通过");
  process.exit(0);
}

main().catch((err) => {
  console.error("harness 出错：", err);
  process.exit(3);
});

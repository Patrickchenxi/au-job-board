#!/usr/bin/env node
/* v1.3 #18 详情「复制岗位」的合成 JS 行为检查
（Node 标准库 + 最小 DOM stub，无第三方依赖；执行 panel.js 里的真实函数）。

覆盖：
  - 复制的是按钮 data-copy-text 里服务端给的完整文本（长文本、HTML 敏感字符原样），
    不是渲染后的 DOM
  - 安全上下文：Clipboard API 成功 → 成功提示（按钮上也短暂标记），不走降级
  - Clipboard 被拒 / 非安全上下文（HTTP）/ 没有 Clipboard → execCommand 降级；
    降级后临时文本框移除、原选区与焦点恢复
  - 都失败（返回 false 或抛错）→ 不提示成功，打开手动复制框：同一份完整文本、
    已聚焦；Esc / 关闭把焦点还给按钮；打开期间快捷键不切条
  - 复制进行中重复点击不重复写；不发请求、不改标注、不动导航门闩
  - 找不到复制文本 → 明确提示，不打开空的手动框

用法：
    node tools/test_panel_copy.mjs
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
      q: {}, hidden: false, textContent: "", value: "", listeners: {}, isConnected: true, selected: false });
    Object.assign(this, props);
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); }
  fire(t, ev = {}) { let stopped = false; (this.listeners[t] || []).forEach((fn) => fn({ target: this, preventDefault() {}, stopPropagation() { stopped = true; }, ...ev })); return stopped; }
  querySelector(s) { return (this.q[s] || [])[0] || null; }
  querySelectorAll(s) { return this.q[s] || []; }
  closest() { return null; }
  contains(el) { return el === this; }
  focus() { if (ACTIVE) ACTIVE.activeElement = this; }
  blur() {}
  // 浏览器里全选文本框会替换页面原有选区
  select() { this.selected = true; if (ACTIVE && ACTIVE.getSelection) ACTIVE.getSelection().removeAllRanges(); }
  remove() { this.isConnected = false; if (ACTIVE) ACTIVE.removed.push(this); }
  scrollIntoView() {}
}

const LONG = "Intro\n</button><script>alert(1)</script><img src=x onerror=alert(2)> & \"q\" 'single' 中文\n"
  + Array.from({ length: 600 }, (_, i) => `Requirement ${i}: ` + "y".repeat(100)).join("\n") + "\nEND-OF-JD\n";
const TEXT = "UID: synthetic:copy\nTitle: Engineer <b>\"Lead\"</b>\nCompany: A&B <Co>\nLocation: Sydney NSW\n"
  + "Listing link: https://example.invalid/job?a=1&b=<2>\n\nFull job description:\n" + LONG;

function loadPanel({ secure = true, clipboard = "ok", exec = true } = {}) {
  const ids = new Map(), reg = {}, docListeners = new Map();
  const body = new El("body");
  body.appendChild = (c) => { appended.push(c); return c; };
  const appended = [];
  const range = { id: "user-range" };
  const selection = { ranges: [range], get rangeCount() { return this.ranges.length; }, getRangeAt(i) { return this.ranges[i]; },
    removeAllRanges() { this.ranges = []; }, addRange(r) { this.ranges.push(r); } };
  const execCalls = [];
  const document = {
    body, activeElement: body, hidden: false, cookie: "", removed: [],
    documentElement: { style: { setProperty() {} }, dataset: {}, lang: "en", classList: new ClassList() },
    getElementById: (id) => ids.get(id) || null,
    querySelector: (s) => (reg[s] || [])[0] || null,
    querySelectorAll: (s) => reg[s] || [],
    createElement: (tag) => new El(tag),
    addEventListener(t, fn) { if (!docListeners.has(t)) docListeners.set(t, []); docListeners.get(t).push(fn); },
    removeEventListener() {},
    getSelection: () => selection,
    execCommand(cmd) {
      execCalls.push({ cmd, text: document.activeElement && document.activeElement.value, selected: document.activeElement && document.activeElement.selected });
      if (exec === "throw") throw new Error("blocked");
      return exec;
    },
  };
  ACTIVE = document;
  const writes = [];
  let release = null;
  const clip = clipboard === null ? undefined : {
    writeText(text) {
      writes.push(text);
      if (clipboard === "ok") return Promise.resolve();
      if (clipboard === "hang") return new Promise((resolve) => { release = resolve; });
      return Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    },
  };
  const sandbox = {
    console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, Math, JSON, String, Number,
    Object, Array, RegExp, Error, Map, Set, WeakMap, URLSearchParams, URL, Node: El, document,
    navigator: clip ? { clipboard: clip } : {}, isSecureContext: secure,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    history: { replaceState() {} },
    location: { href: "http://localhost/", pathname: "/", search: "", hash: "", reload() {} },
    matchMedia: (q) => ({ matches: String(q).includes("reduce"), addEventListener() {}, removeEventListener() {} }),
    innerWidth: 390, innerHeight: 844, addEventListener() {}, removeEventListener() {}, confirm: () => false,
    __I18N__: {}, __LABELS__: { A: { action: "saved" } }, __NOTE_TAGS__: [], __NOTE_TAG_LABELS__: {}, __SKILLS__: [],
    __SKILL_OWNERS__: [], __VIEW__: "all", __STALE_AFTER_DAYS__: 2, __RESULT_GENERATION__: "generation-1",
  };
  sandbox.window = sandbox;
  const cards = ["A", "B"].map((uid) => { const c = new El("div"); c.dataset.uid = uid; return c; });
  reg[".list .card"] = cards; reg[".card"] = cards;
  const pane = new El("div"); pane.id = "detail";
  pane.q[".stepbtn"] = []; pane.q[".d-pos"] = [];
  ids.set("detail", pane); ids.set("toast", new El("div"));
  const btn = new El("button"); btn.dataset.copyText = TEXT;
  reg["#detail [data-copy-text]"] = [btn];
  // 手动复制框（服务端 _copy_dialog 渲染的同一组节点）
  const modal = new El("div", { hidden: true }); modal.id = "copy-modal";
  const ta = new El("textarea"), pick = new El("button"), close = new El("button");
  modal.q["#copy-modal-text"] = [ta]; modal.q["[data-copy-select]"] = [pick]; modal.q["[data-copy-close]"] = [close];
  ids.set("copy-modal", modal);
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(PANEL_JS, "utf8") + `
;globalThis.__T__ = { copyJob, openJob, uid(){return OPEN_UID;}, gates(){return NAV_GATES;}, LABELS };`,
  sandbox, { filename: "panel.js" });
  const calls = [];
  sandbox.fetch = async (url) => {
    calls.push(String(url));
    if (String(url).startsWith("/api/job")) return { ok: true, json: async () => ({ html: "<detail>" }) };
    throw new Error("unexpected " + url);
  };
  (docListeners.get("DOMContentLoaded") || []).forEach((fn) => { try { fn(); } catch (e) { /* 其它模块的初始化与本测试无关 */ } });
  return {
    api: sandbox.__T__, document, btn, modal, ta, pick, close, writes, execCalls, appended, selection, range, calls, pane,
    release: () => release && release(),
    toast: () => ids.get("toast").textContent,
    key(ev) { let p = false; const e = { target: body, preventDefault() { p = true; }, ...ev }; (docListeners.get("keydown") || []).forEach((fn) => fn(e)); return p; },
  };
}

async function testClipboardSuccess() {
  console.log("\n-- 安全上下文：Clipboard API --");
  const t = loadPanel();
  t.btn.focus();
  const labels = JSON.stringify(t.api.LABELS);
  await t.api.copyJob(t.btn);
  eq("写入的是完整文本（含长 JD 与 HTML 敏感字符）", t.writes, [TEXT]);
  check("完整 JD 未截断", t.writes[0].endsWith("END-OF-JD\n") && t.writes[0].length > 60000, String(t.writes[0].length));
  eq("不走降级", t.execCalls.length, 0);
  eq("提示成功", t.toast(), "js.copy_done");
  eq("按钮上也短暂标记已复制（不被同时出现的其它 toast 顶掉）", [t.btn.textContent, t.btn.classList.contains("copied")], ["js.copy_done_short", true]);
  eq("手动框不打开", t.modal.hidden, true);
  eq("不发请求、不改标注、不动门闩", [t.calls, JSON.stringify(t.api.LABELS), t.api.gates()], [[], labels, 0]);
  eq("焦点留在按钮", t.document.activeElement === t.btn, true);
}

async function testFallbacks() {
  for (const [label, opts] of [["Clipboard 被拒（权限）", { clipboard: "deny" }], ["非安全上下文（HTTP）", { secure: false }],
    ["没有 Clipboard API", { clipboard: null }]]) {
    console.log(`\n-- ${label} → execCommand 降级 --`);
    const t = loadPanel(opts);
    t.btn.focus();
    await t.api.copyJob(t.btn);
    if (opts.secure === false) eq(label + "：不调用 Clipboard API", t.writes.length, 0);
    eq(label + "：execCommand('copy') 复制同一份完整文本且已全选",
      t.execCalls.map((c) => [c.cmd, c.text === TEXT, c.selected]), [["copy", true, true]]);
    eq(label + "：临时文本框已移除", t.appended.length === 1 && t.appended[0].isConnected === false, true);
    eq(label + "：原选区恢复", t.selection.ranges, [t.range]);
    eq(label + "：焦点回到按钮", t.document.activeElement === t.btn, true);
    eq(label + "：提示成功、手动框不打开", [t.toast(), t.modal.hidden], ["js.copy_done", true]);
  }
}

async function testManualFallback() {
  for (const [label, opts] of [["降级返回 false", { clipboard: "deny", exec: false }], ["降级抛错", { secure: false, exec: "throw" }]]) {
    console.log(`\n-- ${label} → 手动复制框 --`);
    const t = loadPanel(opts);
    t.btn.focus();
    await t.api.copyJob(t.btn);
    check(label + "：不提示成功", t.toast() !== "js.copy_done", t.toast());
    eq(label + "：按钮不标记已复制", t.btn.classList.contains("copied"), false);
    eq(label + "：手动框打开，内容是同一份完整文本", [t.modal.hidden, t.ta.value === TEXT], [false, true]);
    eq(label + "：文本已聚焦并全选", [t.document.activeElement === t.ta, t.ta.selected], [true, true]);
    eq(label + "：打开期间快捷键不切条", t.key({ key: "ArrowRight" }), false);
    t.ta.selected = false; t.pick.fire("click");
    eq(label + "：「全选」重新选中", t.ta.selected, true);
    const stopped = t.modal.fire("keydown", { key: "Escape" });
    eq(label + "：Esc 关闭、不冒泡给其它 Esc 处理、焦点回到按钮", [t.modal.hidden, stopped, t.document.activeElement === t.btn], [true, true, true]);
    await t.api.copyJob(t.btn);
    t.close.fire("click");
    eq(label + "：「关闭」同样还焦点", [t.modal.hidden, t.document.activeElement === t.btn], [true, true]);
    await t.api.copyJob(t.btn);
    t.btn.isConnected = false;           // 期间换了一条岗位：旧按钮已不在页面
    t.modal.fire("click", { target: t.modal });
    eq(label + "：点遮罩关闭；旧按钮不在时不强行聚焦", [t.modal.hidden, t.document.activeElement === t.btn], [true, false]);
    eq(label + "：全程不发请求", t.calls, []);
  }
}

async function testRepeatAndMissing() {
  console.log("\n-- 重复点击 / 缺少复制文本 --");
  const t = loadPanel({ clipboard: "hang" });
  const first = t.api.copyJob(t.btn);
  await t.api.copyJob(t.btn); await t.api.copyJob(t.btn);
  eq("复制进行中重复点击不重复写", t.writes.length, 1);
  t.release(); await first;
  eq("完成后提示成功", t.toast(), "js.copy_done");
  const again = t.api.copyJob(t.btn); t.release(); await again;
  eq("完成后可再次复制", t.writes.length, 2);
  const m = loadPanel();
  m.btn.dataset = {};
  m.document.querySelector = () => null;
  await m.api.copyJob(m.btn);
  eq("缺少文本：明确提示、不写剪贴板、不打开空手动框", [m.toast(), m.writes.length, m.modal.hidden], ["js.copy_missing", 0, true]);
}

await testClipboardSuccess();
await testFallbacks();
await testManualFallback();
await testRepeatAndMissing();
console.log(failures.length ? `\n${failures.length} 项失败` : "\n全部通过");
process.exit(failures.length ? 1 : 0);

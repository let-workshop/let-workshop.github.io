#!/usr/bin/env node
/* What holding an arrow does, tested without a browser.
 *
 * holdToRepeat is lifted out of the built page and run against a DOM stub and
 * a clock this file controls, so the timings are checked rather than trusted:
 * a tap is one step, a hold repeats and accelerates, and the repeat stops at
 * the end of the list, on release, and when the window loses focus.
 *
 *     node tools/test-hold.js          (after python3 build.py)
 */
const fs = require("fs");
const path = require("path");

const page = fs.readFileSync(
  path.join(__dirname, "..", "_site", "2026", "index.html"), "utf8");
const from = page.indexOf("function holdToRepeat(");
const to = page.indexOf("holdToRepeat(", from + 10);
if (from < 0 || to < 0) {
  console.error("could not find holdToRepeat in _site/2026/index.html");
  process.exit(2);
}

// A clock that only moves when this file says so.
let now = 0;
let queue = [];
globalThis.setTimeout = (fn, ms) => { const id = {}; queue.push({ id, at: now + ms, fn }); return id; };
globalThis.clearTimeout = (id) => { queue = queue.filter((t) => t.id !== id); };
globalThis.Date = { now: () => now };
function tick(ms) {
  const until = now + ms;
  for (;;) {
    const next = queue.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0];
    if (!next) break;
    queue = queue.filter((t) => t !== next);
    now = next.at;
    next.fn();
  }
  now = until;
}

function El() {
  return {
    listeners: {}, disabled: false,
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    fire(t, ev) { (this.listeners[t] || []).forEach((f) => f(ev || {})); },
  };
}
const prev = El(), next = El(), modal = El(), win = {};
globalThis.document = { getElementById: (id) => (id === "p" ? prev : next) };
globalThis.addEventListener = (t, f) => { (win[t] = win[t] || []).push(f); };

let pos = 0;
let stamps = [];
const LAST = 15;
const step = (by) => { stamps.push(now); pos = Math.max(0, Math.min(LAST, pos + by)); };
const where = () => pos;

new Function("holdToRepeat", "step", "where", "modal",
  page.slice(from, to) + "\nholdToRepeat([['p', -1], ['n', 1]], step, where, modal);"
)(undefined, step, where, modal);

const cases = [
  ["a tap moves exactly one", () => {
    next.fire("pointerdown"); tick(80); next.fire("pointerup"); next.fire("click");
    return pos === 1;
  }],
  ["a press shorter than the hold delay never repeats", () => {
    next.fire("pointerdown"); tick(400); next.fire("pointerup"); next.fire("click");
    return pos === 1;
  }],
  ["a hold waits out the tap, then repeats", () => {
    next.fire("pointerdown");
    tick(419);
    const beforeDelay = pos;    // still nothing: a tap is not a hold
    tick(1);
    const firstRepeat = pos;
    next.fire("pointerup");
    return beforeDelay === 0 && firstRepeat === 1;
  }],
  ["the repeats get closer together", () => {
    stamps = [];
    next.fire("pointerdown");
    tick(3000);
    next.fire("pointerup");
    const gaps = stamps.slice(1).map((t, i) => t - stamps[i]);
    // Starts at 240ms, floors at 110, and never widens on the way.
    const monotonic = gaps.every((g, i) => i === 0 || g <= gaps[i - 1] + 0.001);
    if (process.env.SHOW) console.log("      gaps:", gaps.join(" "));
    return gaps.length > 8 && gaps[0] === 240 &&
           gaps[gaps.length - 1] === 110 && monotonic;
  }],
  ["the click that ends a hold adds nothing", () => {
    next.fire("pointerdown"); tick(2000); next.fire("pointerup");
    const held = pos; next.fire("click");
    return pos === held;
  }],
  ["it stops at the end of the list", () => {
    pos = LAST - 1;
    next.fire("pointerdown"); tick(6000); next.fire("pointerup");
    return pos === LAST && queue.length === 0;
  }],
  ["releasing stops it", () => {
    next.fire("pointerdown"); tick(700);
    const atRelease = pos;
    next.fire("pointerup"); tick(3000);
    return pos === atRelease;
  }],
  ["losing the window stops it", () => {
    next.fire("pointerdown"); tick(700);
    const atBlur = pos;
    (win.blur || []).forEach((f) => f()); tick(3000);
    return pos === atBlur;
  }],
  ["closing the sheet stops it", () => {
    next.fire("pointerdown"); tick(700);
    const atClose = pos;
    modal.fire("close"); tick(3000);
    return pos === atClose;
  }],
];

let bad = 0;
for (const [what, run] of cases) {
  pos = 0; queue = []; now += 10000;
  const ok = run();
  if (!ok) bad++;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}`);
}
console.log(bad ? `  ${bad} failed` : `  ${cases.length} cases, all as intended`);
process.exit(bad ? 1 : 0);

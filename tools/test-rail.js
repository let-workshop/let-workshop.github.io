#!/usr/bin/env node
/* What the speaker rail does with a pointer, tested without a browser.
 *
 * The rail's handlers are lifted out of the built page and run against a DOM
 * stub — enough of one for events, classes and geometry. It exists because a
 * fault got through that no amount of reading the code had caught: a press
 * whose release the rail never heard left it dragging for good, and from then
 * on a plain hover scrubbed the panel. That is four lines of state and it is
 * exactly the kind of thing a test pins down.
 *
 *     node tools/test-rail.js          (after python3 build.py)
 */
const fs = require("fs");
const path = require("path");

const page = fs.readFileSync(
  path.join(__dirname, "..", "_site", "2026", "index.html"), "utf8");
const from = page.indexOf("// Hover to read a name, click to go there");
const to = page.indexOf('document.getElementById("spk-prev").onclick', from);
if (from < 0 || to < 0) {
  console.error("could not find the rail's handlers in _site/2026/index.html");
  process.exit(2);
}
const handlers = page.slice(from, to);

function El() {
  return {
    listeners: {},
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    fire(t, ev) { (this.listeners[t] || []).forEach((f) => f(ev || {})); },
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    setPointerCapture() {}, releasePointerCapture() {},
    style: { setProperty() {} },
    getBoundingClientRect: () => ({ left: 0, width: 10, right: 10 }),
  };
}

const bar = El(), rail = El(), win = {};
let opened = [];
globalThis.document = { getElementById: () => rail };
globalThis.STRIP = { bar, ticks: [], order: [0, 1, 2] };
globalThis.spkAt = 0;
globalThis.openSpeaker = (i) => { opened.push(i); globalThis.spkAt = i; };
globalThis.swell = () => {};
globalThis.point = () => {};
globalThis.nearestTick = (x) => Math.max(0, Math.min(2, Math.round(x / 14)));
globalThis.addEventListener = (t, f) => { (win[t] = win[t] || []).push(f); };

new Function(handlers)();

const press = (x) => bar.fire("pointerdown", { pointerId: 1, clientX: x, preventDefault() {} });
const cases = [
  ["a hover with no button held opens nobody", () => {
    bar.fire("mousemove", { clientX: 28, buttons: 0 });
    return opened.length === 0;
  }],
  ["a click opens the tick it landed on", () => {
    press(28); bar.fire("pointerup", { pointerId: 1 });
    return opened.join() === "2";
  }],
  ["a drag walks every tick it crosses", () => {
    // Starting somewhere other than the tick the press lands on, since scrub
    // skips a move to where the panel already is.
    globalThis.spkAt = 2;
    press(0);
    bar.fire("pointermove", { pointerId: 1, clientX: 14, buttons: 1 });
    bar.fire("pointermove", { pointerId: 1, clientX: 28, buttons: 1 });
    bar.fire("pointerup", { pointerId: 1 });
    return opened.join() === "0,1,2";
  }],
  ["a release the rail never hears still ends the drag", () => {
    press(0);
    (win.pointerup || []).forEach((f) => f({ pointerId: 1 }));
    opened = [];
    bar.fire("mousemove", { clientX: 28, buttons: 0 });
    bar.fire("pointermove", { pointerId: 1, clientX: 28, buttons: 0 });
    return opened.length === 0;
  }],
];

let bad = 0;
for (const [what, run] of cases) {
  opened = [];
  globalThis.spkAt = 0;
  const ok = run();
  if (!ok) bad++;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}`);
}
console.log(bad ? `  ${bad} failed` : "  4 cases, all as intended");
process.exit(bad ? 1 : 0);

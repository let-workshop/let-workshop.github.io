#!/usr/bin/env node
/* What a swipe across one of the sheets does, tested without a browser.
 *
 * swipeToStep is lifted out of the built page and driven with made-up pointer
 * events: a mouse drag is not a swipe, a scroll is not a swipe, a short flick
 * is not a swipe, and one that starts on the rail belongs to the rail.
 *
 *     node tools/test-swipe.js         (after python3 build.py)
 */
const fs = require("fs");
const path = require("path");

const page = fs.readFileSync(
  path.join(__dirname, "..", "_site", "2026", "index.html"), "utf8");
const from = page.indexOf("function swipeToStep(");
const to = page.indexOf("holdToRepeat(", from);
if (from < 0 || to < 0) {
  console.error("could not find swipeToStep in _site/2026/index.html");
  process.exit(2);
}

function El(cls) {
  return {
    cls: cls || "", listeners: {}, disabled: false, style: {},
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    fire(t, ev) { (this.listeners[t] || []).forEach((f) => f(ev)); },
    closest(sel) { return this.cls === sel.slice(1) ? this : null; },
    getBoundingClientRect: () => ({ width: 360 }),
  };
}

const sheet = El();
const body = El("sp-body");
const card = El("card");
const rail = El("spk-strip-bar");
const prevBtn = El(), nextBtn = El();
let moved = [];
let prevented = 0;

// A clock and a frame callback this file drives, so the turn can be watched
// rather than waited for.
let now = 0, queue = [];
globalThis.setTimeout = (fn, ms) => { const id = {}; queue.push({ id, at: now + ms, fn }); return id; };
globalThis.clearTimeout = (id) => { queue = queue.filter((t) => t.id !== id); };
globalThis.requestAnimationFrame = (fn) => globalThis.setTimeout(fn, 16);
globalThis.matchMedia = () => ({ matches: false });
globalThis.document = { getElementById: (id) => (id === "p" ? prevBtn : nextBtn) };
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

const swipeToStep = new Function(page.slice(from, to) + "\nreturn swipeToStep;")();
swipeToStep(sheet, (by) => moved.push(by), {
  prev: "p", next: "n", cards: [card],
  skip: (target) => !!(target.closest && target.closest(".spk-strip-bar")),
});

function gesture(opts) {
  const { dx = 0, dy = 0, type = "touch", target = body, steps = 6 } = opts;
  prevented = 0;
  const ev = (n, extra) => Object.assign(
    { pointerId: 7, isPrimary: true, pointerType: type, target,
      cancelable: true, preventDefault: () => prevented++ },
    { clientX: 100 + (dx * n) / steps, clientY: 200 + (dy * n) / steps }, extra);
  sheet.fire("pointerdown", ev(0));
  for (let n = 1; n <= steps; n++) sheet.fire("pointermove", ev(n));
  return { release: () => sheet.fire("pointerup", ev(steps)) };
}
function swipe(opts) {
  const g = gesture(opts);
  g.release();
  tick(1200);            // let the turn finish
}

const cases = [
  ["a swipe left steps forward", () => { swipe({ dx: -120 }); return moved.join() === "1"; }],
  ["a swipe right steps back", () => { swipe({ dx: 120 }); return moved.join() === "-1"; }],
  ["a flick shorter than the commit does nothing", () => { swipe({ dx: -40 }); return moved.length === 0; }],
  ["a scroll down does nothing, and is not blocked", () => {
    swipe({ dy: 200 }); return moved.length === 0 && prevented === 0;
  }],
  ["a mostly-down arc does nothing", () => { swipe({ dx: -90, dy: 90 }); return moved.length === 0; }],
  ["a horizontal swipe cancels the scroll it would cause", () => {
    swipe({ dx: -120 }); return prevented > 0;
  }],
  ["a mouse drag is not a swipe", () => { swipe({ dx: -200, type: "mouse" }); return moved.length === 0; }],
  ["a swipe starting on the rail belongs to the rail", () => {
    swipe({ dx: -120, target: rail }); return moved.length === 0;
  }],
  ["the card follows the finger", () => {
    const g = gesture({ dx: -90 });
    const held = card.style.transform;
    g.release(); tick(1200);
    return /translate3d\(-90px/.test(held);
  }],
  ["and is put back where it started when the turn is over", () => {
    swipe({ dx: -120 });
    return !card.style.transform && !card.style.opacity;
  }],
  ["a card released short of the commit springs back", () => {
    const g = gesture({ dx: -40 });
    const held = card.style.transform;
    g.release(); tick(1200);
    return /translate3d\(-40px/.test(held) && !card.style.transform;
  }],
  ["past the last card the finger gets a third of what it asks", () => {
    nextBtn.disabled = true;
    const g = gesture({ dx: -90 });
    const held = card.style.transform;
    g.release(); tick(1200);
    nextBtn.disabled = false;
    return /translate3d\(-28.8px/.test(held) && moved.length === 0;
  }],
];

let bad = 0;
for (const [what, run] of cases) {
  moved = [];
  const ok = run();
  if (!ok) bad++;
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${what}`);
}
console.log(bad ? `  ${bad} failed` : `  ${cases.length} cases, all as intended`);
process.exit(bad ? 1 : 0);

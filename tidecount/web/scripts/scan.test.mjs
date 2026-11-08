// Tests for Fish Scan's checks and arithmetic. Run with `pnpm test` (plain Node, no extra packages).
import assert from "node:assert/strict";
import test from "node:test";
import { boxBetween, commonOf, cropPixels, fileProblem, filterLibrary, MAX_BYTES, scorePercent, tooSmall } from "../src/scanHelpers.ts";

test("only non-empty JPEG, PNG and WebP pictures up to the limit pass", () => {
  assert.equal(fileProblem({ size: 1000, type: "image/jpeg" }), null);
  assert.equal(fileProblem({ size: 1000, type: "image/png" }), null);
  assert.equal(fileProblem({ size: 1000, type: "image/webp" }), null);
  assert.equal(fileProblem({ size: MAX_BYTES, type: "image/jpeg" }), null);
  assert.match(fileProblem({ size: MAX_BYTES + 1, type: "image/jpeg" }), /larger than 15 MB/);
  assert.match(fileProblem({ size: 1000, type: "image/gif" }), /Only JPEG/);
  assert.match(fileProblem({ size: 1000, type: "image/svg+xml" }), /Only JPEG/);
  assert.match(fileProblem({ size: 0, type: "image/jpeg" }), /empty/);
});

test("a box can be dragged in any direction and stays inside the picture", () => {
  const near = (box, want) => Object.entries(want).forEach(([k, v]) => assert.ok(Math.abs(box[k] - v) < 1e-9, `${k}: ${box[k]} != ${v}`));
  near(boxBetween({ x: 0.2, y: 0.3 }, { x: 0.6, y: 0.9 }), { x: 0.2, y: 0.3, w: 0.4, h: 0.6 });
  near(boxBetween({ x: 0.6, y: 0.9 }, { x: 0.2, y: 0.3 }), { x: 0.2, y: 0.3, w: 0.4, h: 0.6 });
  const out = boxBetween({ x: -0.5, y: 0.5 }, { x: 1.4, y: 1.2 });
  assert.deepEqual(out, { x: 0, y: 0.5, w: 1, h: 0.5 });
});

test("a crop's size is counted in pixels of the original picture", () => {
  assert.deepEqual(cropPixels({ x: 0, y: 0, w: 0.5, h: 0.25 }, 4000, 3000), { w: 2000, h: 750 });
  assert.equal(tooSmall({ x: 0, y: 0, w: 0.5, h: 0.5 }, 4000, 3000), false);
  assert.equal(tooSmall({ x: 0, y: 0, w: 0.003, h: 0.5 }, 4000, 3000), true);   // 12 pixels wide
  assert.equal(tooSmall({ x: 0.5, y: 0.5, w: 0, h: 0 }, 4000, 3000), true);      // a click, no drag
});

test("scores read as percentages, small ones with a decimal", () => {
  assert.equal(scorePercent(0.873), "87%");
  assert.equal(scorePercent(0.1), "10%");
  assert.equal(scorePercent(0.0432), "4.3%");
  assert.equal(scorePercent(0.0004), "0.0%");
  assert.equal(scorePercent(-1), "0.0%");
});

const rows = [
  { species: "Gadus morhua", common: "Atlantic cod" },
  { species: "Salmo salar", common: "Atlantic salmon" },
  { species: "Pungitius pungitius", common: "Pungitius pungitius" },
];
const photo = (id, species, extra = {}) => ({ id, url: `/${id}`, view: "side", caption: "", creator: "A. Diver", license: "CC BY", license_url: "", source: "iNaturalist", source_url: "", verification: "", added_on: "", species, ...extra });

test("the library filter matches species by either name, and hides rejected uploads", () => {
  const photos = [
    photo("a", ["Gadus morhua"]),
    photo("b", ["Salmo salar"], { caption: "Fry in a hatchery" }),
    photo("c", [], { creator: "B. Snorkel", source: "Uploaded to Tideflow" }),
    photo("d", ["Gadus morhua"], { review: "rejected" }),
  ];
  const ids = (q) => filterLibrary(photos, rows, q).map((p) => p.id);
  assert.deepEqual(ids(""), ["a", "b", "c"]);
  assert.deepEqual(ids("cod"), ["a"]);
  assert.deepEqual(ids("gadus"), ["a"]);
  assert.deepEqual(ids("atlantic"), ["a", "b"]);
  assert.deepEqual(ids("hatchery salmon"), ["b"]);
  assert.deepEqual(ids("snorkel"), ["c"]);
  assert.deepEqual(ids("clownfish"), []);
});

test("a species without a common name shows its scientific name", () => {
  assert.equal(commonOf(rows, "Gadus morhua"), "Atlantic cod");
  assert.equal(commonOf(rows, "Nope nope"), "Nope nope");
});

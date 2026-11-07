import assert from "node:assert/strict";
import test from "node:test";
import {
  ALL_YEARS, decadePresets, describeRange, fromPositions, lastPosition, makeScale, normalize, sameRange, tickYears, toPositions, yearInRange,
} from "../src/yearRange.ts";

const scale = makeScale(1950, 2026); // "earlier", then 1950 … 2026: 78 positions, 0 to 77
const LAST = 77;

test("one position per year, plus one for everything earlier", () => {
  assert.deepEqual(scale, { first: 1950, last: 2026 });
  assert.equal(lastPosition(scale), LAST);
});

test("both handles at the ends mean no limit, so older and newer records are all in", () => {
  assert.deepEqual(fromPositions(0, LAST, scale), ALL_YEARS);
  assert.deepEqual(toPositions(ALL_YEARS, scale), [0, LAST]);
});

test("any single years can be picked, such as 2018–2022", () => {
  assert.deepEqual(fromPositions(69, 73, scale), { from: 2018, to: 2022 });
  assert.deepEqual(toPositions({ from: 2018, to: 2022 }, scale), [69, 73]);
  assert.deepEqual(fromPositions(71, 71, scale), { from: 2020, to: 2020 }); // one year
  assert.deepEqual(fromPositions(1, 10, scale), { from: 1950, to: 1959 }); // 1950 itself, without the older records
  assert.deepEqual(fromPositions(0, 10, scale), { from: null, to: 1959 }); // and with them
  assert.deepEqual(fromPositions(0, 0, scale), { from: null, to: 1949 }); // only the records older than the scale
  assert.deepEqual(fromPositions(71, LAST, scale), { from: 2020, to: null });
});

test("handles that cross are put the right way round", () => {
  assert.deepEqual(fromPositions(73, 69, scale), { from: 2018, to: 2022 });
});

test("a range gives back the positions it was made from", () => {
  for (let i = 0; i <= LAST; i++) {
    for (let j = i; j <= LAST; j++) {
      assert.deepEqual(toPositions(fromPositions(i, j, scale), scale), [i, j]);
    }
  }
});

test("years outside the scale are clamped to its open ends", () => {
  assert.deepEqual(normalize({ from: 1900, to: 2100 }, scale), ALL_YEARS);
  assert.deepEqual(normalize({ from: 2013, to: 2017 }, scale), { from: 2013, to: 2017 }); // no snapping any more
});

test("a range in words says which side is open", () => {
  assert.equal(describeRange(ALL_YEARS), "All years");
  assert.equal(describeRange({ from: 2018, to: 2022 }), "2018–2022");
  assert.equal(describeRange({ from: 2020, to: 2020 }), "2020");
  assert.equal(describeRange({ from: 2020, to: null }), "2020–present");
  assert.equal(describeRange({ from: null, to: 2009 }), "up to 2009");
});

test("presets are all years and the three newest decades, in the same form the slider makes", () => {
  const presets = decadePresets(scale, 2026);
  assert.deepEqual(presets.map((p) => p.label), ["All years", "2020s", "2010s", "2000s"]);
  assert.deepEqual(presets[1].range, { from: 2020, to: null });
  assert.deepEqual(presets[2].range, { from: 2010, to: 2019 });
  assert.deepEqual(presets[3].range, { from: 2000, to: 2009 });
  assert.ok(sameRange(presets[2].range, fromPositions(61, 70, scale))); // dragging to 2010–2019 lights the 2010s chip
});

test("a year is in a range unless it falls outside a closed end", () => {
  assert.ok(yearInRange(1800, ALL_YEARS));
  assert.ok(yearInRange(1800, { from: null, to: 1959 }));
  assert.ok(yearInRange(2022, { from: 2018, to: 2022 }) && !yearInRange(2023, { from: 2018, to: 2022 }) && !yearInRange(2017, { from: 2018, to: 2022 }));
  assert.ok(yearInRange(2031, { from: 2020, to: null }));
});

test("ticks fall on round years, leaving the left end for the 'earlier' label", () => {
  assert.deepEqual(tickYears(scale), [1975, 2000, 2025]);
});

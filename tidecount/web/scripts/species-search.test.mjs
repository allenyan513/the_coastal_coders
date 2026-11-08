// Tests for the Identify workspace's species search. Run with `pnpm test` (plain Node, no extra packages).
import assert from "node:assert/strict";
import test from "node:test";
import { fold, rowForName, rowForScientific, searchSpecies } from "../src/speciesSearch.ts";

const row = (species, common) => ({ species, common: common || species, group: "Actinopterygii", inat_obs: 0, obis_nearshore_records: 0, seine_records: 0, confirmed: 0 });
const rows = [
  row("Gadus morhua", "Atlantic cod"),
  row("Gadus ogac", "Greenland cod"),
  row("Melanogrammus aeglefinus", "Haddock"),
  row("Salmo salar", "Atlantic salmon"),
  row("Pungitius pungitius"),  // no common name: the server gives it the scientific name
  row("Myoxocephalus scorpius", "Shorthorn sculpin"),
  row("Anguilla rostrata", "American eel"),
];
const names = (q, limit) => searchSpecies(rows, q, limit).map((r) => r.species);

test("an empty or blank query matches nothing, so the list stays closed", () => {
  assert.deepEqual(names(""), []);
  assert.deepEqual(names("   "), []);
  assert.deepEqual(names("--"), []);
});

test("finds a species by common name, in any case", () => {
  assert.deepEqual(names("HADDOCK"), ["Melanogrammus aeglefinus"]);
  assert.deepEqual(names("sculpin"), ["Myoxocephalus scorpius"]);
});

test("finds a species by scientific name, whole or partial", () => {
  assert.deepEqual(names("salmo salar"), ["Salmo salar"]);
  assert.deepEqual(names("aeglef"), ["Melanogrammus aeglefinus"]);
  assert.deepEqual(names("pungitius"), ["Pungitius pungitius"]);
});

test("a fish with no common name is found by its scientific name only once", () => {
  assert.equal(names("pungitius").length, 1);
});

test("the words can come in any order and the best match comes first", () => {
  assert.deepEqual(names("cod atlantic"), ["Gadus morhua"]);
  assert.equal(names("atlantic")[0], "Gadus morhua");  // "Atlantic cod" before "Atlantic salmon" by name
  assert.deepEqual(names("atlantic"), ["Gadus morhua", "Salmo salar"]);
  assert.deepEqual(names("cod"), ["Gadus morhua", "Gadus ogac"]);
});

test("an exact name beats a name that starts with it", () => {
  const more = [...rows, row("Gadus chalcogrammus", "Cod icefish")];
  assert.equal(searchSpecies([...more, row("X y", "Cod")], "cod")[0].common, "Cod");
});

test("punctuation, accents and extra spaces don't matter", () => {
  assert.deepEqual(names("  atlantic-cod "), ["Gadus morhua"]);
  assert.deepEqual(fold("Café  Sole"), "cafe sole");
});

test("a name that isn't on the list matches nothing, and nothing is guessed", () => {
  assert.deepEqual(names("clownfish"), []);
  assert.deepEqual(names("atlantic clownfish"), []);
});

test("the limit caps the results", () => {
  assert.equal(names("a", 3).length, 3);
  assert.ok(names("a").length > 3);
});

test("a decision's name and a candidate's scientific name both find the row", () => {
  assert.equal(rowForName(rows, "Atlantic cod")?.species, "Gadus morhua");
  assert.equal(rowForName(rows, "Fish, unidentified"), null);
  assert.equal(rowForName(rows, null), null);
  assert.equal(rowForScientific(rows, "Salmo salar")?.common, "Atlantic salmon");
  assert.equal(rowForScientific(rows, "Nope nope"), null);
});

// Regression tests for the species drawer's profile handling. Run with `pnpm test` (plain Node, no extra packages).
import assert from "node:assert/strict";
import test from "node:test";
import { normalizeProfile } from "../src/speciesProfile.ts";

test("a profile from an older server, without names or mentioned_by, still renders", () => {
  // The exact shape the 11:12 server answered with when the Identify tab blanked the app.
  const old = { species: "Tautogolabrus adspersus", curated: true, taxon: null, images: [], profile: { summary: "A wrasse.", features: ["Thick lips"], similar: [], sources: [], expert_reviewed: false } };
  const p = normalizeProfile(old, "Tautogolabrus adspersus");
  assert.deepEqual(p.mentioned_by, []);
  assert.equal(p.names, null);
  assert.equal(p.mentioned_by.filter(() => true).length, 0); // what Identify does first
});

test("a species nobody has written notes for gets an empty profile, not a crash", () => {
  const p = normalizeProfile({ species: "Gadus ogac", curated: false, taxon: null, profile: null, images: [], names: null, mentioned_by: [] }, "Gadus ogac");
  assert.equal(p.profile, null);
  assert.deepEqual(p.images, []);
});

test("missing lists and broken look-alike entries are dropped", () => {
  const p = normalizeProfile(
    {
      species: "Gadus morhua",
      profile: { summary: null, similar: [{ note: "no name" }, { species: "Gadus morhua", note: "itself" }, { species: "Melanogrammus aeglefinus" }, null] },
      names: { status: "accepted", source: "WoRMS", aphia_id: 126436, accepted_name: "Gadus morhua" },
      images: [{ id: "x" }, { id: "y", url: "https://example.org/y.jpg" }],
    },
    "Gadus morhua",
  );
  assert.equal(p.profile.summary, "");
  assert.deepEqual(p.profile.features, []);
  assert.deepEqual(p.profile.sources, []);
  assert.deepEqual(p.profile.similar, [{ species: "Melanogrammus aeglefinus", note: "" }]);
  assert.deepEqual(p.names.synonyms, []);
  assert.deepEqual(p.images.map((i) => i.id), ["y"]);
});

test("nothing at all still gives a usable empty entry", () => {
  const p = normalizeProfile(null, "Mola mola");
  assert.equal(p.species, "Mola mola");
  assert.equal(p.curated, false);
  assert.equal(p.profile, null);
});

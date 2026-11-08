// Regression tests for the species drawer's profile handling. Run with `pnpm test` (plain Node, no extra packages).
import assert from "node:assert/strict";
import test from "node:test";
import { badgeText, environmentLabels, normalizeConservation, normalizeProfile, shortAuthority, splitFirstSentence, statusSummary, tabFromParam } from "../src/speciesProfile.ts";

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

test("a verified conservation status comes through with its sources", () => {
  const p = normalizeProfile({
    species: "Coregonus huntsmani",
    conservation: { kind: "at_risk", badge: "Endangered", verified_on: "2026-11-07", statuses: [{ authority: "COSEWIC", status: "Endangered" }, { status: "no authority" }], threats: ["Predatory fishes", ""], sources: [{ label: "COSEWIC 2022", url: "https://example.org/cosewic" }, { url: "http://insecure.example" }] },
  }, "Coregonus huntsmani");
  assert.equal(p.conservation.badge, "Endangered");
  assert.deepEqual(p.conservation.statuses.map((s) => s.authority), ["COSEWIC"]);
  assert.deepEqual(p.conservation.threats, ["Predatory fishes"]);
  assert.deepEqual(p.conservation.sources.map((s) => s.url), ["https://example.org/cosewic"]);
});

test("a population-specific status is labelled as such and never as the whole species", () => {
  const c = normalizeConservation({
    kind: "at_risk", badge: "Endangered", verified_on: "2026-11-07", scope: "species", sources: [{ url: "https://example.org" }],
    statuses: [
      { authority: "COSEWIC", status: "Endangered", population: "Inner Bay of Fundy population" },
      { authority: "Species at Risk Act (Canada)", status: "Not listed", source: "http://insecure.example" },
    ],
  });
  assert.equal(c.scope, "populations"); // derived, even if the entry claims otherwise
  assert.equal(badgeText(c), "Endangered · some populations");
  assert.deepEqual(c.statuses.map((s) => s.type), ["assessment", "legal"]);
  assert.equal(c.statuses[1].source, "");
  assert.match(statusSummary(c), /Differs by population/);
});

test("a species-wide summary names each body's own result instead of joining them", () => {
  const c = normalizeConservation({
    kind: "at_risk", badge: "Threatened (COSEWIC)", verified_on: "2026-11-07", sources: [{ url: "https://example.org" }],
    statuses: [{ authority: "COSEWIC", status: "Threatened" }, { authority: "Species at Risk Act (Canada)", status: "Not listed" }],
  });
  assert.equal(c.scope, "species");
  assert.equal(badgeText(c), "Threatened (COSEWIC)");
  assert.equal(statusSummary(c), "COSEWIC: Threatened · SARA: Not listed");
});

test("an unknown or unsourced status stays unknown, never 'safe'", () => {
  assert.equal(normalizeProfile({ species: "Gadus morhua" }, "Gadus morhua").conservation, null);
  assert.equal(normalizeConservation({ kind: "at_risk", badge: "Endangered", verified_on: "2026-01-01", sources: [] }), null);
  assert.equal(normalizeConservation({ kind: "at_risk", badge: "Endangered", sources: [{ url: "https://x.org" }] }), null);
  assert.equal(normalizeConservation({ kind: "secure", badge: "Not at risk", verified_on: "2026-01-01", sources: [{ url: "https://x.org" }] }), null);
});

test("old tab links go to the new sections", () => {
  assert.equal(tabFromParam("photos"), "overview");
  assert.equal(tabFromParam("identify"), "overview");
  assert.equal(tabFromParam("map"), "map");
  assert.equal(tabFromParam("details"), "details");
  assert.equal(tabFromParam(null), "overview");
  assert.equal(tabFromParam("nonsense"), "overview");
});

test("an unlisted look-alike keeps its common name; historical and current range stay apart", () => {
  const p = normalizeProfile({
    species: "Coregonus huntsmani",
    profile: { summary: "x", similar: [{ species: "Coregonus clupeaformis", common: "Lake Whitefish", note: "Fewer scales" }, { species: "Salmo salar", common: 7 }] },
    conservation: { kind: "at_risk", badge: "Endangered", verified_on: "2026-11-07", historical_range: "Tusket and Petite", current_range: "Three Petite Rivière lakes", sources: [{ url: "https://example.org" }] },
  }, "Coregonus huntsmani");
  assert.equal(p.profile.similar[0].common, "Lake Whitefish");
  assert.equal("common" in p.profile.similar[1], false);
  assert.equal(p.conservation.historical_range, "Tusket and Petite");
  assert.equal(p.conservation.current_range, "Three Petite Rivière lakes");
  assert.equal(p.conservation.range_note, "");
});

test("environment labels are plain words, only from WoRMS's own flags", () => {
  assert.deepEqual(environmentLabels({ source: "WoRMS", is_marine: true, is_brackish: false, is_freshwater: false }), ["Saltwater"]);
  assert.deepEqual(environmentLabels({ source: "WoRMS", is_marine: true, is_brackish: true, is_freshwater: true }), ["Saltwater", "Brackish", "Freshwater"]);
  assert.deepEqual(environmentLabels({ source: "GBIF", is_marine: true }), []); // not checked against WoRMS: nothing claimed
  assert.deepEqual(environmentLabels(null), []);
});

test("assessment chips use short names, and a comparison splits after its first sentence", () => {
  assert.equal(shortAuthority("Species at Risk Act (Canada)"), "SARA");
  assert.equal(shortAuthority("Nova Scotia Endangered Species Act"), "Nova Scotia");
  assert.equal(shortAuthority("COSEWIC"), "COSEWIC");
  assert.deepEqual(splitFirstSentence("Fewer scales (dark brown in some inland lakes). It is far more common."), ["Fewer scales (dark brown in some inland lakes).", "It is far more common."]);
  assert.deepEqual(splitFirstSentence("One sentence only."), ["One sentence only.", ""]);
  assert.deepEqual(splitFirstSentence("Has 109 to 124 scales, against 90 to 100. Atlantic Whitefish has no spots."), ["Has 109 to 124 scales, against 90 to 100.", "Atlantic Whitefish has no spots."]);
});

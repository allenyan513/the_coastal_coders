"""Finds reference photographs for the species encyclopedia and checks the manifest the app serves.

Run from tidecount/server (standard library only; Pillow is used for contact sheets if installed):

    uv run python ../ml/species_media.py resolve "Gadus morhua" "Clupea harengus"
    uv run python ../ml/species_media.py candidates "Gadus morhua"        # downloads thumbnails + a numbered contact sheet
    uv run python ../ml/species_media.py check                            # validates server/tidecount/species_media.json

The flow keeps a person in the loop on purpose:

1. `resolve` matches the scientific name against the iNaturalist and GBIF taxonomies and refuses
   anything that is not an exact, accepted species name. It prints the ids the manifest stores.
2. `candidates` collects only openly licensed images (CC0, CC BY, CC BY-SA, public domain):
   - iNaturalist research-grade observations of exactly that taxon id, best-voted first
   - Wikimedia Commons files in the category named exactly like the species
   Everything lands in data/species_media/<species>/ with a numbered contact sheet.
3. A person looks at the sheet, rejects wrong species, bad crops and look-alikes, tags each kept
   image (side / underwater / in_hand / illustration) and records the keepers:
       uv run python ../ml/species_media.py add "Gadus morhua" 0:side 14:underwater
   (`show "Gadus morhua"` lists the numbered candidates with creator, licence and place.)
4. `check` fails on a licence that isn't on the allow-list, a missing creator or source link, a
   species that is not in species.csv, or a name that is not the one the manifest resolved. It
   also checks species_profiles.json: every "easily confused with" entry must be on the list.

Scientific names:

    uv run python ../ml/species_media.py taxonomy        # all 182 names against WoRMS, then GBIF

`taxonomy` writes server/tidecount/species_taxonomy.json: the WoRMS AphiaID (which the OBIS map
uses), the WoRMS status, the accepted name when the list uses a synonym, and known synonyms. It
never edits species.csv, so the BioCLIP candidates stay exactly as they are. Names WoRMS doesn't
know, mostly freshwater fish, fall back to the GBIF backbone and are marked as such.

Nothing here downloads images into the app. The manifest stores the original URLs, creators and
licences, and the browser loads the images from their source.
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "server" / "tidecount" / "species_media.json"
PROFILES = ROOT / "server" / "tidecount" / "species_profiles.json"
TAXONOMY = ROOT / "server" / "tidecount" / "species_taxonomy.json"
SPECIES_CSV = ROOT / "server" / "tidecount" / "species.csv"
WORMS = "https://www.marinespecies.org/rest/"
WORK = ROOT / "data" / "species_media"
UA = "TideCount-species-media/0.1 (hackathon research tool; contact: repo owner)"

# The only licences the app will show. Non-commercial and no-derivatives licences are left out,
# because a public demo is not clearly non-commercial and the drawer crops images to fit.
ALLOWED = {
    "cc0": ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "cc-by": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "cc-by-sa": ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    "pd": ("Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
}
VIEWS = {"side", "underwater", "in_hand", "illustration", "other"}


def get_json(url: str, params: dict | list | None = None, pause: float = 1.1):
    """GET and parse JSON. WoRMS answers 204 with no body for "nothing found", which comes back as None."""
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        time.sleep(pause)  # iNaturalist asks for at most about one request a second
        raw = r.read()
        return json.loads(raw) if raw else None


def get_bytes(url: str) -> bytes:
    """Wikimedia answers 429 to quick bursts, so it gets a pause before each file and a retry."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        time.sleep(2.0 if "wikimedia.org" in url else 0.3)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError("unreachable")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def listed_species() -> set[str]:
    with open(SPECIES_CSV, newline="", encoding="utf-8") as f:
        return {row["species"] for row in csv.DictReader(f)}


# --- names ------------------------------------------------------------------------------------

def resolve(name: str) -> dict:
    """Exact, accepted species match in iNaturalist and GBIF, or an error saying why not."""
    inat = get_json("https://api.inaturalist.org/v1/taxa", {"q": name, "rank": "species", "per_page": 10, "is_active": "true"})
    exact = [t for t in inat["results"] if t["name"] == name]
    if not exact:  # the plain search can bury a species under fuzzy matches; autocomplete ranks by name prefix
        auto = get_json("https://api.inaturalist.org/v1/taxa/autocomplete", {"q": name, "rank": "species", "per_page": 10, "is_active": "true"})
        exact = [t for t in auto["results"] if t["name"] == name]
    if not exact:
        raise ValueError(f"{name}: no exact active species match on iNaturalist (maybe a synonym; got {[t['name'] for t in inat['results']][:4]})")
    taxon = exact[0]
    gbif = get_json("https://api.gbif.org/v1/species/match", {"name": name, "kingdom": "Animalia", "strict": "true"})
    if gbif.get("matchType") != "EXACT" or gbif.get("status") != "ACCEPTED" or gbif.get("rank") != "SPECIES":
        raise ValueError(f"{name}: GBIF does not list it as an accepted species (matchType={gbif.get('matchType')}, status={gbif.get('status')}, accepted={gbif.get('species')})")
    worms = worms_exact([name]).get(name)
    if worms and worms["status"] != "accepted":
        raise ValueError(f"{name}: WoRMS lists it as {worms['status']}; the accepted name is {worms['accepted_name']}")
    return {
        "scientific_name": name,
        "inat_taxon_id": taxon["id"],
        "inat_common_name": taxon.get("preferred_common_name", ""),
        "gbif_key": gbif["usageKey"],
        "aphia_id": worms["aphia_id"] if worms else None,
        "authority": (worms or {}).get("authority") or (gbif.get("scientificName") or "").replace(name, "").strip(),
        "family": (worms or {}).get("family") or gbif.get("family", ""),
        "resolved_on": time.strftime("%Y-%m-%d"),
    }


def worms_exact(names: list[str]) -> dict:
    """Exact WoRMS records for up to 50 names at once, keyed by the name asked for."""
    params = [("scientificnames[]", n) for n in names] + [("like", "false"), ("marine_only", "false")]
    batches = get_json(WORMS + "AphiaRecordsByNames", params, pause=0.5) or []
    out = {}
    for name, records in zip(names, batches):
        # A name can match several records (a homonym, or an old record). Prefer the accepted species.
        species = [r for r in (records or []) if r.get("rank") == "Species" and r.get("scientificname") == name]
        if not species:
            continue
        rec = next((r for r in species if r["status"] == "accepted"), species[0])
        out[name] = {
            "aphia_id": rec["AphiaID"],
            "status": rec["status"],
            "unaccept_reason": rec.get("unacceptreason"),
            "accepted_name": rec.get("valid_name"),
            "accepted_aphia_id": rec.get("valid_AphiaID"),
            "authority": rec.get("authority") or "",
            "family": rec.get("family") or "",
            "url": rec.get("url"),
            "is_marine": bool(rec.get("isMarine")), "is_brackish": bool(rec.get("isBrackish")),
            "is_freshwater": bool(rec.get("isFreshwater")),
        }
    return out


def cmd_taxonomy(_args) -> None:
    """Every name on the list against WoRMS; GBIF for the ones WoRMS doesn't know."""
    names = sorted(listed_species())
    found = {}
    for i in range(0, len(names), 50):
        found.update(worms_exact(names[i:i + 50]))
    out, report = {}, {"accepted": 0, "synonym": 0, "gbif_only": 0, "unmatched": 0}
    for name in names:
        rec = found.get(name)
        if rec:
            target = rec["accepted_aphia_id"] or rec["aphia_id"]
            syn = get_json(WORMS + f"AphiaSynonymsByAphiaID/{target}", pause=0.3) or []
            rec["synonyms"] = sorted({s["scientificname"] for s in syn if s.get("scientificname") and s["scientificname"] != name})[:20]
            rec["source"] = "WoRMS"
            if rec["status"] == "accepted":
                report["accepted"] += 1
            else:
                report["synonym"] += 1
                print(f"  {name}: WoRMS says {rec['status']}, accepted name {rec['accepted_name']}")
            out[name] = rec
            continue
        gbif = get_json("https://api.gbif.org/v1/species/match", {"name": name, "kingdom": "Animalia", "strict": "true"}, pause=0.3) or {}
        if gbif.get("matchType") == "EXACT":
            out[name] = {
                "source": "GBIF", "aphia_id": None, "gbif_key": gbif.get("usageKey"),
                "status": (gbif.get("status") or "").lower(), "accepted_name": gbif.get("species"),
                "authority": (gbif.get("scientificName") or "").replace(name, "").strip(),
                "family": gbif.get("family", ""), "url": f"https://www.gbif.org/species/{gbif.get('usageKey')}",
                "synonyms": [],
            }
            report["gbif_only"] += 1
            print(f"  {name}: not in WoRMS, GBIF {out[name]['status']}")
        else:
            out[name] = {"source": None, "aphia_id": None, "status": "unmatched", "accepted_name": None, "synonyms": []}
            report["unmatched"] += 1
            print(f"  {name}: no exact match in WoRMS or GBIF")
    TAXONOMY.write_text(json.dumps({"version": 1, "checked_on": time.strftime("%Y-%m-%d"), "species": out}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(names)} names: {report}")


# --- candidates -------------------------------------------------------------------------------

def inat_license(code: str | None) -> tuple[str, str] | None:
    return ALLOWED.get(code or "")


# Atlantic Canada, roughly: Nova Scotia, New Brunswick, PEI, Newfoundland, the Gulf of St. Lawrence.
ATLANTIC_CANADA = {"swlat": 43.0, "swlng": -67.5, "nelat": 52.0, "nelng": -52.0}


def inat_candidates(taxon_id: int, limit: int) -> list[dict]:
    """Atlantic Canada sightings first, because a regional fish can look different elsewhere, then the best worldwide."""
    out, seen = [], set()
    base_params = {
        "taxon_id": taxon_id, "quality_grade": "research", "photos": "true",
        "photo_license": "cc0,cc-by,cc-by-sa", "order_by": "votes", "order": "desc", "per_page": 40,
    }
    results = []
    for extra in (ATLANTIC_CANADA, {}):
        results += [dict(o, regional=bool(extra)) for o in get_json("https://api.inaturalist.org/v1/observations", {**base_params, **extra})["results"]]
    per_observer: dict[str, int] = {}
    for obs in results:
        if (obs.get("taxon") or {}).get("id") != taxon_id:
            continue  # research grade at a coarser or finer rank is not an exact match
        login = obs["user"]["login"]
        if per_observer.get(login, 0) >= 2:
            continue  # a few prolific observers would otherwise fill the sheet with one fish and one camera
        # The lead photo is the one the observer chose; the second often shows the other side or a close-up.
        for photo in obs["photos"][:2]:
            lic = inat_license(photo.get("license_code"))
            if not lic or photo["id"] in seen:
                continue
            dims = photo.get("original_dimensions") or {}
            if dims and max(dims.get("width", 0), dims.get("height", 0)) < 800:
                continue  # too small to show a fin ray or a lateral line
            seen.add(photo["id"])
            per_observer[login] = per_observer.get(login, 0) + 1
            base, filename = photo["url"].rsplit("/", 1)
            ext = filename.split(".")[-1].split("?")[0]  # not always jpg, and a wrong extension is a 404
            user = obs["user"]
            out.append({
                "source": "iNaturalist",
                "source_url": f"https://www.inaturalist.org/observations/{obs['id']}",
                "image_url": f"{base}/large.{ext}",
                "thumb_url": f"{base}/medium.{ext}",
                "creator": user.get("name") or user["login"],
                "license": lic[0], "license_url": lic[1],
                "place": obs.get("place_guess") or "",
                "observed_on": obs.get("observed_on") or "",
                "agreements": obs.get("num_identification_agreements", 0),
                "faves": obs.get("faves_count", 0),
                "iconic": "",
                "atlantic_canada": obs["regional"],
            })
        if len(out) >= limit:
            break
    return out


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def commons_license(meta: dict) -> tuple[str, str] | None:
    short = strip_html(meta.get("LicenseShortName", {}).get("value", "")).lower()
    url = meta.get("LicenseUrl", {}).get("value", "")
    if short.startswith("cc0") or "public domain" in short or short == "pd" or short.startswith("pd-"):
        return ALLOWED["pd" if "cc0" not in short else "cc0"]
    m = re.match(r"cc[ -]by(-sa)? (\d\.\d)", short)
    if m:
        kind = "CC BY-SA" if m.group(1) else "CC BY"
        return (f"{kind} {m.group(2)}", url or f"https://creativecommons.org/licenses/{'by-sa' if m.group(1) else 'by'}/{m.group(2)}/")
    return None


# Species categories on Commons also hold food, fishing scenes, stamps and anatomy. These words in a
# title or description almost always mean the file isn't a whole, recognisable fish.
COMMONS_NOISE = re.compile(
    r"\b(?:fillet|filet|tongue|dish|cooked|fried|smoked|dried|salted|market|food|recipe|plate|fishery|fisheries|"
    r"trawl|boat|schooner|skeleton|skull|otolith|stamp|coin|logo|map|distribution|range|catch|bucket|"
    r"splitting|haddie|bacall|torsk|stockfish|lutefisk|egg|larva|parasite|dissect|anatomy|label)",
    re.IGNORECASE,
)


def commons_candidates(name: str, limit: int) -> list[dict]:
    # 500 and 1280 are standard Wikimedia thumbnail widths, which come from cache and don't get rate-limited.
    data = get_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:{name}",
        "gcmtype": "file", "gcmlimit": 100, "prop": "imageinfo", "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 500, "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|ImageDescription|Credit",
    }) or {}
    out = []
    for page in data.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if max(info.get("width", 0), info.get("height", 0)) < 800:
            continue
        desc = strip_html(info.get("extmetadata", {}).get("ImageDescription", {}).get("value", ""))
        if COMMONS_NOISE.search(page["title"]) or COMMONS_NOISE.search(desc):
            continue
        meta = info.get("extmetadata", {})
        lic = commons_license(meta)
        if not lic:
            continue
        thumb = (info.get("thumburl") or info["url"]).split("?")[0]
        large = re.sub(r"/500px-", "/1280px-", thumb) if info.get("width", 0) > 1280 else info["url"]
        out.append({
            "source": "Wikimedia Commons",
            "source_url": info["descriptionurl"],
            "image_url": large,
            "thumb_url": thumb,
            "creator": strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown",
            "license": lic[0], "license_url": lic[1],
            "title": page["title"], "description": strip_html(meta.get("ImageDescription", {}).get("value", ""))[:200],
            "iconic": "",
        })
    # Category pages are noisy (drawings of fishing scenes, skeletons), so keep the batch small.
    return out[:limit]


def sheet(folder: Path, cands: list[dict]) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  Pillow not installed, skipping the contact sheet")
        return
    tile, cols = 320, 4
    rows = (len(cands) + cols - 1) // cols
    img = Image.new("RGB", (cols * tile, rows * (tile * 3 // 4 + 4)), "white")
    d = ImageDraw.Draw(img)
    for i, c in enumerate(cands):
        p = folder / f"{i:02d}.jpg"
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        im.thumbnail((tile - 4, tile * 3 // 4))
        x, y = (i % cols) * tile + 2, (i // cols) * (tile * 3 // 4 + 4)
        img.paste(im, (x, y))
        tag = f"{i} {'iNat' if c['source'] == 'iNaturalist' else 'Wiki'}{' CA' if c.get('atlantic_canada') else ''}"
        d.rectangle([x, y, x + 8 + 7 * len(tag), y + 20], fill="black")
        d.text((x + 4, y + 4), tag, fill="white")
    img.save(folder / "sheet.jpg", quality=85)


def cmd_candidates(args) -> None:
    for name in args.species:
        folder = WORK / slug(name)
        if (folder / "sheet.jpg").exists() and not args.force:
            print(f"{name}: already collected, skipping (use --force to collect again)")
            continue
        try:
            ident = resolve(name)
        except ValueError as e:
            print(f"SKIP {e}")  # a name we can't match exactly gets no photos, rather than possibly wrong ones
            continue
        folder.mkdir(parents=True, exist_ok=True)
        cands = inat_candidates(ident["inat_taxon_id"], args.limit) + commons_candidates(name, 8)
        for i, c in enumerate(cands):
            try:
                (folder / f"{i:02d}.jpg").write_bytes(get_bytes(c["thumb_url"]))
            except Exception as e:  # one dead link shouldn't stop the batch
                print(f"  {i}: download failed: {e}")
        (folder / "candidates.json").write_text(json.dumps({"taxon": ident, "candidates": cands}, indent=1), encoding="utf-8")
        sheet(folder, cands)
        print(f"{name}: {len(cands)} candidates -> {folder}")


def cmd_show(args) -> None:
    """One line per candidate, numbered like the contact sheet."""
    for name in args.species:
        data = json.loads((WORK / slug(name) / "candidates.json").read_text(encoding="utf-8"))
        print(f"== {name} (iNat {data['taxon']['inat_taxon_id']})")
        for i, c in enumerate(data["candidates"]):
            extra = c.get("place") or c.get("description", "")[:60]
            ca = "CA" if c.get("atlantic_canada") else "  "
            print(f"{i:2d} {c['source'][:4]} {ca} {c['license']:<14} {c['creator'][:24]:<24} {extra}")


def cmd_add(args) -> None:
    """Record the candidates a person kept: `add "Gadus morhua" 0:side 14:underwater:"Juvenile on rock"`.

    Replaces that species' images in the manifest, keeps the taxon ids from `resolve`, and writes
    how each image was checked. Nobody should run this before looking at the contact sheet.
    """
    data = json.loads((WORK / slug(args.species) / "candidates.json").read_text(encoding="utf-8"))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"version": 1, "species": {}}
    images = []
    for pick in args.picks:
        idx, view, *rest = pick.split(":", 2)
        c = data["candidates"][int(idx)]
        if view not in VIEWS:
            raise SystemExit(f"view must be one of {sorted(VIEWS)}, got {view!r}")
        key = c["source_url"].rstrip("/").rsplit("/", 1)[-1]
        url = c["image_url"].split("?")[0]
        thumb = c["thumb_url"].split("?")[0]
        if "/thumb/" in thumb:
            thumb = re.sub(r"/\d+px-", "/500px-", thumb)
            url = re.sub(r"/\d+px-", "/960px-", url)
        if c["source"] == "iNaturalist":
            how = (f"iNaturalist research-grade observation of taxon {data['taxon']['inat_taxon_id']} with {c['agreements']} agreeing identification(s). "
                   "Subject and view checked by eye; not reviewed by a fish biologist.")
            caption = rest[0] if rest else ""
            place = c.get("place", "")
        else:
            how = ("Wikimedia Commons file filed under the accepted species name. Subject and view checked by eye; "
                   "not reviewed by a fish biologist." + (" Historical illustration, so colours and proportions may differ from a live fish." if view == "illustration" else ""))
            caption = rest[0] if rest else c.get("description", "")
            place = ""
        images.append({
            "id": f"{slug(args.species)}-{key}"[:80],
            "url": url, "thumb_url": thumb, "view": view, "caption": caption,
            "creator": c["creator"], "license": c["license"], "license_url": c["license_url"],
            "source": c["source"], "source_url": c["source_url"], "place": place,
            "verification": how, "added_on": time.strftime("%Y-%m-%d"),
        })
    manifest["species"][args.species] = {"taxon": data["taxon"], "images": images}
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.species}: {len(images)} images recorded")


def cmd_resolve(args) -> None:
    for name in args.species:
        try:
            print(json.dumps(resolve(name)))
        except Exception as e:
            print(f"FAIL {e}")


# --- manifest check ---------------------------------------------------------------------------

def check_inat_observations(data: dict) -> list[str]:
    """Each iNaturalist photo's observation must still exist, be research grade and name the same
    taxon. Identifications change after curation, so this catches a photo whose fish was renamed."""
    wanted = {}
    for name, entry in data["species"].items():
        for img in entry["images"]:
            m = re.match(r"https://www\.inaturalist\.org/observations/(\d+)", img.get("source_url", ""))
            if m:
                wanted[int(m.group(1))] = (name, entry["taxon"]["inat_taxon_id"])
    problems, ids = [], sorted(wanted)
    print(f"checking {len(ids)} iNaturalist observations through the API…", flush=True)
    for i in range(0, len(ids), 100):
        batch = ids[i:i + 100]
        found = {o["id"]: o for o in (get_json(f"https://api.inaturalist.org/v1/observations/{','.join(map(str, batch))}", {"per_page": 100}) or {}).get("results", [])}
        for oid in batch:
            name, taxon = wanted[oid]
            obs = found.get(oid)
            if not obs:
                problems.append(f"{name}: iNaturalist observation {oid} is gone or hidden")
            elif (obs.get("taxon") or {}).get("id") != taxon:
                problems.append(f"{name}: iNaturalist observation {oid} is now identified as {(obs.get('taxon') or {}).get('name')}")
            elif obs.get("quality_grade") != "research":
                problems.append(f"{name}: iNaturalist observation {oid} is no longer research grade ({obs.get('quality_grade')})")
    return problems


def link_status(url: str) -> int | str:
    """HTTP status of a GET (some hosts refuse HEAD), reading only the first bytes."""
    time.sleep(2.0 if "wikimedia.org" in url else 0.3)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return 200 if r.status in (200, 206) else r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # DNS, timeout
        return e.__class__.__name__

def cmd_check(_args) -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    listed = listed_species()
    problems, n_images = [], 0
    lic_ok = {v[0] for v in ALLOWED.values()} | {"CC BY 3.0", "CC BY-SA 3.0", "CC BY 2.0", "CC BY-SA 2.0", "CC BY 2.5", "CC BY-SA 2.5"}
    for name, entry in data["species"].items():
        if name not in listed:
            problems.append(f"{name}: not in species.csv")
        if entry["taxon"]["scientific_name"] != name:
            problems.append(f"{name}: taxon block names {entry['taxon']['scientific_name']}")
        for img in entry["images"]:
            n_images += 1
            where = f"{name} image {img.get('id')}"
            for key in ("id", "url", "view", "creator", "license", "license_url", "source", "source_url", "verification"):
                if not img.get(key):
                    problems.append(f"{where}: missing {key}")
            if img.get("license") not in lic_ok:
                problems.append(f"{where}: licence {img.get('license')!r} is not allowed")
            if img.get("view") not in VIEWS:
                problems.append(f"{where}: unknown view {img.get('view')!r}")
            if not str(img.get("url", "")).startswith("https://"):
                problems.append(f"{where}: url is not https")
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["species"] if PROFILES.exists() else {}
    for name, p in profiles.items():
        if name not in listed:
            problems.append(f"profile {name}: not in species.csv")
        for key in ("summary", "features", "sources"):
            if not p.get(key):
                problems.append(f"profile {name}: missing {key}")
        for s in p.get("similar", []):
            # An entry with a "common" name is a reference-only look-alike (e.g. Lake Whitefish):
            # it is shown as plain text, so it needn't be on the list.
            if s["species"] not in listed and not s.get("common"):
                problems.append(f"profile {name}: similar species {s['species']} is not in species.csv, so the drawer can't link it")
            if s["species"] == name:
                problems.append(f"profile {name}: lists itself as similar")
        for src in p.get("sources", []):
            if not src.get("url", "").startswith("https://"):
                problems.append(f"profile {name}: source {src.get('label')} has no https link")
    taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))["species"] if TAXONOMY.exists() else {}
    for name in set(data["species"]) | set(profiles):
        t = taxonomy.get(name)
        if t and t.get("status") not in ("accepted", None):
            problems.append(f"{name}: {t.get('source')} lists it as {t.get('status')} (accepted: {t.get('accepted_name')})")
    if getattr(_args, "links", False):
        problems += check_inat_observations(data)
        urls = {img[k] for e in data["species"].values() for img in e["images"] for k in ("url", "thumb_url", "source_url") if img.get(k)}
        urls |= {s["url"] for p in profiles.values() for s in p.get("sources", [])}
        # iNaturalist's website answers scripts with 403, so its pages are checked through the API above.
        urls = {u for u in urls if not u.startswith("https://www.inaturalist.org/observations/")}
        print(f"checking {len(urls)} links…", flush=True)
        for i, url in enumerate(sorted(urls), 1):
            status = link_status(url)
            if status != 200:
                problems.append(f"link {status}: {url}")
                print(f"  {status}: {url}", flush=True)
            if i % 25 == 0:
                print(f"  {i}/{len(urls)}", flush=True)
    for p in problems:
        print("PROBLEM", p)
    print(f"{len(data['species'])} species with photos, {n_images} images, {len(profiles)} profiles, {len(problems)} problems")
    return 1 if problems else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # creators and places are not always ASCII, and Windows consoles aren't UTF-8
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve"); r.add_argument("species", nargs="+"); r.set_defaults(fn=cmd_resolve)
    c = sub.add_parser("candidates"); c.add_argument("species", nargs="+"); c.add_argument("--limit", type=int, default=10); c.add_argument("--force", action="store_true"); c.set_defaults(fn=cmd_candidates)
    s = sub.add_parser("show"); s.add_argument("species", nargs="+"); s.set_defaults(fn=cmd_show)
    a = sub.add_parser("add"); a.add_argument("species"); a.add_argument("picks", nargs="+", metavar="INDEX:VIEW[:CAPTION]"); a.set_defaults(fn=cmd_add)
    t = sub.add_parser("taxonomy"); t.set_defaults(fn=cmd_taxonomy)
    k = sub.add_parser("check"); k.add_argument("--links", action="store_true", help="also fetch every image and source link"); k.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())

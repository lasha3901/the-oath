#!/usr/bin/env python3
"""Collect current civics answers from official sources only.

Sources (the same ones USCIS points to on its Test Updates page):
  - USCIS "Check for Test Updates": President, Vice President, Speaker, Chief Justice,
    number of justices (2008), President's party (2008); accepted forms verbatim.
  - senate.gov member list (XML): each state's two U.S. Senators.
  - USA.gov state and territory pages: each Governor.

Usage:
  collect_dynamic_answers.py --out api/v1/dynamic_answers.json
      Writes a new file with reviewStatus "proposed". A person must review it and set
      reviewStatus to "approved" before publishing (never auto-published).
  collect_dynamic_answers.py --check api/v1/dynamic_answers.json --report report.md
      Exit 0: official sources match the published answers.
      Exit 1: something changed, or a source could not be parsed (report explains).
      Used by the scheduled GitHub Action, which opens an issue instead of publishing.

Standard library only.
"""
import argparse, datetime, html, json, re, sys, time, urllib.request
import xml.etree.ElementTree as ET

USCIS_URL = "https://www.uscis.gov/citizenship/testupdates"
SENATE_URL = "https://www.senate.gov/general/contact_information/senators_cfm.xml"
USAGOV_URL = "https://www.usa.gov/states/{slug}"

# Official question numbers → answer keys (from the USCIS question lists).
NATIONAL_KEYS = {
    "2008": {28: "president", 29: "vicePresident", 39: "supremeCourtJusticeCount", 40: "chiefJustice",
             46: "presidentParty", 47: "speakerOfTheHouse"},
    "2025": {30: "speakerOfTheHouse", 38: "president", 39: "vicePresident", 57: "chiefJustice"},
}
SECTION_TITLES = {"2008": "Civics Test (2008 Version) Updates",
                  "2025": "Civics Test (2025 Naturalization Civics Test) Updates"}

# USPS code → (name, kind) for the 50 states, DC and inhabited territories.
JURISDICTIONS = None  # loaded from the app's jurisdictions.json when available, else from senate data.


class SourceError(Exception):
    pass


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "TheOath-civics-check/1.0 (+github.com/lasha3901/the-oath)"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as error:  # noqa: BLE001
            if attempt == retries - 1:
                raise SourceError(f"{url}: {error}")
            time.sleep(2 * (attempt + 1))


def text_lines(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_uscis(page):
    lines = text_lines(page)
    national = {}
    reviewed = next((lines[i + 1] for i, l in enumerate(lines) if l.startswith("Last Reviewed/Updated")), None)
    for version, title in SECTION_TITLES.items():
        try:
            start = lines.index(title)
        except ValueError:
            raise SourceError(f"USCIS page: section '{title}' not found")
        end = next((i for i in range(start + 1, len(lines)) if lines[i] in SECTION_TITLES.values() or lines[i].startswith("Last Reviewed")), len(lines))
        section = lines[start + 1:end]
        answers, number = {}, None
        for line in section:
            match = re.match(r"^(\d{1,3})\.\s", line)
            if match:
                number = int(match.group(1))
                answers[number] = []
            elif number is not None and line not in ("*", "?"):
                answers[number].append(line)
        national[version] = {}
        for question, key in NATIONAL_KEYS[version].items():
            values = answers.get(question)
            if not values or any(v.startswith("Answers will vary") or v.startswith("Visit ") for v in values):
                raise SourceError(f"USCIS page: no fixed answers for {version} question {question}")
            national[version][key] = values
    return national, reviewed


def parse_senate(xml_text):
    root = ET.fromstring(xml_text)
    senators = {}
    for member in root.findall("member"):
        state = member.findtext("state")
        name = f"{member.findtext('first_name').strip()} {member.findtext('last_name').strip()}"
        senators.setdefault(state, []).append(name)
    if len(senators) != 50 or any(len(v) != 2 for v in senators.values()):
        raise SourceError(f"senate.gov: expected 2 senators for each of 50 states, got {[(k, len(v)) for k, v in senators.items() if len(v) != 2]} across {len(senators)} states")
    return {state: sorted(names) for state, names in senators.items()}


def parse_governor(page):
    lines = text_lines(page)
    for i, line in enumerate(lines):
        if line == "Governor" and i + 1 < len(lines):
            follow = lines[i + 1]
            for prefix in ("Governor ", "Contact Governor "):
                if follow.startswith(prefix):
                    return follow[len(prefix):].strip()
    return None


def load_jurisdictions(path):
    with open(path, encoding="utf-8") as handle:
        return [(j["id"], j["name"], j["kind"]) for j in json.load(handle)["jurisdictions"]]


def collect(jurisdictions):
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    stamp = now.isoformat().replace("+00:00", "Z")
    national, reviewed = parse_uscis(fetch(USCIS_URL))
    senators = parse_senate(fetch(SENATE_URL))
    states, missing = {}, []
    for code, name, kind in jurisdictions:
        if kind == "federalDistrict":
            continue  # USCIS: D.C. has no Governor and no U.S. Senators.
        slug = re.sub(r"[^a-z]+", "-", name.lower()).strip("-")
        governor = parse_governor(fetch(USAGOV_URL.format(slug=slug)))
        time.sleep(0.4)
        if not governor:
            missing.append(code)
            continue
        entry = {"governor": [governor]}
        if kind == "state":
            entry["senators"] = senators.get(code, [])
        states[code] = entry
    if missing:
        raise SourceError(f"USA.gov: no Governor found for {', '.join(missing)}")
    return {
        "schemaVersion": 1,
        "dataVersion": now.strftime("%Y-%m-%d.%H%M"),
        "publishedAt": stamp,
        "reviewBy": (now + datetime.timedelta(days=90)).date().isoformat(),
        "reviewStatus": "proposed",
        "sources": [
            {"id": "uscis-testupdates", "url": USCIS_URL, "retrievedAt": stamp, "lastReviewed": reviewed},
            {"id": "senate-members", "url": SENATE_URL, "retrievedAt": stamp},
            {"id": "usagov-states", "url": "https://www.usa.gov/states-and-territories", "retrievedAt": stamp},
        ],
        "national": national,
        "states": states,
    }


def answers_only(data):
    return {"national": data["national"], "states": data["states"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--check")
    parser.add_argument("--report", default="report.md")
    parser.add_argument("--jurisdictions", default="api/v1/jurisdictions.json")
    args = parser.parse_args()
    jurisdictions = load_jurisdictions(args.jurisdictions)

    if args.out:
        data = collect(jurisdictions)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"Wrote {args.out} (reviewStatus: proposed). Review it, set reviewStatus to approved, then publish.")
        return 0

    if args.check:
        with open(args.check, encoding="utf-8") as handle:
            published = json.load(handle)
        try:
            fresh = collect(jurisdictions)
        except SourceError as error:
            open(args.report, "w").write(f"## Official source could not be checked\n\n{error}\n\nNothing was published. Check the source by hand.\n")
            print(error)
            return 1
        old, new = answers_only(published), answers_only(fresh)
        if old == new:
            print("Official sources match the published answers.")
            return 0
        lines = ["## Official answers may have changed", "", "Nothing was published. Review against the official sources, then update and approve `api/v1/dynamic_answers.json`.", ""]
        for version in sorted(set(old["national"]) | set(new["national"])):
            for key in sorted(set(old["national"].get(version, {})) | set(new["national"].get(version, {}))):
                a, b = old["national"].get(version, {}).get(key), new["national"].get(version, {}).get(key)
                if a != b:
                    lines.append(f"- **{version} {key}**: {a} → {b}")
        for code in sorted(set(old["states"]) | set(new["states"])):
            a, b = old["states"].get(code), new["states"].get(code)
            if a != b:
                lines.append(f"- **{code}**: {a} → {b}")
        lines += ["", "Sources: " + ", ".join(s["url"] for s in fresh["sources"])]
        open(args.report, "w").write("\n".join(lines) + "\n")
        print("\n".join(lines))
        return 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

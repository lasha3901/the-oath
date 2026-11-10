# the-oath (public site and data)

Static GitHub Pages site for **The Oath – US Citizenship Test**: home, privacy and support pages, plus the public data the app downloads.

| Path | Purpose |
|---|---|
| `index.html`, `privacy.html`, `support.html` | Website (App Store privacy and support URLs) |
| `api/v1/dynamic_answers.json` | Current officeholder answers, from official sources only |
| `api/v1/apps_catalog.json` | "Discover More Apps" list |
| `api/v1/jurisdictions.json` | States/DC/territories (input for the collector) |
| `scripts/collect_dynamic_answers.py` | Collects answers from USCIS, senate.gov, USA.gov and the Clerk of the House (stdlib Python) |
| `.github/workflows/check-civics-answers.yml` | Weekly check; opens an issue on changes; never publishes |

## Enable GitHub Pages
Settings › Pages › Build and deployment › Source: **Deploy from a branch**, Branch: **main**, folder **/ (root)**. The site is then served at `https://lasha3901.github.io/the-oath/`.

## Updating answers (manual, reviewed)
1. When the weekly check opens an issue (or after an election or appointment), run locally:
   `python3 scripts/collect_dynamic_answers.py --out api/v1/dynamic_answers.json`
2. Compare every value with the official pages listed in `sources`.
3. Set `"reviewStatus": "approved"` and commit. The app rejects files that are not approved or don't validate, and keeps its last good copy.
4. If an official page changed its layout and the script can't parse it, the check opens an issue instead. Update the script or the JSON by hand.

## USCIS and the weekly check
uscis.gov refuses requests from GitHub's runners (HTTP 403). The weekly check then compares the other sources and shows a warning in the run instead of opening an issue. Check USCIS by hand after elections or appointments, or run `--check` locally (it works from a home connection).

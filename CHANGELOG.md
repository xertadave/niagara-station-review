# Station Review – change log

Every fix and feature is listed here. **Read this before changing anything.** A fix may only be removed on
purpose, never by accident. Each line marked [test] has a regression test in tests/test_regressions.py, and
`python build.py` refuses to package if any test fails.

## v1.0.0 – 21 Oct 2026
- First release. Upload a Niagara station backup (.bog) with a site name; the tool reads it, runs the checks
  and opens a review page; tick Include / Disregard; build and download the Word report. [test]
- Reads backups whose firmware strings hold character codes XML forbids (e.g. `&#x0;`). [test]
- Checks: manual overrides on field points (emergency = High), failed sensors, wrong units / CO2 named as
  humidity, device naming outliers, missing and disabled points, inconsistent fallbacks, empty schedules, no
  limit alarms, alarm routes to disabled stations, user accounts, unencrypted connections, version behind another
  station, old backups, history retention, duplicate M-Bus addresses and low frost setpoints. [test]
  - Energy counters (kWh) are never reported as sensor faults; only temperature, humidity and CO2 are judged. [test]
  - A wiresheet setting held at a priority level (an enrolment switch, for example) is a status item, not an
    override. [test]
- Readings at the time of the backup come from the last values passed along links, one per field input. [test]
- Disregard asks why, and whether the logic applies to this report, this site or all sites. Site and all-sites
  choices become rules that are checked before anything is raised on later reviews; changing the decision back
  removes the rule. [test]
- Earlier decisions at the same site carry forward: disregarded findings go under *Already decided* with the
  reason; included findings are tagged *Carried*. Only wording the reviewer wrote is carried (and flagged to
  check); generated wording is rebuilt from the new station so counts and names stay right. [test]
- Rules page on the home screen: edit, switch off, delete, add, export and import (site placeholder `{{SITE}}`).
- Word report on the SSE template: cover, summary with counts, site and system information, status, readings,
  actions, completed during review, reviewed – no action required, engineer notes, contact. [test]
  - The template's contents page also lists "Contact us"; the real Contact us block is the last one, so the
    template body is fully replaced. [test]
- Review page saves each field in place and never rebuilds the list, so the page does not jump to the top
  while typing. Hidden panels stay hidden (the `hidden` attribute wins over the panels' own display). [test]
- Nothing in the repository names a site, station, person or address from a real job; test data is invented. [test]
- GitHub launchers (push / get latest), BUILD-RULES.md and build.py (tests must pass before a zip is made). [test]

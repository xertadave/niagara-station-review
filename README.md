# Station Review v1.0.0

Upload a Niagara station backup (.bog), review what it finds, tick what goes in, and download a
remote PPM report as a Word document. Decisions you make are remembered, so the next station at the
same site only asks about what is new.

A small browser tool (Python standard-library web server, no framework). It also appears as a tile on
the Report Hub.

## Install / run
1. Install Python 3.10+ (tick *Add to PATH*).
2. Unzip to `C:\niagara-station-review` (the Report Hub tile expects this folder).
3. Double-click **START - Station Review.bat**. The first run installs `python-docx`.
4. Go to http://localhost:8780/

Options: `python -m station_review --host 0.0.0.0 --port 8780 --data D:\StationReviewData --no-browser`.

## How a review works
1. **Upload.** Type the site name (or pick one used before) and drop the station's `.bog` file.
2. **Pre-check.** The review page opens with a summary: actions found, how many are new, how many were
   included on an earlier review at this site (*Carried*), and how many you have already ruled out
   (*Already decided*). Add an optional site note for the report summary (for example "floor vacant").
3. **Review.** Open each finding to see what was found, where in the station, why it matters and the
   steps to fix it. Tick **Include** or **Disregard**.
   * When you disregard, say **why**, and choose whether the logic applies to *this report only*, *this
     site* or *all sites*. "This site" and "All sites" save a **rule**. You can widen what a rule covers
     (for example `DISABLED:Fan Speed, MISSING:Fan Speed`).
   * Tick *List in the report as reviewed, not required* to show a disregarded item in the report with its
     reason.
   * Edit the **report wording**, priority and status. Status *Completed during review* moves an item to
     the Completed table; *Client decision* marks it for the client.
   * Saving happens as you go and never moves the page.
4. **Report.** Click **Build report**, then **Download report**. Only included items go in; anything still
   undecided is left out and you are told how many.

## What is remembered
* **Rules** (home page): checked before anything is raised. Edit what they apply to, the wording, switch them
  off, delete them, or export them to a file and import them on another PC. On import, site rules whose site is
  blank or `{{SITE}}` are given the site you choose.
* **Earlier decisions at the same site:** a finding disregarded on an earlier station (report only) is shown
  under *Already decided* with the earlier reason. A finding included earlier is tagged *Carried* and keeps any
  wording you wrote (flagged *Wording carried – check the details*); generated wording is rebuilt from the new
  station so counts and names are right. You still confirm carried findings.
* Everything lives in the `data` folder: reviews (with the uploaded backup and the last report), rules and
  settings. It is never in the zip or in git, so upgrades keep it.

## What the checks look for
| Code | Finding |
|---|---|
| OVR | A field point held by a manual override (emergency overrides are High) |
| FAULT | A temperature, humidity or CO2 reading outside any real range (open/short sensor) |
| UNITS | A CO2 (ppm) reading named as humidity; a temperature input with non-temperature units |
| NAMING | Devices in a group that do not follow the group's naming pattern |
| MISSING | A point most devices in a group have but some do not |
| DISABLED | Disabled proxy points in a device group |
| FALLBACK | Inconsistent fallback values for the same point across a device group |
| SCHED-EMPTY | A schedule with no on-periods (imported ones: check the supervisor) |
| ALARM-ANALOG | No high/low limit alarms at all |
| ALARM-ROUTE | An alarm recipient pointing at a disabled or missing station |
| USERS | Expired, unused, old-password, default and shared admin accounts |
| SEC | Plain Fox, legacy clients, HTTP, or station links without Foxs |
| VERSION | This station's Niagara version is behind another station's |
| BACKUP | Last backup record older than six months |
| HISTORY | Trend logs at default capacity with no export |
| MBUS-DUP | M-Bus meters sharing a secondary address |
| FROST | A frost protection setpoint below 5 °C |

Status items: points in manual, settings held at a priority level, readings at the time the backup was saved
(the last values passed along links), schedules, device groups, field devices, metering, trend logging and
station communications.

A `.bog` holds configuration plus the last values passed along links; it does not hold live status, alarm
history or the supervisor's side of a link, so some findings say "check on the supervisor".

## Report
Word report with: cover, Executive Summary (with actions open / completed / client decision / points in manual),
Site and System Information, System Status (with readings), Actions and Recommendations (Action Summary,
Completed During Review, Reviewed – No Action Required), Engineer Notes and Contact us.

The built-in template is the SSE Energy Solutions report template. Under *Report settings* you can set the
report title, the team name, the contact name and role, or upload your own Word template (its cover, headers,
footers and styles are used; `{{SITE_NAME}}` and `{{CLIENT}}` are replaced).

## GitHub (the master copy)
This folder is a git repository, and your private GitHub repository is the master copy of the code. The
`data` folder is never put in git.
* **First time:** install Git for Windows, create an empty private repository called `niagara-station-review`
  on github.com (don't add a README), then run **GITHUB - push to GitHub.bat** and paste the repository address.
* **New version from Claude:** unzip it over this folder; the zip carries the full history. Then run
  **GITHUB - push to GitHub.bat**.
* **Bring this PC up to date from GitHub:** run **GITHUB - get latest.bat**.
See BUILD-RULES.md for how changes must be made.

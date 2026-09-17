# Scouting protocol

The scouting team uses the **scout mode** of the planner to field-test candidate segments, record what actually exists on the ground, and return verdicts that drive the final route. This document describes the workflow: before departure, in the field, and after return.

## Before the trip: preparation

1. **Check the scouting priority** in each section (Priority 1 must be done first).
2. **Open the app in scout mode** and navigate to your assigned section.
3. **Export GPX files** of the segments you will scout:
   - Click each segment and select "Export as GPX."
   - Load GPX files onto your GPS device or phone (e.g. RideWithGPS, Garmin BaseCamp).
4. **Read the `open_questions`** on each segment and section; these are the things you need to answer.
5. **Note the `resupply_notes`, `water_points`, and `hazards`** already recorded so you know what to test.
6. **Coordinate timing** with the organizers for cultural checkpoints (villages that must grant permission).

## In the field: what to record per segment

For **every segment you ride or walk**, record the following in the app or a notebook (data entry happens after):

| Data point | How to measure | Purpose |
|---|---|---|
| **Date and time** | GPS timestamp or clock | Correlate with weather, tide, seasonal conditions |
| **Actual surface** | Observation: paved / gravel / dirt / singletrack / hike-a-bike dominant / mixed | Refine the `character` field; affects rider experience and equipment needs |
| **Rideability %** | Estimate the fraction of the segment you actually rode the bike (vs. walked) | Calibrate `est_hab_km`; guides future preparation |
| **Hike-a-bike km** | Record cumulative distance walked or carried | Verify or update the `est_hab_km` value |
| **Water sources** | GPS and name of every water point you use or pass (spring, warung, well, river, hot spring) | Populate `water_points`; critical for self-supported racing |
| **Resupply sources** | Shops, warungs, homestays you pass; what they sell | Refine `resupply_notes` and node `resupply` level |
| **People met** | Villages passed, permission status (contacted / granted / unclear / refused), homestay availability | Populate `cultural_notes` and guide checkpoint agreements |
| **Permissions** | Record names of elders, village heads, or officials who agree to host the race | Critical for cultural checkpoints; store separately for privacy |
| **Photos with GPS** | Take photos of tricky sections, water, resupply, cultural sites, hazards; enable GPS tagging in your camera or use a GPS-enabled app | Visual record; helps the route designer and the story; geotag allows precise reference |
| **Hazards** | Rockfall zones, river crossings, loose volcanic soil, animal encounters, landslide evidence | Update segment `hazards` field |
| **Weather and conditions** | Temperature, wind, rain, cloud, ground conditions (mud, flooded streams, etc.) | Guides race window and safety planning; note seasonal variance if you scout in a different season |

## Verdict scale

After riding or walking a segment, record your **verdict**:

| Verdict | Meaning | When to use |
|---|---|---|
| **go** | The segment is rideable as planned, water and resupply exist, no blockers; recommend it for the race | Everything checked out; no surprises |
| **no-go** | The segment is impassable, flooded, politically impossible, or too dangerous; do not use it | Road washed out, village refused permission, active landslide risk, hazard zone active |
| **partial** | Some sections are rideable, others need rework; a variant might work, or the segment needs a reroute or walk section marked clearly | Part of the route works; part doesn't; needs human review to decide the next step |

## After the trip: submission

1. **Export the scouting patch** from the app:
   - In scout mode, click "Export patch" in the right panel.
   - Save `scouting-patch.json` to your machine.

2. **Upload GPX files**:
   - Create a timestamped folder: `data/scouting/gpx/YYYY-MM-DD/`
   - Upload your GPS track (the actual ride) and any segment exports you re-traced.
   - Name files clearly: `2026-07-14-ruteng-reo-a.gpx`, `2026-07-14-ridden-track.gpx`.

3. **Write the scouting report**:
   - Create `data/scouting/YYYY-MM-DD-<section>.md` with front matter:
   ```yaml
   ---
   date: 2026-07-14
   team: [RC, MB]
   segments: [s-ruteng-reo-a, s-reo-pota]
   verdict: go
   gpx: gpx/2026-07-14/
   ---
   ```
   - Write the body as Markdown: narrative of the trip, key findings, quotes from locals, photos, anything that explains the verdicts.
   - Reference open_questions answered: "Q1: Water at Reo is reliable (warung had 5-liter bottles); took photos."

4. **Open a pull request**:
   - Commit the scouting patch, GPX files, and report.
   - Write a clear PR title: "Scouting: Ruteng–Reo, July 2026 — verdict: go on variant A"
   - The maintainer will review, apply the patch, and merge.

## Printable field checklist

Print or photograph this before each trip:

```
SCOUTING TEAM: ___________________    DATE: ________________

SEGMENT: _________________________    GPS device: __________

[  ] Before trip:
     [  ] Downloaded GPX for this segment
     [  ] Read open_questions on the segment and section
     [  ] Noted water_points and resupply_notes to verify
     [  ] Checked for cultural checkpoint (need permission?)

[  ] In the field:
     [  ] Record start time: _________, end time: _________
     [  ] Surface type(s) observed: ___________________________
     [  ] Estimated % rideable: ____%  (vs. walked/carried)
     [  ] Total hike-a-bike km: _____ km
     [  ] Water sources found (GPS + name):
          1. ___________________  @ ___________
          2. ___________________  @ ___________
          3. ___________________  @ ___________
     [  ] Resupply (shops, warungs, homestays):
          1. ___________________  sells: ______________
          2. ___________________  sells: ______________
     [  ] Villages and permissions (names of elders/officials):
          1. ___________________  status: [ ] agreed  [ ] unclear  [ ] refused
          2. ___________________  status: [ ] agreed  [ ] unclear  [ ] refused
     [  ] Hazards noted (rockfall, river, landslide, etc.):
          ________________________________________________
     [  ] Photos taken with GPS: _____ photos
     [  ] Weather: temp ___°C, wind ___km/h, rain [Y/N]

[  ] Verdict: [ ] GO  [ ] NO-GO  [ ] PARTIAL

Notes for the report:
_________________________________________________________
_________________________________________________________

[  ] After trip:
     [  ] Export scouting patch from the app
     [  ] Upload GPX files to data/scouting/gpx/YYYY-MM-DD/
     [  ] Write data/scouting/YYYY-MM-DD-<section>.md
     [  ] Open a pull request with the patch and report
```

## Tips

- **GPS accuracy:** Enable "Improve Accuracy" on phones; use a dedicated GPS unit if you have one.
- **Offline maps:** Download map tiles before the trip for areas with no signal.
- **Photo metadata:** Enable GPS tagging in your phone camera settings (if allowed by the device's privacy policy).
- **Permissions:** Approach village elders respectfully; bring a small gift (e.g. tea, coffee) and explain the race concept.
- **Water safety:** Boil or filter water from open sources; note if a source is reliable in dry season (it may not be in wet season).
- **Local knowledge:** Talk to locals about seasonal road closures, hazard zones, and alternative routes.
- **Conflict of interest:** If you have a personal preference for one variant over another, note it; let the route designer weigh the evidence.

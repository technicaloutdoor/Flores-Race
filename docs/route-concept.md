# Route concept — a traverse of Flores

> Status: **concept**. Everything here is a starting hypothesis for the scouting team, written from
> desk knowledge. Coordinates are approximate unless marked verified in `data/`. The point of the
> tool is to replace this page, section by section, with what the island actually allows.

## The idea in one paragraph

Flores is only ~360 km long, but it is a wall of volcanoes with two coasts. The paved Trans-Flores
highway needs ~670 km to cross it because it has to. A race that keeps leaving the highway to climb
over the spine on farmers' tracks, drop to a forgotten coast, and climb back, can reach 1,200–1,400 km
of riding with well over 30,000 m of climbing, most of it unpaved, a meaningful share on foot. The
course runs **west to east**, from Labuan Bajo (the Komodo gateway, international flights, sunset
finish town for tourists) to Larantuka (Portuguese heritage, the Semana Santa town, the island's
eastern end under Ile Mandiri). West to east because the prevailing dry-season wind is from the
east-south-east — riders will earn it — and because the island's story reads that way: from Komodo
and the Manggarai highlands to Ngada's megalithic villages, the Lio country around Kelimutu, the
ikat weavers of Sikka, and the Catholic-Portuguese east.

Format, borrowed deliberately from the Silk Road Mountain Race: single stage, self-supported, fixed
route, mandatory checkpoints (some of them **cultural checkpoints** where riders sign in at a village
that has agreed to host the race), a time limit of roughly two weeks, a dry-season window (late June
to September; August is the safest bet for weather, though also the busiest month in Labuan Bajo).

## Design rules for the course

1. **Prefer the small track.** A farm track, a cattle path across savanna, a village-to-village
   footpath over a ridge always beats a paved road, even when the road is scenic.
2. **Touch both coasts repeatedly.** Every section that can cross the spine, does.
3. **Hike-a-bike is a feature**, not an accident, but it must be *honest*: the segment says how many
   kilometres, and scouts have walked it.
4. **Every section has a reason**: a volcano, a village, a beach, a piece of history. The section
   story in `sections.json` says what it is.
5. **Villages are hosts, not scenery.** Traditional villages (Wae Rebo, Bena, Gurusina, Luba, Tololela,
   Wologai, Nggela and others) receive guests with protocol. The race must reach an agreement with
   each village council before a single rider passes; where agreement is not possible, the route goes
   around. Checkpoints inside villages bring income (homestays, food, guest fees) — that is the point.
6. **Respect hazard zones.** Active volcanoes (see hazards) define exclusion radii that the route must
   honour on race day, with a pre-agreed reroute.
7. **Resupply is sparse but never impossible.** No rider should be more than ~120 km from a village
   with food and water; the north coast and the Manggarai Timur interior need particular care.

## Sections (west → east)

Distances are concept targets for the whole section; alternatives are listed as A/B/C. Node and POI
ids refer to `data/`.

| # | Section | Anchors | Target km | HAB | Why |
|---|---|---|---|---|---|
| 01 | **Komodo gate and the Mbeliling forest** | Labuan Bajo → Sano Nggoang → Werang | 90–130 | low–medium | Leave the tourist town through the Mbeliling forest (Important Bird Area), waterfalls, to Sano Nggoang, the island's largest crater lake with hot springs. First taste of Manggarai hill tracks. |
| 02 | **Wae Rebo and the south coast of Manggarai** | Werang → Dintor/Denge → Wae Rebo (HAB) → Todo → Iteng | 100–140 | high | Drop to the south coast, then the Wae Rebo trail (~9 km, ~+700 m, on foot with the bike) to the cone-shaped *mbaru niang* houses, the island's most famous traditional village (UNESCO Asia-Pacific heritage award). Continue via Todo, the ancient seat of the Manggarai kingdom. **Cultural checkpoint; requires agreement.** Alternative B: Wae Rebo as an out-and-back from Denge if the onward trail is not passable with bikes. |
| 03 | **Manggarai highlands** | Iteng → Ruteng → Ranamese / Poco Ranaka → Liang Bua | 90–130 | medium | Climb to Ruteng (1,100 m, cool, Catholic hill town), the spider-web *lingko* rice fields at Cancar, the highest volcanic massif of the island (Poco Mandasawu 2,370 m, Poco Ranaka) and Ranamese crater lake. Descend north past Liang Bua, the cave where *Homo floresiensis* was found (2003) — the deep history hook of the race. |
| 04 | **The forgotten north coast** | Liang Bua → Reo → Pota → Riung | 150–200 | medium | The north coast of Manggarai and Manggarai Timur is dry savanna, small ports, few visitors. Reo (old port), then the coastal track toward Pota and Riung — remote, hot, the section most likely to define the race. Riung's Seventeen Islands marine park is the reward. **Water is the constraint here; scouting priority 1.** |
| 05 | **Ngada: megaliths under Inerie** | Riung → Soa (Mengeruda hot springs) → Bajawa → Bena, Luba, Tololela, Gurusina → Aimere | 120–170 | medium–high | Climb from the coast to the Bajawa plateau (1,100 m) past the Mengeruda hot springs, then the megalithic Ngada villages under the perfect cone of Inerie (2,245 m): Bena, Luba, Tololela, Gurusina (rebuilt after the 2018 fire). Option for a hike-a-bike traverse of Inerie's shoulder down to the south coast at Aimere, the arak-distilling coast. **Cultural checkpoints; agreements required.** |
| 06 | **Ebulobo and the Nagekeo plains** | Aimere → Mataloko/Wogo → Boawae (Ebulobo) → Mbay | 110–150 | low–medium | Back up to the plateau (Mataloko seminary and hot springs, Wogo village), round the active cone of Ebulobo (2,124 m) at Boawae, then down the Aesesa valley to Mbay and the rice plains of the north. Alternative B: skip Mbay, cross directly from Boawae to the south coast at Nangaroro (shorter, less remote). |
| 07 | **The blue-stone coast to Ende** | Mbay → Nangaroro/Maukaro → Penggajawa (Blue Stone beach) → Ende | 120–160 | low–medium | Cross the island's narrow waist back to the south coast, follow it east past the blue-stone beach of Penggajawa and Nangapanda to Ende, the largest town of central Flores, under Iya volcano. History: Sukarno's exile in Ende (1934–38), where he is said to have formed the Pancasila under a breadfruit tree. Full resupply. |
| 08 | **Kelimutu and the Lio country** | Ende → Wolotopo → Detusoko → Wologai → Moni → Kelimutu → Wolojita/Nggela → Paga/Koka | 130–170 | medium | The signature section. Lio traditional villages (Wolotopo, Wologai), the Detusoko rice terraces, Moni, and a dawn at Kelimutu's three coloured lakes (1,639 m) — the only place riders should be *required* to stop. Then south through the ikat weaving villages (Wolojita, Jopu, Nggela) to the white beaches of Paga and Koka. |
| 09 | **Sikka and the Portuguese south** | Koka → Sikka village → Lela → Maumere | 60–90 | low | The old Portuguese-era village of Sikka with its 1899 church, then Maumere — airport, hospital, bike shop-ish resupply; the 1992 earthquake and tsunami town. Wuring, the Bajo stilt village of sea people, on the way in. |
| 10 | **Egon and the far east** | Maumere → Watublapi → Egon → Waiterang/Talibura → (north of Lewotobi) → Larantuka | 150–200 | medium–high | Ikat weavers of Watublapi, the trail up Egon volcano (1,703 m) from Blidit, the north coast east of Maumere, then the crux logistics question of the race: how to pass **Lewotobi** (twin volcanoes, violent eruptions in 2024–2025 with fatalities and displacement). Concept A: north coast corridor well outside the exclusion radius. Concept B: the highway corridor via Boru (only if PVMBG status allows). Finish in Larantuka under Ile Mandiri (1,502 m); an optional final hike-a-bike up Ile Mandiri's flank is on the table as a "sting in the tail". |

Concept total: **1,120–1,540 km**. With the optional loops below, an *Ultra* variant approaches
1,800 km. Actual numbers will be computed from the selected segments, never typed.

### Optional loops for an Ultra variant

* **Manggarai Timur interior**: Ruteng → Borong (south coast) → Elar → back to the north coast at Pota
  instead of the direct Liang Bua → Reo → Pota (+120–160 km, very remote, unknown tracks).
* **Inerie full circuit** instead of the shoulder traverse (+40–60 km, HAB).
* **Riung → Mbay by the coast** *and* the Bajawa plateau (+60–90 km).
* **Egon and the Bola coast**: Maumere → Bola (south coast) → Watublapi → Egon (+50–70 km).

## Hike-a-bike inventory (candidates)

| Where | Estimate | Note |
|---|---|---|
| Denge → Wae Rebo (→ onward trail) | 9 km, +700 m; onward unknown | permission and protocol; porters' path, steps |
| Inerie shoulder, Bena → Aimere side | 5–10 km | steep, loose volcanic soil, exposure |
| Kelimutu rim | 1–2 km | paved to the car park, then stairs |
| Egon from Blidit | 4–6 km | forest trail, active fumaroles at the crater |
| Ridge crossings between north and south coasts (Manggarai Timur, Ngada, Nagekeo) | unknown | footpaths between villages: the real scouting work |
| Coastal headlands (Pota–Riung, Riung–Mbay, Paga–Sikka) | unknown | where the coastal track dies |
| Ile Mandiri flank (optional finale) | 3–5 km | very steep; only if it can be done safely at the end of a race |

## Hazards and constraints

| Hazard | Where | Handling |
|---|---|---|
| **Lewotobi Laki-laki** eruptions (2024–2025; fatalities Nov 2024; alert level raised to the maximum at times; exclusion radii of several km) | Flores Timur, section 10 | Treat as a no-go zone in planning; design the north-coast corridor as the primary; check PVMBG status monthly; pre-agree a reroute and an abort rule |
| Other active volcanoes: Ebulobo, Iya (Ende), Egon, Inerie (dormant), Kelimutu (crater lakes, gas) | sections 05–10 | Check PVMBG alert levels before the race; no camping in craters; Kelimutu visit at dawn only |
| Wet season Nov–Apr: landslides, flooded rivers, mud | everywhere | Dry-season race window (late Jun–Sep) |
| Water scarcity | north coast (sec 04, 06), savanna | Node `water` field, mandatory carry capacity rule, planned water caches only if unavoidable |
| Heat | coasts | Route the coasts for early/late hours where possible; medical plan |
| Malaria and dengue (East Nusa Tenggara has among the highest incidences in Indonesia) | island-wide, lower in the highlands | Rider briefing, prophylaxis advice, nets at checkpoints |
| Traffic | Trans-Flores highway | Use the highway only for short links; never at night in towns |
| Earthquake and tsunami history (1992 Maumere) | north coast | Awareness in the rider manual; no route dependency |
| Dogs | villages | Standard bikepacking advice |

## Cultural and historical threads to carry through the story

* **Deep time**: *Homo floresiensis* at Liang Bua; the Soa basin fossil sites.
* **Megalithic present**: Ngada villages with *ngadhu* and *bhaga* shrines; Manggarai *mbaru niang*
  houses at Wae Rebo and Todo; *lingko* spider-web fields.
* **Weaving**: Lio ikat (Nggela, Wolojita, Jopu), Sikka ikat (Watublapi), Manggarai songke.
* **Portugal and Rome**: Larantuka's Semana Santa (since the 16th century), Sikka's church, the Solor
  fort across the strait, Ledalero seminary; Flores as the most Catholic island of Indonesia.
* **The republic**: Sukarno's exile house in Ende.
* **Sea people**: the Bajo at Wuring.
* **Fire**: the volcanoes, and Kelimutu's lakes as the resting place of souls in Lio belief.

## Status after the first computation (September 2026)

The pipeline has now routed the concept over the real track network (`pipeline/route_candidates.py`,
remote cost profile, every one of the 37 anchors found on the network). First honest numbers, all
still `concept` status and unscouted:

| Variant | Length | Climbing (10 m threshold) | Unpaved | Hike-a-bike estimate |
|---|---|---|---|---|
| Traverse, network-routed | ~1,340 km | ~32,800 m | 59% | ~45 km |
| Ultra, network-routed (loops as currently defined) | ~1,390 km | ~35,900 m | 68% | ~45 km |

What this tells the route designer:

* The Traverse lands inside its 1,120–1,540 km target without any forcing. The climbing figure
  (about 24 m per km) is plausible for Flores roads and tracks; the figures computed on the
  hand-sketched corridors are not meaningful and the app marks them as such.
* The Ultra loops as sketched (Manggarai Timur interior, Bola coast) add only ~50 km, far less than the
  120–250 km this page hoped for. To reach 1,600–1,900 km the Ultra needs genuinely new anchors: for
  example a north-coast excursion Riung → Mbay by the coast *and* the plateau, an Inerie full circuit, a
  Kelimutu–Egon ridge link, or a Lembata/Adonara epilogue by ferry. Add anchors to `routes.json`, rerun the
  candidate generator, and the numbers update.
* The track-and-path share of most computed pairs is still low (0–25%): the network in OpenStreetMap
  knows the roads far better than the farmers' paths. The remoteness layer in scout mode shows where
  mapped tracks exist; where the map is empty, only feet on the ground will tell.

## Status after the brochure session (September 2026)

The course now exists as importable GPX (`exports/gpx/`) and as an illustrated brochure
(`docs/brochure/`). Numbers below come from `exports/gpx/manifest.json` (routed geometry, SRTM,
10 m threshold) and supersede the table above where they differ:

| Variant | Length | Climbing | Unpaved | Hike-a-bike estimate |
|---|---|---|---|---|
| Traverse, network-routed | ~1,331 km | ~32,800 m | 59% | ~46 km |
| Ultra (Manggarai Timur interior + Bola coast) | ~1,382 km | ~35,900 m | 68% | ~45 km |
| Ultra+ (Ultra + Inerie full circuit) | ~1,387 km | ~35,800 m | 67% | ~37 km |

Optional tracks now routed over the network and exported on their own (option vs. the main-course
stretch it replaces): Manggarai Timur interior loop (204 vs 170 km), Bola south-coast loop (46 vs 29 km),
Inerie full circuit via Gurusina and the Sewowoto coast (35 vs 30 km; two new anchors `n-gurusina`,
`n-sewowoto`), Wae Rebo out-and-back with the Denge → Todo road (60 vs 60 km), Boawae → Nangaroro
direct (49 vs 118 km), south coast direct Aimere → Nangaroro (102 vs 197 km), Lewotobi southern
corridor via Boru (118 vs 96 km). Two ideas were computed and set aside: a Kelimutu → Egon highland
link (120–163 km, 4,700–7,300 m, drops the Lio villages, the beaches, Sikka and Maumere) and the paved
Riung → Mbay coast road (48 km, remoteness index 1). The "Nangaroro/Maukaro" wording in section 07 is
a labelling error: Maukaro is a north-coast sub-district of Ende.

Hazard status recorded with dates in `data/pois.geojson`: Lewotobi Laki-laki at PVMBG Level III with a
5 km exclusion radius as of the week of 27 Aug–2 Sep 2026; a M7.7 earthquake on 15 Aug 2026 north of
Ende (47+ dead, landslides in the summit areas of Ebulobo, Kelimutu and Anak Ranakah per Badan Geologi);
the Reo–Pota–Riung corridor on emergency water trucking in August 2026. All to be re-checked before
any planning milestone.

## Open questions for the first scouting season (priority order)

1. Is there a continuous rideable/walkable corridor Reo → Pota → Riung along or near the north coast,
   and where is water? (section 04)
2. Which villages will host cultural checkpoints, under what terms? (sections 02, 05, 08)
3. Is the Wae Rebo onward trail passable with a bike, or is it an out-and-back? (section 02)
4. Inerie shoulder: is the Bena → Aimere descent safe with a bike? (section 05)
5. Lewotobi: what is the realistic corridor and the abort plan? (section 10)
6. Which ridge crossings between coasts exist as footpaths? (sections 04–07) — the track network
   layer in scout mode is the starting point; the DEM tells you where the passes are.

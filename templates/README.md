# Layout templates

One reusable column template per layout family — Meiji / Taishō / Shōwa seniority lists and
the 列次名簿 variant. A few dozen at most, built once with light human setup from ground-truth
and sample pages.

**Field identity comes from geometry, not from cell contents.** That is the whole point: it
is what eliminates "is this a name or a date?" false detections. Define the grid once, reuse
it across thousands of pages.

Pipeline: classify page → template · register/align (deskew + ruling-line anchors) ·
read fields by fixed position · reconcile rows against the monotone seniority sequence.

> Do not add a per-page self-improving crop detector here. That approach is what sank the
> prior effort and is excluded by design (see `docs/PLAN.md`, standing commitment 3).

## The artifacts

Each `*.json` here is one layout family, versioned as data: band fractions, the fields
between them, the match thresholds, and the provenance of how it was derived. The code
that uses them is [`reading/registration.py`](../reading/registration.py); tests are
[`reading/test_registration.py`](../reading/test_registration.py).

| Artifact | Layout family | Derived from |
|---|---|---|
| `showa-teinen-meibo-A.json` | Shōwa main roster table (現役将校実役停年名簿) | pid 1449426 (昭和8年調), 7 panels across frames 60–700 |
| `showa-teinen-meibo-B.json` | same layout, 1935 edition: rulings sit lower, past A's tolerance; fields carried over from A, unconfirmed on this edition | pid 1449474 (昭和10年調), 8 panels across frames 100–700 |
| `taisho12-teinen-meibo-wide.json` | Taishō main roster table (陸軍現役将校同相当官実役停年名簿), 1923 edition, 将官・佐官 pages: 5–8 officers per leaf, six bands, one cell for all appointment dates, no cohort row | pid 930894 (大正12年調), 4 panels across frames 20–100 |
| `taisho12-teinen-meibo-narrow.json` | same edition and fields, 尉官 pages listed by regiment: 13 strips per leaf, lower bands ruled at other heights | pid 930894, 6 panels across frames 150–650 |
| `taisho15-teinen-meibo-wide.json` | 1926 edition, 将官・佐官 pages: the 1923 bands plus a 出身期別 row | pid 1908494 (大正15年調), 5 panels across frames 20–150 |
| `taisho15-teinen-meibo-narrow.json` | same edition and fields, 尉官 pages: 13 strips per leaf, the two lowest rulings lower | pid 1908494, 4 panels across frames 350–550 |

**Taishō labels confirmed by the lead 11 Sep 2026** (`docs/decision-taisho-field-labels.md`).
The bands are named from the legend column the volumes print at the head of each 尉官
section. Two points a reader needs: `appointment_dates` is the one cell holding every rank's
appointment date, and its 少尉 line is the schema's `commissioning_date`; the small figures
under a name are 年齡 (age at the 調 date), not a birth date.

**Camera scans.** The Taishō volumes are photographs of the bound book, not film scans, and
`reading/registration.py` handles them on their own path (`scan_kind`): leaves overlap past
the gutter cut, rulings are found with a local threshold, and horizontal lines outside the
officer-column rulings - page edges, cover, binding strip - are dropped. Film scans take the
old path unchanged; every cached 1933 and 1935 frame registered identically before and after.
Not yet covered by any template, and so reported rather than registered: the 各部 sections
(no 列次 row), the 休職 sections, and the index.

**Reading a template.** `band_fracs` are horizontal ruling positions as fractions of table
height. `fields` name the space *between* two bands by index, so a field's edges follow the
ruling the page actually has rather than a nominal fraction. Officer records are the vertical
column strips, index 0 = rightmost.

**Field names are the human half.** Geometry is derived and measured; the semantic label on a
band is a reading decision. Fields carry `confirmed` and a `note`, and unconfirmed ones are
named descriptively rather than authoritatively — in `showa-teinen-meibo-A` the five lower
fields are confirmed against the page, the four upper date rows are not. Correcting a label is
a JSON edit, not a code change.

```
python -m unittest discover -s reading -p "test_*.py"
```

## Adding a template

1. Cache a handful of pages spanning the volume (`ingestion/iiif_client.py`).
2. Run `reading.registration.detect_page` over them and pool `Grid.band_fracs`.
3. Cluster at the match tolerance; keep bands supported by most panels; take the median.
4. Read a page to name the fields — and mark as unconfirmed anything you are guessing.
5. Set thresholds from measurement, using non-matching pages as negative controls. Record
   the numbers in `match.note` so the next person knows why the gate sits where it does.
   Where a neighbouring layout differs by missing a ruling rather than moving one, name that
   band in `match.required_bands`: `min_bands_matched` forgives any one miss and cannot
   tell a faint line from a row the page never had. Where a cell holds rows of dense small
   type that read as lines (the Taishō appointment cell), name the interval in
   `match.text_intervals`: rulings found inside it count neither for nor against the page.
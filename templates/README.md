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
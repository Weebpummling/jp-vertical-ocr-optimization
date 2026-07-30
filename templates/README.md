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
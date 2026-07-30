# Spike C — template registration on real pages · ANSWERED (29 Jul 2026)

**Question:** does top-down template registration actually hold on real degraded scans —
the load-bearing bet of the whole design?

**Verdict: yes.** On real pages of the 1933 volume (pid 1449426), a template of
horizontal field-band positions transfers across pages with sub-percent residuals, and
non-roster layouts announce themselves by failing to match — which is the page-classifier
signal, not a defect.

## Experiment

`reading/spike_c/registration_experiment.py` on 10 spreads (20 page panels) sampled
across the volume (frames 60–850): split spread at the gutter → deskew from ruling
angle → extract long rulings morphologically → cluster into band positions → score
every panel against a template defined once from the first panel.

## Results

- **Main-layout table pages match 10–11 of 11 template bands with mean residual
  ≤ 0.005 of table height** (typically 0.002). Field identity by geometry works: the
  11 bands land on the visible field structure — rank dittos / promotion dates /
  seniority number / post / court rank / name + birth date / cohort number.
- **Skew is small and handled**: observed range ±1.2°, corrected by rotation from the
  dominant ruling angle.
- **Officer columns**: 10 per page on the main layout, detected correctly on clean
  panels. Vertical-line detection is less stable than horizontal (thin rulings break;
  some panels under-count). This is Phase-1 engineering (per-band column detection,
  full-height-line filtering), not a design risk.
- **The volume contains multiple layout families**, confirming the template-library
  design: main roster tables (sectioned by branch+rank, e.g. 歩兵大佐, 砲兵少尉), and
  a name-index section (索引) at the back with a completely different grid. Index pages
  matched only 6–9/11 bands with wrong band signatures — cleanly separable.
- **Seniority anchors confirmed at scale**: Arabic-numeral seniority numbers, monotone
  ascending right-to-left *within each branch+rank section*, with gaps (the sequence is
  global across sections). Row auditing must therefore reconcile per-section
  monotonicity, not global contiguity.

## Detection lessons (they cost an iteration each)

1. **Scale matters**: below ~0.5× resolution the thin interior rulings alias away under
   Otsu thresholding and the field bands vanish. Detect at ≥0.6×.
2. **Heal before opening**: a short morphological close along the line direction before
   the long opening rescues 1-px breaks in thin rulings.
3. **Spreads don't contour-split**: the two pages of a spread touch; split at the
   darkest column near the middle (gutter shadow) instead.

## Consequences for Phase 1

- Template = band fractions + column positions per layout family; the experiment's
  empirical 11-band template is the seed for the first Shōwa template.
- Page classification can be as simple as band-signature distance to known templates —
  the index pages demonstrate the separation margin is wide.
- Add a per-section (branch+rank) dimension to seniority auditing in Layer 2.

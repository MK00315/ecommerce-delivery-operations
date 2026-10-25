# Dashboard design: Midnight Editorial

The user selected their new Superdesign project, **Midnight Editorial Style**, as
the main template for the delivery dashboard. This is a separate visual direction
from the complaint project's sky-blue dashboard.

The selected canvas is:
https://superdesign.dev/teams/4c16666b-9de5-4e29-8075-d59290c79393/projects/eab076dd-28a2-452e-a97d-4329c1c1a803

The adapted preview is:
https://p.superdesign.dev/draft/0c0e017f-c7d6-43d5-bd58-3bf78e8a194f

## Selected direction

Keep the template's near-black background, Satoshi/Inter typography, coral accents,
rounded tonal surfaces, slash headings, horizontal navigation and glass dock.
The landing-page composition was adapted to show delivery analytics immediately.
There is no left sidebar or reuse of the earlier blue dashboard style.

The original template remains version 1. A generated version 2 introduced fictional
live logistics data; it is not accepted or used as project evidence. Versions 3-4
directly correct the content, charts and layout to the actual project, preserving
the selected visual language. The user approved version 4 and requested implementation.
The remote draft's legacy canvas title still says Lumen, while the actual document
title and visible identity are Delivery Ops.

## Content and checks

- Overview: full-source counts, completed SLA denominator, late rate and delivery time.
- Delivery patterns: actual January-August 2018 late counts and top-six state volumes.
- Review planning: default constraints, 28-batch totals and the four-policy comparison.
- Evidence: distance association, experimental model results and interpretation limits.
- Navigation anchors and expandable evidence notes are part of the design preview.
- The dock has its own reserved row below the scrollable content, avoiding overlap.
- Reduced-motion and keyboard-focus styles are included.

The design preview was inspected in the in-app browser at 797 by 930 CSS pixels.
Its figures were reconciled to the saved reporting CSVs. The approved direction
has since been implemented as a working local dashboard with a FastAPI/DuckDB
backend. Responsive browser viewport checks cover 390, 797 and 1440 CSS-pixel
widths; these are layout checks, not physical-phone tests. The original canvas
remains a design reference, while the localhost app contains working controls.

## Working implementation

The implementation reads a compact, verified DuckDB snapshot of the existing
orders, frozen model priorities and operations results. Date/state filters preserve
the completed-delivery denominator and explicit unknown outcomes. Review planning
keeps its separate August cohort, equal baseline constraints, declared time assumptions
and experimental model limits. A custom mode runs the actual optimizer on one
historical batch. Public copy retains the historical/portfolio scope. The full
99-test suite passed; current browser evidence is recorded separately in
`DASHBOARD_VERIFICATION.json`.

Existing Excel, native Power BI, cloud evidence, training and prior project work
are preserved. No cloud rerun, model retraining, GitHub publication or deployment
was performed during the design and local implementation phases. GitHub/live
publication remains the next stage.

# Stacy Family Tree

An interactive family history centered on Trevor, Sara and Jeremiah Stacy, covering the
Stacy, Riffe, Prichard, Folz, Mudd, Zoglman, Stallings, Coomes, Campbell and Hively families.

Open `index.html` in a browser, or view the hosted site on GitHub Pages.

`zoglman-stallings/` holds the archived first edition of the site, covering only the
Zoglman and Stallings families with their newspaper and record links.

## Adding to the tree

All of the family data lives in the `DATA` block near the top of the `<script>` in `index.html`:

- `PEOPLE` – one entry per person (names, dates, places, parents, spouses, notes, sources)
- `CHAPTERS` – the story chapters
- `EVENTS` – the timeline
- `RECORDS` – linked obituaries, grave memorials and documents
- `MEDIA` – photos and scanned documents (files live in `media/`)
- `TREES` – the layouts for each family tree view

## Public edition

`node tools/build_public.js dist-public` builds a public copy of the site in `dist-public/`. It removes the dates, places, photos, notes, timeline entries, stories and records of living people from the data itself, so they are not in the page source either. Living relatives keep only their names and family links. `tools/living.js` decides who counts as living: no death date and a known or estimated birth year of 1926 or later. Add ids to `ALWAYS_LIVING` or `NEVER_LIVING` there to override it.

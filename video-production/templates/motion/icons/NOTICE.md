# Icons

The SVG files in this folder are a curated subset of **Lucide** (`lucide-static` 1.47.0),
used under the ISC licence in `LICENSE`. They are inlined into compositions at build time,
so renders never fetch anything. Colour comes from brand tokens via `currentColor`.

To add one: copy it unchanged from the same package version, then map a keyword to it in
`video-production/storyboard/infographics.py` (`ICON_FOR`).

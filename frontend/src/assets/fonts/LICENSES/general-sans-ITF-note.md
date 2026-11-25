# General Sans — ITF Free Font License note

General Sans (weights 400/500/600/700, vendor Fontshare) is a **free font**
under the ITF Free Font License. Terms relevant to this repository (verified
2026-11-25 against the Fontshare license):

- Free for personal and commercial use, no attribution required.
- The font files **may not be modified, subset, converted, or
  redistributed**.

Consequence for this codebase: the woff2 files in
`../general-sans/` are served **unmodified** — exactly the bytes served by
the Fontshare CDN URL that was previously imported at `base.css:1`. Do not
subset, re-encode, or convert them. If a different weight or style is ever
needed, add the provider's exact file for it; never derive a local variant.

Source: https://www.fontshare.com (font by Jonathan Pinhorn / Fontshare).

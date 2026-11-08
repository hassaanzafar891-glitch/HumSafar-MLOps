# Verified destination photographs

Sixteen existing attraction IDs have local photographs: eight in Pakistan and eight in Hawaii. The complete
[photographer/source/license table](public/images/destinations/ATTRIBUTION.md)
also ships as `/images/destinations/ATTRIBUTION.md` in the production build.

`DestinationPhoto.jsx` is shared by Explore/featured cards, individual and group
recommendation cards, detail dialogs, and itinerary stops. It performs a strict
stable-ID lookup and checks country, type and source compatibility. There is no
name-based guessing or reuse of a nearby destination's photo. Normal runtime
loads local assets only; source/license links open Wikimedia/Creative Commons
when followed. No secrets, API keys or image-service subscription is required.

Each photo has 480px and 960px WebP variants, except Rush Lake and Ho'okipa Beach which use 480px
and 800px to respect the original source resolution. The browser chooses with
`srcset`/`sizes`; images have intrinsic dimensions, lazy loading, async decoding,
alt text, visible attribution and license links. Card images use cover cropping;
details show the complete photo. Both absent and failed images display a clearly
labeled illustration. Photo errors reset on destination changes. No recommendation
scores, datasets, model artifacts, permissions or voting behavior are changed.

Attribution/provenance is separate from the ML catalog:

- `photo_sources.json`: manually reviewed file/author/license and destination IDs.
- `src/data/destinationPhotos.json`: generated image manifest, URLs, dimensions,
  hashes, retrieval date and resize/conversion disclosure.
- `public/images/destinations/`: lightweight assets with accompanying attribution.

To reproduce assets with the project's existing requests/Pillow installation:

```powershell
.venv\Scripts\python.exe frontend\scripts\fetch_destination_photos.py
```

The helper reads only the international catalog to verify exact identities. It
downloads only the sixteen allowlisted previews, caps each response at 2 MiB, checks
HTTP status/image content, writes responsive images, and records checksums. On
reruns, unchanged local assets with matching hashes are reused. Full originals
and unrelated files are not downloaded. Builds and tests require no network.
Before adding another source, verify its subject, author and file-specific reuse
permission; do not use the general Commons footer as the image license.

Nathiagali and Passu are absent from the current catalog and therefore have no
cards to photograph. The other 61 Pakistan attractions, 1,504 Hawaii attractions and
historical hotels have no assigned photographs in this initial set. No generic
photo is shown as if it depicts one of those records. Images may depict winter
or past conditions; they imply neither current conditions nor booking availability.

Verification:

```powershell
cd frontend
npm test
npm run build
npm run test:e2e
```

Photo tests check exact-ID matching, source/country/type guards, local checksums,
credits, responsive attributes, error fallbacks and detail/itinerary reuse. The
mobile browser test loads the actual Ansoo Lake photo and its attribution in the
catalog detail dialog; the two-account planning workflow remains a regression test.

## Final frontend cleanup

Recommendation information is shown in one collapsed-by-default native details
section, labelled "How recommendations work". Every backend warning message is
retained verbatim. Date/restriction conflicts and stale-list warnings remain
prominent outside it; request errors retain their existing alert behavior. The
compact approach label and explicit new-account preference-based explanation
remain visible while details are closed. Individual-list voting/itinerary limits
also stay visible. Backend responses, models and ranking/voting logic are unchanged.

Eight additional photos were selected from genuine saved recommendation outputs:
`data/processed/hawaii/group_validation_details.json` and
`data/processed/international/service_demo.json`. Existing validation output was
read only to count recommended attractions and match their catalog IDs. Two more
photos cover Hanalei National Wildlife Refuge and Lanikai Pillbox, both visible in
the actual new-account browser workflow. No user
preferences, ratings, model weights or candidate rankings were changed. No test
split was read. The script checks the exact country/source for both Pakistan and
Hawaii; the complete photo set is 32 responsive files totaling 3,169,780 bytes.

Recommendation cards use consistent 16:10 imagery and illustrative fallbacks,
refined spacing/type, and avoid stretching every card when an itinerary form is
expanded. Existing source/license/resize disclosures stay visible.

Final local verification: **19 frontend unit tests passed, all 3 Edge browser
tests passed, and the production build passed**. Browser checks cover two-account
recommendations/voting/itinerary, collapsed explanations with accessible backend
disclosures, mobile photo details, and Hawaii photo loading/credits/card aspect
ratio. All ten added photos were visually inspected. A repeat asset-preparation
run reused all sixteen checksum-verified source entries without downloading them.

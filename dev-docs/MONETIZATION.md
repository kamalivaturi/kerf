# Turning Kerf into a paid product later

Kerf ships free (MIT). These hooks exist so you can add a subscription without rewriting anything.

## What's already built in

| Hook | Where | What it gives you |
|---|---|---|
| Feature tiers | `Feature(tier="free" \| "pro")` in `kerf/features.py` | Mark any feature (or a plugin's) as paid. The UI shows a **Pro** badge and a "Requires pro" button. |
| Built-in licence keys | `kerf/license.py` (Lemon Squeezy License API) + Settings → Licence | Sell a monthly/yearly plan on Lemon Squeezy with licence keys enabled, set `KERF_LS_PRODUCT=<product id>`, mark features `tier="pro"`. Users paste their key; Kerf activates it per machine, re-validates weekly and allows 14 days offline. Deactivate frees the seat. |
| Entitlement provider | `KERF_LICENSE_PROVIDER` → your module with `entitled(name, tier)` and `status()` | Plug in licence-key checks (your server, Paddle, Stripe, Gumroad). The engine refuses unentitled runs (HTTP 402). |
| Drop-in plugins | `~/.kerf/plugins/*.py` | Sell premium features as separate files/packages without forking the core. |
| Presets | `~/.kerf/presets/<feature>/*.json` | Sell caption-style / zoom / pipeline packs. |
| Update checker | `kerf/server.py:check_update` (GitHub Releases) | Point `KERF_REPO` at your release channel; panels show "update available". |
| Versioning | `kerf/__init__.py`, `ui/public/manifest.json`, `CHANGELOG.md` | One version string per release; the release workflow builds the zip + .ccx on every `v*` tag. |

## Models that work with an open-source core

1. **Open core.** Keep this repo free; publish a closed `kerf-pro` package (more features, presets,
   priority support) that registers via the plugin/entitlement hooks.
2. **Hosted services.** Charge for what costs you money: cloud transcription on GPUs, AI prompt edits
   without the user's own API key, stock-footage credits, team preset sync.
3. **Convenience.** Signed installer, auto-update, onboarding, support SLA, Adobe Exchange listing.

## Licence choice

MIT lets anyone (including competitors) reuse the code commercially. If you want to stop closed
forks while still selling a commercial licence yourself, re-license **before** accepting outside
contributions: AGPL-3.0 + a commercial licence is the usual dual-licence pattern. Collect a CLA
from contributors if you plan to relicense later.

## Note on client-side checks

Anything in an open-source client can be patched out. Enforce paid value on a server (hosted
features, signed licence tokens checked against your API), not only with `entitled()` in local code.

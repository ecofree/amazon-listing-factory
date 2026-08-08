# Image publication sizing

The current production path commits every provider result through
`core/image_upscale.py` before CandidateManifest, QA, publish, or template
can read it. The publication contract is an exact `1600x1600` square.

The bundled enhancement backend is Real-ESRGAN `realesrgan-x4plus`:

- `tools/realesrgan/realesrgan-ncnn-vulkan.exe`
- `tools/realesrgan/models/realesrgan-x4plus.param`
- `tools/realesrgan/models/realesrgan-x4plus.bin`

`AMAZON_FACTORY_UPSCALE_BACKEND=auto` (the default) tries that bundled model
and falls back to Pillow Lanczos in the same candidate transaction if the
process, GPU, or model is unavailable. `realesrgan` also keeps the fallback;
`lanczos` deliberately selects the deterministic path. A fallback never
silently publishes an un-sized image: the manifest records the backend and
publish requires exactly `1600x1600`.

The old Real-ESRGAN notes in the historical bed-frame documentation were not
previously reachable from this project's production chain. Existing old
CandidateManifests are stale under the v6 publication contract and must be
regenerated; historical job directories are not migrated automatically.

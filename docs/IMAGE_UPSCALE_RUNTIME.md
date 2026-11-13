# Image publication sizing — current runtime

Every native response passes native integrity and normalization, then
`core/image_upscale.py`, before the immutable candidate commit. Publication output
is exactly 1600×1600; a saved candidate is not QA or release approval.

Normal undersized input uses the NCNN/Vulkan executable with the official
`realesrnet-x4plus` pixel-reconstruction weights:

- `tools/realesrgan/realesrgan-ncnn-vulkan.exe`
- `tools/realesrgan/models/realesrnet-x4plus.param`
- `tools/realesrgan/models/realesrnet-x4plus.bin`

This host binds NCNN GPU 1 to NVIDIA GeForce RTX 2060, tile 256, threads 1:1:1,
process timeout 120 seconds. GPU ID/name must be configured and the returned
NCNN device log must match. NCNN index 1 is not NVIDIA/CUDA index 0. The existing
exclusive host GPU resource is shared with SAM.

Already-sized RGB PNG bytes are retained. Larger images are downsampled with
Lanczos. Missing assets, invalid GPU settings, timeouts, process/decode failures
**do not trigger interpolation fallback**; the paid native response is retained
for local recovery. There is no global `lanczos`/`pillow` enlargement selector.

Only an operator-confirmed upscale artifact on an exact candidate permits local
Lanczos recovery from its finalized native receipt:

```text
python scripts/factory.py revise --job <job> --child <ASIN> --role <role>
  --mode publication_reprocess --upscale-artifact-confirmed
  --candidate-sha256 <exact-parent-sha> --reason <observed-artifact>
```

That operation creates a new immutable derived candidate, sends no image request,
and transfers no QA or human approval to the new SHA. It is not an automatic
artifact detector and does not repair a product defect already present in native
pixels.

CandidateManifestV8 records the actual backend. Historical GAN/Lanczos labels on
unchanged current-schema candidates remain provenance, not executable fallback
routes. Do not relabel old records, delete failed candidates, regenerate merely
because a tool version changed, or use a new job to erase unknown-request debt.

Known purple-tree residuals and other-category texture/text quality require real
pixel inspection; GPU success and valid PNG are not proof of visual acceptance.

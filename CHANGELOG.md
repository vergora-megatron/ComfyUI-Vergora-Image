# Changelog

## 0.2.0 - 2026-10-15

The adapter now speaks the full official Images API parameter set.

Added

- Official fields on both nodes: `quality`, `background`, `output_format`, `output_compression`,
  `moderation`, `n` and `user`; the editor also gets `input_fidelity` and an optional `mask`
  (IMAGE, transparent area is repainted).
- A field is only put in the request body when it leaves its default, so a node nobody touched
  sends exactly what 0.1.0 sent.
- Replies with more than one picture are returned as an IMAGE batch and each picture is saved.

Compatibility

- **Not breaking.** The new widgets are appended to the optional group, so every widget that
  existed in 0.1.0 keeps its position and workflows saved with 0.1.0 restore their values.

Notes

- Live status of each official field is tabulated in `README.md`. `prompt`, `model`, `size`,
  `image` and the single-picture behaviour were measured on 2026-10-14; the fields added here are
  sent but not yet measured, because on 2026-10-15 the image route answered
  `500 do_request_failed: context deadline exceeded` (the relay's upstream provider stopped
  responding) while `/v1/models` and the video route stayed healthy. Those rows get measured and
  recorded as soon as the provider is back.
- `partial_images` / `stream` are intentionally not exposed: a ComfyUI node returns one finished
  value.

Changed

- The documentation now lists only the image models the platform actually serves; no other
  provider's model ids appear anywhere in the pack.

## 0.1.0 - 2026-10-14

First release: two nodes for the Vergora image routes, both verified live against
`https://api.vergora.ai/v1`.

Added

- `VergoraImageGenerator` (文生图) for `POST /images/generations` and `VergoraImageEditor`
  (图像编辑) for `POST /images/edits`.
- Models: `gpt-image-2`, `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst` - only ids that answer
  are listed, so nothing in the dropdown fails on arrival; `model_override` reaches any other id,
  including models added later.
- Sizes: `1024x1024`, `1536x1024`, `1024x1536`, `1080x1920` (vertical) or `auto`.
- Outputs: an `IMAGE` you can wire straight into another node, the path of the saved file and the
  temporary platform URL; the picture is also rendered in the result panel.
- Editing accepts a connected `IMAGE` (a batch of up to ten becomes several references) or picture
  URLs / data URIs in `image_url`, so the node runs without any wiring.
- Key handling: `config.ini` (gitignored) or `VERGORA_BASE_URL` / `VERGORA_API_KEY`; when this pack
  has no key of its own it borrows one from a sibling Vergora pack in the same `custom_nodes`
  folder.
- Gateway errors are translated rather than dumped: `401` auth, `403` quota, `503` no channel,
  `524` edge timeout, `500 model_price_unavailable`. Failed pictures are never retried
  automatically, because a `524` may already have been billed upstream.
- `test_offline.py` drives both nodes against a stub HTTP layer - no network, no key, no cost.
- `list_models.py` prints the catalogue your key can see, grouped by output modality.
- Two example workflows in `examples/`.

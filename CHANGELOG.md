# Changelog

## 0.1.0 - 2026-10-14

First release: two nodes for the Vergora image routes, both verified live against
`https://api.vergora.ai/v1`.

Added

- `VergoraImageGenerator` (文生图) for `POST /images/generations` and `VergoraImageEditor`
  (图像编辑) for `POST /images/edits`.
- Models: `gpt-image-2`, `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`. The two gemini image
  models in the catalogue answer `500 model_price_unavailable` on every route, so they are kept
  out of the dropdown; `model_override` reaches any id, including models added later.
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

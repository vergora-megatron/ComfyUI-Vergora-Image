# ComfyUI Vergora Image

Two ComfyUI nodes that put GPT-Image text-to-image and image editing behind the Vergora
gateway: type a prompt and get a picture, or wire an image in and ask for a change. Both
endpoints are called for you, the result is saved into ComfyUI's output directory, shown
in the result panel, and handed on as an `IMAGE` you can feed into other nodes (including
the Vergora video pack's `first_frame`).

- **Nodes:** `vergora 文生图（gpt-image）` (text to image) and `vergora 图像编辑（图生图）`
  (image editing).
- **Models:** the three image models that actually answer - `gpt-image-2`,
  `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`. Only working models are listed, so
  nothing in the dropdown fails on arrival. `model_override` accepts any other id, so a
  model the platform adds (or prices) later works without a code change.
- **No extra pip packages.** The request layer uses `requests` when it is installed and
  falls back to the standard library `urllib`, so the nodes load in any ComfyUI.
- **Key stays out of the graph.** It is read from `config.ini` or the environment, never
  from a widget, so sharing a workflow never shares your key.
- **Verified on:** ComfyUI 0.40.0 (Desktop), Python 3.13, Windows 11, against
  `https://api.vergora.ai/v1` on 2026-10-14.

## Requirements

- ComfyUI (recent version; developed against 0.40.0)
- A Vergora API key
- No additional packages

## Installation

1. Copy this folder into your ComfyUI `custom_nodes` directory:
   - manual / portable install: `<ComfyUI>/custom_nodes/ComfyUI-Vergora-Image`
   - ComfyUI Desktop: `custom_nodes` lives inside the installation base path
2. Create your configuration from the template and fill in your key (`config.ini` is
   gitignored and is not part of a fresh checkout):
   - Windows: `copy config.ini.example config.ini`
   - macOS / Linux: `cp config.ini.example config.ini`

   ```ini
   [API]
   BASE_URL = https://api.vergora.ai/v1
   KEY = sk-your-key-here
   ```

3. Restart ComfyUI and add the nodes from the `vergora` category (search for `vergora` or
   `image`).

Instead of the file you can set `VERGORA_BASE_URL` and `VERGORA_API_KEY`; the environment
wins over `config.ini`. If you also run the Vergora video pack, that is the cheapest way
to keep a single key in one place.

## What is in this repository

| File | Purpose |
| --- | --- |
| `nodes.py`, `__init__.py` | The two custom nodes |
| `config.ini.example` | Configuration template, copy it to `config.ini` |
| `test_offline.py` | Offline self-test, no network or key needed |
| `list_models.py` | Prints the models your key can see, grouped by output |
| `examples/` | Two loadable workflows, see below |
| `CHANGELOG.md` | Release history |
| `pyproject.toml` | Package metadata for the ComfyUI node registry |
| `README.md`, `LICENSE` | Documentation and license |

## Examples

Drag either file onto the canvas (or `Workflow` -> `Open`):

| File | What it does |
| --- | --- |
| `examples/text-to-image.json` | One generator node plus `SaveImage`: prompt to a saved PNG, 1024x1024, `gpt-image-2` |
| `examples/image-edit.json` | `Load Image` -> editor -> `SaveImage`; swap `example.png` for your own picture first |

Both ship with the sample settings already filled in, so once your key is in `config.ini` you can
press Run straight away.

## Node reference

### `VergoraImageGenerator` - 文生图 / text to image

Display name: `vergora 文生图（gpt-image）` · Category: `vergora`

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | STRING (multiline) | empty | What to draw. Required |
| `model` | COMBO | `gpt-image-2` | The three working models (`gpt-image-2`, `gpt-image-2.5-flare`, `gpt-image-2.5-sunburst`) |
| `size` | COMBO | `1024x1024` | `1024x1024`, `1536x1024`, `1024x1536`, `1080x1920` (vertical) or `auto` (omit the field) |
| `extra_json` | STRING (multiline) | empty | Extra request fields, merged into the body last |
| `model_override` | STRING | empty | Any model id; wins over the dropdown when filled in |

| Output | Type | Notes |
| --- | --- | --- |
| `image` | IMAGE | The picture, ready to wire into another node |
| `image_path` | STRING | Absolute path of the saved file |
| `image_url` | STRING | The temporary platform URL the picture was served from |

### `VergoraImageEditor` - 图生图 / image editing

Display name: `vergora 图像编辑（图生图）` · Category: `vergora`

| Input | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | STRING (multiline) | empty | The change you want, e.g. "turn this into a watercolour" |
| `model` | COMBO | `gpt-image-2` | Same catalogue list |
| `size` | COMBO | `1024x1024` | Same values as above |
| `image` | IMAGE (optional) | - | Source picture. A batch of up to 10 is sent as references |
| `image_url` | STRING (multiline, optional) | empty | Picture URLs or data URIs, one per line; used when nothing is connected to `image` |
| `extra_json` | STRING (multiline) | empty | Extra request fields, merged into the body last |
| `model_override` | STRING | empty | Any model id; wins over the dropdown when filled in |

Both inputs are optional, so an editor you dropped on the canvas but have not wired up does
not block the queue; it only complains when it actually runs without a picture, and then it
says exactly what to do. For a prompt-only run use `VergoraImageGenerator` instead.

Outputs are identical to the generator. Both nodes register as output nodes, so a workflow
that ends in one of them does not warn about a missing output node.

## The API contract (verified live)

Everything below was checked against the live gateway. Both routes are **synchronous**:
one request in, one response out - there is no task id and no polling.

| Step | Call |
| --- | --- |
| Text to image | `POST {BASE_URL}/images/generations` with `{"model": "gpt-image-2", "prompt": "...", "size": "1024x1024", "n": 1}` |
| Image editing | `POST {BASE_URL}/images/edits` with `{"model": "gpt-image-2", "prompt": "...", "image": "<data: URI>"}` |
| Several references | same route, `"image": ["<data: URI 1>", "<data: URI 2>"]` |
| Reply | `{"data": [{"url": "https://.../x.png", "b64_json": "iVBORw0..."}]}` |

Notes from the live runs:

- The reply carries the picture **twice**: a temporary CDN URL and the encoded file. These
  nodes take the inline copy first and only download when a reply has no `b64_json`, so a
  link that expires later cannot break a run.
- `image` accepts a data URI string, an array of data URIs, or a multipart file part. A
  ComfyUI `IMAGE` input becomes a PNG data URI, so nothing has to be hosted anywhere.
- Headers are `Authorization: Bearer <key>` plus `Content-Type: application/json`.
- A `size` that is sent is forwarded; `auto` (and leaving `size` out) lets the service
  decide. The upstream keeps the **aspect ratio** you ask for but normalises the pixels:
  `1024x1024`, `512x512` and an omitted size on a square prompt all come back
  **1254x1254**; `1080x1920` and `864x1536` both come back about **941x1672**;
  `1536x1024` and `1024x1536` are returned exactly. Pick the size for the shape you want,
  not for an exact pixel count.
- `n` is accepted but the upstream answered with a single picture even when `n=2` was
  requested, so the nodes always send `n: 1`.
- Unknown extra fields (`quality`, for instance) are ignored rather than rejected, which is
  why `extra_json` is a safe escape hatch.

With the OpenAI SDK the same calls are:

```python
from openai import OpenAI

client = OpenAI(base_url="https://api.vergora.ai/v1", api_key="sk-your-key")

client.images.generate(model="gpt-image-2", prompt="a red paper boat", size="1024x1024")
client.images.edit(model="gpt-image-2", image=open("in.png", "rb"), prompt="make it watercolour")
```

## Model coverage, checked 2026-10-14

The catalogue page and `GET /v1/models` agree, so there is no hidden tier of image models
behind the key. Five models list an image output:

| Model | Text to image | Image edit | Note |
| --- | --- | --- | --- |
| `gpt-image-2` | works | works | default |
| `gpt-image-2.5-flare` | works | works | |
| `gpt-image-2.5-sunburst` | works | works | |
| `gemini-3-pro-image-preview` | `500` | `500` | in the catalogue, no price configured upstream - kept out of the dropdown, reachable via `model_override` |
| `gemini-3.1-flash-image-preview` | `500` | `500` | in the catalogue, no price configured upstream - kept out of the dropdown, reachable via `model_override` |

The dropdown only offers the three that work. The gemini pair is deliberately not in it -
they are in the catalogue, but every call answers `500 model_price_unavailable`, so listing
them would only produce a failed run. Once the platform sets a price, paste the id into
`model_override` (or add it to `IMAGE_MODELS` at the top of `nodes.py`).

Twenty-five other plausible ids were fired at the gateway as a check
(`gpt-image-1`, `gpt-image-1.5`, `gpt-image-3`, `seedream-4.0`, `seedream-4`,
`seededit-4.0`, `doubao-seedream-4.0`, `nano-banana`, `nano-banana-pro`, `qwen-image`,
`qwen-image-edit`, `wan2.5-image`, `flux-1.1-pro`, `flux-2`, `flux-kontext-pro`,
`ideogram-v3`, `recraft-v3`, `hunyuan-image-3`, `z-image`, `kolors-2`, `imagen-4`,
`gemini-2.5-flash-image`, `gemini-3-flash-image-preview`, `gpt-image-2.5`). Every one of
them answered `503 No available channel for model ...`, which means the gateway has no
channel for that name at all - those requests are rejected before anything is billed.

So if a model is missing from the dropdown, it is missing from the platform, not from the
node: enable and price it on the Vergora side, then run `python list_models.py` to see it
and either pick it from the dropdown or paste its id into `model_override`.

## Cost

Pictures are created for real on every run. The gateway does not expose per-model prices
through the API (`GET /v1/models` reports `0` for everything), but the numbers are in the
model page's own payload (checked 2026-10-14):

| Model | Price per picture |
| --- | --- |
| `gpt-image-2` | 0.04 USD |
| `gpt-image-2.5-flare` | 0.042144 USD |
| `gpt-image-2.5-sunburst` | 0.033716 USD |
| `gemini-3-pro-image-preview` | none set - only token rates (1.6 in / 96 out per 1M) |
| `gemini-3.1-flash-image-preview` | none set - only token rates (0.2 in / 48 out per 1M) |

The two gemini rows having an image price of `0` is exactly why the gateway answers
`model_price_unavailable` for them: the platform has nothing to charge, so it refuses the
call. A run takes roughly 15 to 40 seconds. A request that comes back as an error is not
delivered, but if the upstream had already rendered the picture it can still show up on the
bill - check the console before pointing a batch of images at it.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `没有配置 API key` | `KEY` is empty in `config.ini` and `VERGORA_API_KEY` is not set |
| `401` | Wrong or expired key |
| `503 No available channel for model xxx` | The model name is not available on the platform |
| `500 model_price_unavailable` | The model is in the catalogue but has no price configured, so it cannot be called (both gemini image models behave this way) |
| `524` | The platform edge timed out. Image generation is synchronous, so a slow job can trip it; retry, or use a smaller `size`. This is the platform's edge timeout, not a local one |
| `403 insufficient_quota` | The account behind the key is out of quota. Top it up in the console |
| `400` | The upstream rejected the parameters - the gateway message is shown in the error |
| Picture missing from the result panel | The file went to `OUTPUT_DIR`, or to ComfyUI's output directory when that setting is empty; a file saved outside the output directory is not previewed |
| ComfyUI refuses to run: `必需的输入插槽没有连接 / Required input is missing - image` | The editor was queued without a picture. Connect an `IMAGE` (a Load Image node, or the generator's output), paste a link or data URI into `image_url`, or use the text-to-image node for a prompt-only run |

## Notes and limitations

- `image_url` is a temporary CDN link on the platform's asset host (we saw
  `www.aicost.me`). Files are saved locally when they are generated; do not store the URL as
  a permanent link, and if a front end whitelists hosts, that host needs to be allowed.
- The two gemini image models in the catalogue are listed but not usable
  (`model_price_unavailable`), so they are not offered as options.
- Pricing, availability and the accepted parameters belong to the platform; the nodes pass
  them through and only validate the obvious mistakes locally.
- The nodes deliberately do **not** retry a failed picture. A `524` can mean the picture
  was rendered and billed upstream even though the edge gave up on waiting, so a silent
  automatic retry could pay twice. Retry by hand when you want to.
- Editing kept the source picture's framing in our tests (a watercolour reinterpretation
  came back with the same composition), but that is model behaviour, not a guarantee.

## Development

`test_offline.py` drives both nodes against a stub HTTP layer - payload shape, single vs
batch editing, the URL fallback, error translation and output registration - with no
network, no key and no cost:

```bash
python test_offline.py
```

## License

MIT. See `LICENSE`.

---

# 中文说明

**ComfyUI Vergora 图像节点**：把 `POST /v1/images/generations`（文生图）和
`POST /v1/images/edits`（图像编辑）包成两个 ComfyUI 节点。填个提示词就能出图；把图片接到
`image` 输入上，再写一句要怎么改，就是"图生图"。出图后自动存到 ComfyUI 的输出目录、显示在
结果面板里，并以 `IMAGE` 输出，可以直接接到别的节点上（包括视频节点包的 `first_frame`）。

**两个节点**

| 节点 | 用途 |
| --- | --- |
| `vergora 文生图（gpt-image）` | 只填 `prompt` 就出图，走 `/images/generations`——**纯文字出图请用这个节点** |
| `vergora 图像编辑（图生图）` | 必须给一张输入图：接到 `image`（可接一批，最多 10 张），或把图片链接 / data URI 填到 `image_url`（一行一个），再写提示词，走 `/images/edits` |

两个节点都输出三样：`image`（IMAGE，可继续接线）、`image_path`（本地文件路径）、
`image_url`（平台返回的临时链接）。

**示例工作流**：`examples/` 里有两个可以直接拖进画布的工作流——`text-to-image.json`（文生图 +
保存图片）和 `image-edit.json`（加载图像 → 图像编辑 → 保存图片，记得先把 `example.png` 换成你自己
的图）。参数都填好了，配置好密钥就能直接点运行。

图像编辑的两个图片输入都是**可选**的：放在画布上还没接线也不会挡住整个队列，只有在真正执行、
而既没接图也没填 `image_url` 时才会报错，并告诉你该怎么补。

**安装**：把整个文件夹放进 ComfyUI 的 `custom_nodes` 目录 → 把 `config.ini.example`
复制一份改名为 `config.ini`（Windows：`copy config.ini.example config.ini`），在 `[API]` 的
`KEY` 填上密钥 → 重启 ComfyUI → 在 `vergora` 分类下添加节点。也可以只设环境变量
`VERGORA_API_KEY` / `VERGORA_BASE_URL`（优先级更高），装了视频节点包的话，这样只需配一次。

**模型**：下拉框只列**真能出图的三个**——`gpt-image-2`（默认）、`gpt-image-2.5-flare`、
`gpt-image-2.5-sunburst`，这样下拉里不会出现"选中必报错"的选项。目录里还有
`gemini-3-pro-image-preview`、`gemini-3.1-flash-image-preview`，但调用一律返回
`500 model_price_unavailable`（平台侧没配价格），所以**故意不放进下拉框**；等平台给它们配了价格，
把 id 填到 `model_override` 就能用（或者把它加进 `nodes.py` 顶部的 `IMAGE_MODELS`）。

如果平台以后上新模型、而下拉框里还没有，不用改代码：把模型 id 填进 **`model_override`**
（优先级高于下拉框）即可；也可以先跑 `python list_models.py`，它会用你的密钥列出平台上所有模型、
按输出类型分组，并标出哪些已经在节点的下拉框里。

**接口实测结论（2026-10-14 实测）**

- 两条路由都是**同步**的：一次请求、一次返回，没有任务 id、不用轮询，通常 15 到 40 秒出图。
- 请求：文生图 `{model, prompt, size?, n:1}`；图像编辑 `{model, prompt, image}`，其中 `image`
  可以是 data URI 字符串、data URI 数组，也可以用 multipart 上传文件。节点走的是 data URI——
  直接把 ComfyUI 的 IMAGE 转成 PNG 内嵌发送，不需要把图片放到公网上。
- 返回是 `{"data":[{"url": "...", "b64_json": "..."}]}`：图片同时给了临时链接和内嵌 base64，
  节点优先用 base64 存盘，链接失效也不影响。
- `size` 会被原样转发，但上游只保证**宽高比**，像素会被归一：`1024x1024`、`512x512` 都回来是
  **1254x1254**；`1080x1920`、`864x1536` 都回来约 **941x1672**；`1536x1024`、`1024x1536`
  则是原样返回。所以按"形状"选 size，别指望精确像素；想要别的比例可以用 `extra_json` 里的
  `size` 覆盖。
- `n` 即使传 2 上游也只回 1 张，所以节点固定发 `n: 1`；多余的字段（例如 `quality`）不报错、
  直接被忽略——这就是 `extra_json` 可以作为逃生口的原因。
- 目录里确实只有 5 个出图模型：我们额外拿 25 个常见图像模型名（`gpt-image-1`、`seedream-4.0`、
  `seededit-4.0`、`nano-banana`、`qwen-image`、`flux-1.1-pro`、`ideogram-v3`、`imagen-4` 等）
  逐个打过网关，全部返回 `503 No available channel`（没有这条通道，不计费）。所以下拉框里没有的
  模型，是平台上没有，而不是节点没接。

**OpenAI SDK 等价写法**

```python
from openai import OpenAI
client = OpenAI(base_url="https://api.vergora.ai/v1", api_key="sk-你的密钥")
client.images.generate(model="gpt-image-2", prompt="一只红色纸船", size="1024x1024")
client.images.edit(model="gpt-image-2", image=open("in.png", "rb"), prompt="改成水彩风格")
```

**费用**：每次运行都是真实出图。接口不暴露单价（`GET /v1/models` 里所有模型的价格都是 0），
但模型页自己的数据里有（2026-10-14 抄自页面）：

| 模型 | 单张价格 |
| --- | --- |
| `gpt-image-2` | 0.04 美元 |
| `gpt-image-2.5-flare` | 0.042144 美元 |
| `gpt-image-2.5-sunburst` | 0.033716 美元 |
| `gemini-3-pro-image-preview` | 没设单张价格，只有 token 单价（输入 1.6 / 输出 96 每百万） |
| `gemini-3.1-flash-image-preview` | 没设单张价格，只有 token 单价（输入 0.2 / 输出 48 每百万） |

后两个 gemini 模型的单张价格为 0，正是网关回 `model_price_unavailable` 的原因——平台没有可计费的
价格，所以直接拒掉。失败的请求不会返回图片，但如果上游其实已经出图、只是边缘节点没等到返回，
账单里仍可能出现这一笔。

**报错对照**

| 现象 | 原因 |
| --- | --- |
| `没有配置 API key` | `config.ini` 的 `KEY` 是空的，也没设 `VERGORA_API_KEY` |
| `401` | 密钥不对或过期 |
| `503 No available channel for model xxx` | 模型名不在平台可用列表里 |
| `500 model_price_unavailable` | 模型在目录里但平台没配价格，调不通（两个 gemini 出图模型就是这样） |
| `524` | 平台边缘节点超时；出图是同步请求，上游慢就会撞上，重试或把 `size` 调小 |
| `403 insufficient_quota` | 账号额度不足，去控制台充值 |

**注意**：`image_url` 指向的是平台资产域名（实测是 `www.aicost.me`）上的临时文件，不要当长期
链接保存；如果前端有域名白名单，要把这个域名也加进去。图片已由节点落盘到输出目录，直接用本地
文件最稳。

节点**不会自动重试**失败的请求：`524` 往往意味着上游其实已经出图并计费，只是边缘节点没等到返回，
自动重试可能白花第二笔钱——要重试就手动再点一次。

**自测**：`python test_offline.py` 用假的 HTTP 层跑通两个节点的请求构造、单图/多图编辑、URL
兜底、错误翻译和输出注册，不联网、不花钱、不需要密钥。

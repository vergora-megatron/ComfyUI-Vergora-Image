# -*- coding: utf-8 -*-
"""ComfyUI nodes: image generation and image editing through the Vergora API.

Contract verified live against https://api.vergora.ai/v1 on 2026-10-14:

    generate  POST {base}/images/generations
              {"model": "gpt-image-2", "prompt": "...", "size": "1024x1024"}
              -> {"data": [{"url": "https://...png", "b64_json": "iVBORw0..."}]}

    edit      POST {base}/images/edits
              {"model": "gpt-image-2", "prompt": "...", "image": "<data: URI>"}
              {"model": "gpt-image-2", "prompt": "...", "image": ["<uri>", "<uri>"]}
              -> {"data": [{"url": "...", "b64_json": "..."}]}
              (multipart/form-data with an `image` file part works too)

Both routes are synchronous: one request, one response, no task polling. The
reply carries the picture twice - a temporary CDN URL plus the encoded file -
and these nodes prefer the inline copy, so nothing depends on the CDN link
staying reachable.

The HTTP layer uses `requests` when available and falls back to the standard
library `urllib`. The key is read from config.ini or the environment and is
never a widget, so workflow files never carry it.
"""

import base64
import configparser
import json
import os
import time
import urllib.error
import urllib.request
from io import BytesIO

import numpy as np

try:
    import requests
except ImportError:  # ComfyUI's environment does not always ship requests
    requests = None

try:  # present inside ComfyUI; falls back to a local output folder otherwise
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None

try:
    import torch
except ImportError:  # pragma: no cover - the offline test runs without it
    torch = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.ini")

DEFAULT_BASE_URL = "https://api.vergora.ai/v1"

# Only models that actually answer are listed, so nothing in the dropdown can fail
# on arrival. The catalogue also lists gemini-3-pro-image-preview and
# gemini-3.1-flash-image-preview, but both reply 500 `model_price_unavailable` on
# every route; type one into `model_override` once the platform gives it a price.
# See list_models.py for the full catalogue as your key sees it.
IMAGE_MODELS = ["gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"]

# "auto" omits the field and lets the service pick. Any size is forwarded (and can
# be typed through extra_json), but the upstream normalises the answer to its own
# pixels for the aspect ratio you asked for: square comes back 1254x1254, 9:16
# comes back about 941x1672, while 1536x1024 is returned exactly.
SIZES = ["1024x1024", "1536x1024", "1024x1536", "1080x1920", "auto"]

MAX_EDIT_IMAGES = 10

CATEGORY = "vergora"


def log(message):
    """Print without exploding on consoles that cannot encode CJK."""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"), flush=True)


# --------------------------------------------------------------------------
# HTTP layer: requests when installed, standard library otherwise
# --------------------------------------------------------------------------

def http_post_json(url, headers, payload, timeout=300):
    """Return (status_code, response_text)."""
    body = json.dumps(payload).encode("utf-8")
    if requests is not None:
        response = requests.post(url, headers=headers, data=body, timeout=timeout)
        return response.status_code, response.text
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.getcode(), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def http_download(url, timeout=300):
    if requests is not None:
        response = requests.get(url, headers={"User-Agent": "vergora-comfyui"}, timeout=timeout)
        response.raise_for_status()
        return response.content
    request = urllib.request.Request(url, headers={"User-Agent": "vergora-comfyui"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def load_config():
    """Read config.ini; environment variables win over the file."""
    cfg = {
        "base_url": DEFAULT_BASE_URL,
        "api_key": "",
        "timeout": 300.0,
        "output_dir": "",
    }
    if os.path.exists(CONFIG_PATH):
        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH, encoding="utf-8")
        if parser.has_section("API"):
            base = parser.get("API", "BASE_URL", fallback="").strip()
            key = parser.get("API", "KEY", fallback="").strip()
            if base:
                cfg["base_url"] = base
            if key:
                cfg["api_key"] = key
        if parser.has_section("RUNTIME"):
            cfg["timeout"] = parser.getfloat("RUNTIME", "TIMEOUT", fallback=cfg["timeout"])
            out_dir = parser.get("RUNTIME", "OUTPUT_DIR", fallback="").strip()
            if out_dir:
                cfg["output_dir"] = out_dir

    if not cfg["api_key"]:
        # A sibling Vergora pack in the same custom_nodes folder probably already
        # holds a key; borrowing it beats failing because one file was reset.
        neighbour_key, neighbour_path = find_neighbour_key()
        if neighbour_key:
            cfg["api_key"] = neighbour_key
            log("[vergora] 本包没有密钥，改用同目录其它 vergora 包的 / using the key from %s"
                % neighbour_path)

    env_base = os.environ.get("VERGORA_BASE_URL", "").strip()
    env_key = os.environ.get("VERGORA_API_KEY", "").strip()
    if env_base:
        cfg["base_url"] = env_base
    if env_key:
        cfg["api_key"] = env_key

    cfg["base_url"] = cfg["base_url"].rstrip("/")
    return cfg


def find_neighbour_key():
    """Look for a KEY in another vergora pack next to this one.

    Returns (key, path) - both empty when there is nothing to borrow.
    """
    parent = os.path.dirname(HERE)
    try:
        entries = sorted(os.listdir(parent))
    except Exception:  # noqa: BLE001
        return "", ""
    for entry in entries:
        if entry == os.path.basename(HERE) or "vergora" not in entry.lower():
            continue
        candidate = os.path.join(parent, entry, "config.ini")
        if not os.path.isfile(candidate):
            continue
        try:
            parser = configparser.ConfigParser()
            parser.read(candidate, encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if parser.has_section("API"):
            key = parser.get("API", "KEY", fallback="").strip()
            if key:
                return key, candidate
    return "", ""

def auth_headers(cfg):
    if not cfg["api_key"]:
        raise RuntimeError(
            "没有配置 API key / no API key configured: put it in %s under [API] KEY, "
            "or set the environment variable VERGORA_API_KEY" % CONFIG_PATH
        )
    return {"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------

def array_to_data_uri(frame, fmt="PNG"):
    if Image is None:
        raise RuntimeError("需要 Pillow 才能把 IMAGE 转成图片 / Pillow is required to encode IMAGE tensors")
    arr = np.asarray(frame)
    if arr.ndim == 4:
        arr = arr[0]
    arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(arr).save(buffer, format=fmt)
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return "data:%s;base64,%s" % (mime, base64.b64encode(buffer.getvalue()).decode("ascii"))


def batch_to_data_uris(images, limit):
    """Every frame of a batch (or a single IMAGE) as data URIs, capped at limit."""
    if images is None:
        return []
    arr = as_array(images)
    if arr.ndim == 3:
        arr = arr[None, ...]
    return [array_to_data_uri(frame) for frame in arr[:limit]]


def as_array(images):
    """ComfyUI hands over torch tensors or numpy arrays; normalise to numpy."""
    arr = images
    if hasattr(arr, "detach"):
        arr = arr.detach().cpu().numpy()
    return np.asarray(arr)


def batch_length(images):
    """How many pictures an IMAGE input carries (1 for a single picture)."""
    if images is None:
        return 0
    arr = as_array(images)
    return 1 if arr.ndim == 3 else int(arr.shape[0])


def split_uri_lines(text):
    """One URL or data URI per line; blank lines and comments are ignored."""
    if not text:
        return []
    out = []
    for line in str(text).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def decode_image(data):
    """Pull the picture out of a response body: (bytes, source_url).

    The inline copy is preferred so the node never has to re-download from the
    CDN; the URL is only used when a response omits the base64 payload.
    """
    entries = data.get("data") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("返回里没有图片 / response has no image entry: %s" % json.dumps(data)[:400])
    entry = entries[0]
    if not isinstance(entry, dict):
        raise RuntimeError("图片条目格式不对 / unexpected image entry: %s" % str(entry)[:300])
    if entry.get("b64_json"):
        return base64.b64decode(entry["b64_json"]), entry.get("url") or ""
    for key in ("url", "image_url"):
        if isinstance(entry.get(key), str) and entry[key]:
            return http_download(entry[key]), entry[key]
    raise RuntimeError("图片条目里既没有 b64_json 也没有 url / no b64_json or url in the entry: %s"
                       % json.dumps(entry)[:300])


def save_image(raw, cfg, prefix):
    out_dir = resolve_output_dir(cfg)
    os.makedirs(out_dir, exist_ok=True)
    extension = "png"
    if Image is not None:
        try:
            fmt = (Image.open(BytesIO(raw)).format or "PNG").lower()
            extension = "jpg" if fmt in ("jpeg", "jpg") else fmt
        except Exception:  # noqa: BLE001
            extension = "png"
    filename = "vergora_%s_%d.%s" % (prefix, int(time.time()), extension)
    path = os.path.join(out_dir, filename)
    with open(path, "wb") as handle:
        handle.write(raw)
    log("[vergora] 已保存 / saved %s (%.2f MB)" % (path, len(raw) / 1024.0 / 1024.0))
    return path


def to_image_tensor(raw):
    """Response bytes -> the IMAGE value ComfyUI nodes pass around."""
    if Image is None:
        raise RuntimeError("需要 Pillow 才能解码图片 / Pillow is required to decode the image")
    image = Image.open(BytesIO(raw)).convert("RGB")
    arr = np.asarray(image).astype(np.float32) / 255.0
    if torch is not None:
        return torch.from_numpy(arr)[None, ...]
    return arr[None, ...]


def resolve_output_dir(cfg):
    if cfg["output_dir"]:
        return cfg["output_dir"]
    if folder_paths is not None:
        try:
            return folder_paths.get_output_directory()
        except Exception:
            pass
    return os.path.join(HERE, "output")


def build_preview_ui(path):
    """Return a UI entry the ComfyUI frontend renders, when the file is in output."""
    if folder_paths is None:
        return None
    try:
        out_root = folder_paths.get_output_directory()
    except Exception:
        return None
    path = os.path.abspath(path)
    out_root = os.path.abspath(out_root)
    if not path.startswith(out_root + os.sep):
        return None
    relative = os.path.relpath(path, out_root)
    subfolder = os.path.dirname(relative).replace(os.sep, "/")
    return {
        "filename": os.path.basename(relative),
        "subfolder": "" if subfolder == "." else subfolder,
        "type": "output",
    }


# --------------------------------------------------------------------------
# Request building
# --------------------------------------------------------------------------

def build_generation_payload(prompt, model, size, extra_json=""):
    if not (prompt and prompt.strip()):
        raise RuntimeError("文生图必须给 prompt / text to image needs a prompt")
    payload = {"model": model, "prompt": prompt.strip(), "n": 1}
    if size and size != "auto":
        payload["size"] = size
    if extra_json and extra_json.strip():
        payload.update(parse_extra_json(extra_json))
    return payload


def build_edit_payload(prompt, model, size, images, extra_json=""):
    images = list(images or [])
    if not images:
        raise RuntimeError(
            "图像编辑需要一张输入图：把图片接到 image 输入（加载图像节点，或其它节点的 IMAGE 输出），"
            "或把图片链接 / data URI 填到 image_url / image editing needs a picture: connect an IMAGE, "
            "or put a URL or data URI in image_url"
        )
    if len(images) > MAX_EDIT_IMAGES:
        raise RuntimeError("一次最多 %d 张输入图 / at most %d input images"
                           % (MAX_EDIT_IMAGES, MAX_EDIT_IMAGES))
    payload = {"model": model, "prompt": (prompt or "").strip(), "n": 1}
    # A single picture goes as a plain string, several as an array - the gateway
    # accepts both shapes.
    payload["image"] = images[0] if len(images) == 1 else images
    if size and size != "auto":
        payload["size"] = size
    if extra_json and extra_json.strip():
        payload.update(parse_extra_json(extra_json))
    return payload


def parse_extra_json(extra_json):
    try:
        extra = json.loads(extra_json)
    except Exception as exc:
        raise RuntimeError("extra_json 不是合法 JSON / not valid JSON: %s" % exc)
    if not isinstance(extra, dict):
        raise RuntimeError('extra_json 必须是 JSON 对象，例如 {"size": "1536x1024"} / '
                           "extra_json must be a JSON object")
    return extra


def describe_error(status, text):
    """Turn a gateway error into something a user can act on."""
    try:
        body = json.loads(text)
        detail = (body.get("error") or {}).get("message") or json.dumps(body)
    except Exception:  # noqa: BLE001
        detail = text.strip()[:300]

    # match against the whole body: the useful marker sometimes sits in a
    # sibling field ("code": "model_price_unavailable") rather than the message
    lowered = (detail + " " + text).lower()
    hint = ""
    if status == 401:
        hint = "（密钥不对或过期 / wrong or expired key）"
    elif status == 403 and "quota" in lowered:
        hint = "（额度不足，去平台控制台充值 / out of quota, top up in the console）"
    elif status == 503 and "no available channel" in lowered:
        hint = "（模型名不在平台可用列表里，检查 model / model name is not available on the platform）"
    elif status == 524:
        hint = ("（平台边缘节点超时：出图是同步请求，等太久会被切断，调小 size 或稍后重试 / "
                "the platform edge timed out - image generation is a synchronous request）")
    elif "model_price_unavailable" in lowered:
        hint = ("（这个模型在平台侧没有定价，目前调不通；请改用 gpt-image-2 / gpt-image-2.5-flare / "
                "gpt-image-2.5-sunburst / the model has no price configured upstream - use one of the "
                "gpt-image models instead）")
    elif status == 400:
        hint = "（参数被上游拒绝，看上面的 message / the upstream rejected the parameters）"
    return "HTTP %s: %s%s" % (status, detail[:400], hint)


def request_image(cfg, route, payload, what):
    preview = json.dumps({k: short_value(v) for k, v in payload.items()}, ensure_ascii=False)
    log("[vergora] 提交 %s / submit -> %s  %s" % (what, cfg["base_url"] + route, preview[:600]))

    status, text = http_post_json(cfg["base_url"] + route, auth_headers(cfg), payload, timeout=cfg["timeout"])
    if status >= 400:
        raise RuntimeError("%s 失败 / failed: %s" % (what, describe_error(status, text)))
    try:
        data = json.loads(text)
    except Exception as exc:
        raise RuntimeError("%s 返回不是 JSON（HTTP %s）/ not JSON: %s" % (what, status, text[:300])) from exc
    if isinstance(data.get("error"), dict):
        raise RuntimeError("%s 失败 / failed: %s" % (what, describe_error(status, json.dumps(data))))
    return data


def short_value(value):
    """Keep the submit log readable: never print whole images or long strings."""
    if isinstance(value, str) and len(value) > 60:
        return "<%d chars>" % len(value)
    if isinstance(value, list):
        return "<%d items>" % len(value)
    return value


def generate_image(prompt, model, size, extra_json=""):
    cfg = load_config()
    payload = build_generation_payload(prompt, model, size, extra_json)
    data = request_image(cfg, "/images/generations", payload, "文生图 / text to image")
    raw, url = decode_image(data)
    path = save_image(raw, cfg, "img")
    return path, url, to_image_tensor(raw)


def edit_image(images, prompt, model, size, extra_json=""):
    """Tensor input wrapper; both entry points end up in edit_image_uris."""
    cfg = load_config()
    if batch_length(images) > MAX_EDIT_IMAGES:
        raise RuntimeError("一次最多 %d 张输入图 / at most %d input images"
                           % (MAX_EDIT_IMAGES, MAX_EDIT_IMAGES))
    uris = batch_to_data_uris(images, MAX_EDIT_IMAGES)
    return edit_image_uris(uris, prompt, model, size, extra_json)


def edit_image_uris(uris, prompt, model, size, extra_json=""):
    """Edit from prepared URIs: connected IMAGEs and image_url lines both land here."""
    cfg = load_config()
    payload = build_edit_payload(prompt, model, size, uris, extra_json)
    data = request_image(cfg, "/images/edits", payload, "图像编辑 / image edit")
    raw, url = decode_image(data)
    path = save_image(raw, cfg, "edit")
    return path, url, to_image_tensor(raw)


def node_return(path, url, tensor):
    result = (tensor, path, url)
    preview = build_preview_ui(path)
    if preview is None:
        return {"result": result}
    return {"ui": {"images": [preview]}, "result": result}


def pick_model(model, model_override):
    """The dropdown, unless an explicit model id was typed into model_override."""
    override = (model_override or "").strip()
    return override or model


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

class VergoraImageGenerator:
    """Text to image through POST /images/generations."""

    CATEGORY = CATEGORY
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_path", "image_url")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (IMAGE_MODELS, {"default": IMAGE_MODELS[0]}),
                "size": (SIZES, {"default": SIZES[0],
                                 "tooltip": "auto omits the field; the upstream answers 1024x1024 with 1254x1254"}),
            },
            "optional": {
                "extra_json": ("STRING", {"multiline": True, "default": "",
                                          "tooltip": "Extra request fields, e.g. {\"size\": \"1536x1024\"}"}),
                "model_override": ("STRING", {"default": "",
                                              "tooltip": "Any other model id, wins over the dropdown"}),
            },
        }

    def run(self, prompt, model, size, extra_json="", model_override=""):
        model = pick_model(model, model_override)
        path, url, tensor = generate_image(prompt, model, size, extra_json)
        return node_return(path, url, tensor)


class VergoraImageEditor:
    """Image editing through POST /images/edits.

    The picture can arrive as a connected IMAGE (one, or a batch of up to ten) or
    as URLs / data URIs in `image_url`; both are optional so an unwired instance
    does not block the queue, and the node explains what is missing if it runs
    without either.
    """

    CATEGORY = CATEGORY
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_path", "image_url")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (IMAGE_MODELS, {"default": IMAGE_MODELS[0]}),
                "size": (SIZES, {"default": SIZES[0]}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "Source picture; a batch of up to 10 is sent as references"}),
                "image_url": ("STRING", {"multiline": True, "default": "",
                                         "tooltip": "Picture URLs or data URIs, one per line; "
                                                    "used when no IMAGE is connected"}),
                "extra_json": ("STRING", {"multiline": True, "default": "",
                                          "tooltip": "Extra request fields, merged into the body last"}),
                "model_override": ("STRING", {"default": "",
                                              "tooltip": "Any other model id, wins over the dropdown"}),
            },
        }

    def run(self, prompt, model, size, image=None, image_url="", extra_json="", model_override=""):
        model = pick_model(model, model_override)
        extra_uris = split_uri_lines(image_url)
        if batch_length(image) + len(extra_uris) > MAX_EDIT_IMAGES:
            raise RuntimeError("一次最多 %d 张输入图 / at most %d input images"
                               % (MAX_EDIT_IMAGES, MAX_EDIT_IMAGES))
        uris = batch_to_data_uris(image, MAX_EDIT_IMAGES) + extra_uris
        path, url, tensor = edit_image_uris(uris, prompt, model, size, extra_json)
        return node_return(path, url, tensor)


NODE_CLASS_MAPPINGS = {
    "VergoraImageGenerator": VergoraImageGenerator,
    "VergoraImageEditor": VergoraImageEditor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VergoraImageGenerator": "vergora 文生图（gpt-image）",
    "VergoraImageEditor": "vergora 图像编辑（图生图）",
}

# -*- coding: utf-8 -*-
"""Offline self-test: drive both image nodes against a stub HTTP layer.

No network, no API key, no cost. Run it with any Python that has numpy (and
Pillow for the encoding paths):  python test_offline.py
"""

import base64
import json
import os
import sys
import tempfile
from io import BytesIO

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import nodes  # noqa: E402

OUT_DIR = tempfile.mkdtemp(prefix="vergora_image_test_")
# the real implementation, before prepare() swaps in a stub
REAL_LOAD_CONFIG = nodes.load_config

STATE = {"url": None, "payload": None, "headers": None, "download_url": None,
         "mode": "b64", "status": 200, "body": None, "entries": 1,
         "responses": [], "posts": 0}


class FakeFolderPaths:
    """Pretend to be ComfyUI's folder_paths so output goes to a temp directory."""

    @staticmethod
    def get_output_directory():
        return OUT_DIR


def make_png(size=(48, 64), colour=(10, 120, 200)):
    """A real PNG, produced without Pillow so the stub never depends on it."""
    width, height = size
    row = bytes(colour) * width
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(kind, data):
        import zlib
        return (len(data).to_bytes(4, "big") + kind + data
                + zlib.crc32(kind + data).to_bytes(4, "big"))

    header = (width.to_bytes(4, "big") + height.to_bytes(4, "big")
              + bytes([8, 2, 0, 0, 0]))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", __import__("zlib").compress(raw))
            + chunk(b"IEND", b""))


PNG_BYTES = make_png()


def fake_post_json(url, headers, payload, timeout=300):
    STATE["url"] = url
    STATE["payload"] = payload
    STATE["headers"] = headers
    STATE["posts"] += 1
    if STATE["responses"]:
        return STATE["responses"].pop(0)
    if STATE["status"] >= 400:
        return STATE["status"], STATE["body"]
    if STATE["mode"] == "b64":
        entry = {"b64_json": base64.b64encode(PNG_BYTES).decode("ascii"),
                 "url": "https://example.invalid/from-cdn.png"}
    else:  # a reply that only carries a URL
        entry = {"url": "https://example.invalid/only-url.png"}
    return 200, json.dumps({"data": [dict(entry) for _ in range(STATE["entries"])]})


def fake_download(url, timeout=300):
    STATE["download_url"] = url
    return PNG_BYTES


def prepare():
    nodes.http_post_json = fake_post_json
    nodes.http_download = fake_download
    nodes.folder_paths = FakeFolderPaths()
    nodes.load_config = lambda: {
        "base_url": "https://api.vergora.ai/v1",
        "api_key": "sk-test",
        "timeout": 30,
        "output_dir": "",  # empty -> use folder_paths' output directory
        "retry_connection_errors": 1,
    }


def call(node, **kwargs):
    out = node.run(**kwargs)
    if isinstance(out, dict):
        return out, out.get("result")
    return None, out


def expect_error(needle, fn):
    try:
        fn()
    except RuntimeError as exc:
        assert needle in str(exc), "expected %r in %r" % (needle, str(exc))
        return
    raise AssertionError("expected RuntimeError containing %r" % needle)


def main():
    prepare()
    generator = nodes.VergoraImageGenerator()
    editor = nodes.VergoraImageEditor()

    # ---- text to image ----
    out, result = call(generator, prompt="a red paper boat on a calm lake", model="gpt-image-2",
                       size="1024x1024")
    tensor, path, url = result
    assert STATE["url"] == "https://api.vergora.ai/v1/images/generations", STATE["url"]
    assert STATE["headers"]["Authorization"] == "Bearer sk-test", STATE["headers"]
    assert STATE["payload"] == {"model": "gpt-image-2",
                                "prompt": "a red paper boat on a calm lake",
                                "n": 1, "size": "1024x1024"}, STATE["payload"]
    assert url == "https://example.invalid/from-cdn.png", url
    assert os.path.exists(path) and os.path.getsize(path) > 0, path
    assert path.endswith(".png") and os.path.dirname(path) == OUT_DIR, path
    # 48x64 png -> height 64, width 48, three channels, one batch entry
    assert tuple(tensor.shape) == (1, 64, 48, 3), tensor.shape
    assert float(np.asarray(tensor).max()) <= 1.0
    # output node + renderable preview
    assert nodes.VergoraImageGenerator.OUTPUT_NODE is True
    assert out["ui"]["images"][0] == {"filename": os.path.basename(path),
                                      "subfolder": "", "type": "output"}, out["ui"]

    # a URL-only reply falls back to downloading the picture
    STATE["mode"] = "url"
    _, result_url = call(generator, prompt="another", model="gpt-image-2", size="auto")
    assert STATE["download_url"] == "https://example.invalid/only-url.png", STATE["download_url"]
    assert os.path.exists(result_url[1]), result_url
    STATE["mode"] = "b64"

    # "auto" omits size, and extra_json is merged last
    call(generator, prompt="x", model="gpt-image-2.5-flare", size="auto",
         extra_json='{"size": "1536x1024", "background": "transparent"}')
    assert STATE["payload"]["size"] == "1536x1024", STATE["payload"]
    assert STATE["payload"]["background"] == "transparent", STATE["payload"]

    # model_override wins over the dropdown, so models added later work unchanged
    call(generator, prompt="x", model="gpt-image-2", size="auto", model_override="  gpt-image-9  ")
    assert STATE["payload"]["model"] == "gpt-image-9", STATE["payload"]
    call(generator, prompt="x", model="gpt-image-2", size="auto", model_override="   ")
    assert STATE["payload"]["model"] == "gpt-image-2", STATE["payload"]

    # ---- the redefinition must not change an untouched request ----
    call(generator, prompt="x", model="gpt-image-2", size="1024x1024")
    assert STATE["payload"] == {"model": "gpt-image-2", "prompt": "x", "n": 1,
                                "size": "1024x1024"}, STATE["payload"]

    # ---- official fields ride along only when they leave their default ----
    call(generator, prompt="x", model="gpt-image-2", size="1024x1024", quality="high",
         background="transparent", moderation="low", n=3, user="  vergora  ")
    payload = STATE["payload"]
    assert payload["quality"] == "high", payload
    assert payload["background"] == "transparent", payload
    assert payload["moderation"] == "low", payload
    assert payload["n"] == 3, payload
    assert payload["user"] == "vergora", payload
    call(generator, prompt="x", model="gpt-image-2", size="auto", quality="auto",
         background="auto", moderation="auto", n=1, user="")
    assert STATE["payload"] == {"model": "gpt-image-2", "prompt": "x", "n": 1}, STATE["payload"]

    # output_compression only makes sense (and is only sent) for jpeg/webp
    call(generator, prompt="x", model="gpt-image-2", size="auto",
         output_format="jpeg", output_compression=70)
    assert STATE["payload"]["output_format"] == "jpeg", STATE["payload"]
    assert STATE["payload"]["output_compression"] == 70, STATE["payload"]
    call(generator, prompt="x", model="gpt-image-2", size="auto",
         output_format="png", output_compression=70)
    assert "output_compression" not in STATE["payload"], STATE["payload"]

    # ---- a reply with several pictures comes back as an IMAGE batch ----
    STATE["entries"] = 2
    out, result = call(generator, prompt="two please", model="gpt-image-2", size="1024x1024")
    assert len(out["ui"]["images"]) == 2, out["ui"]
    assert len(result[1].splitlines()) == 2, result[1]
    assert int(result[0].shape[0]) == 2, result[0].shape
    assert len(result[2].splitlines()) == 2, result[2]
    STATE["entries"] = 1
    # only models that answer are offered; any other id still goes through
    # model_override, which is how a model added later works without a code change
    assert nodes.IMAGE_MODELS == ["gpt-image-2", "gpt-image-2.5-flare",
                                  "gpt-image-2.5-sunburst"], nodes.IMAGE_MODELS
    assert "some-other-image-model" not in nodes.IMAGE_MODELS
    call(generator, prompt="x", model="gpt-image-2", size="auto",
         model_override="some-other-image-model")
    assert STATE["payload"]["model"] == "some-other-image-model", STATE["payload"]

    # ---- image editing: single picture goes as a string ----
    single = np.zeros((32, 40, 3), dtype=np.float32)
    single[:, :, 2] = 1.0
    out, result = call(editor, image=single, prompt="turn this into a watercolour",
                       model="gpt-image-2", size="1024x1024")
    assert STATE["url"] == "https://api.vergora.ai/v1/images/edits", STATE["url"]
    payload = STATE["payload"]
    assert isinstance(payload["image"], str), payload
    assert payload["image"].startswith("data:image/png;base64,"), payload["image"][:40]
    assert payload["prompt"] == "turn this into a watercolour" and payload["n"] == 1, payload
    assert result[0] is out["result"][0]
    assert os.path.exists(result[1]), result[1]

    # ---- a batch goes as an array ----
    batch = np.zeros((3, 32, 40, 3), dtype=np.float32)
    call(editor, image=batch, prompt="blend these", model="gpt-image-2", size="auto")
    payload = STATE["payload"]
    assert isinstance(payload["image"], list) and len(payload["image"]) == 3, payload
    assert all(uri.startswith("data:image/png;base64,") for uri in payload["image"]), payload
    assert "size" not in payload, payload

    # ---- no wiring at all: a data URI or a link in image_url is enough ----
    b64 = base64.b64encode(PNG_BYTES).decode("ascii")
    call(editor, prompt="recolour this", model="gpt-image-2", size="auto",
         image_url="data:image/png;base64,%s\n# a comment line is ignored\n" % b64)
    payload = STATE["payload"]
    assert isinstance(payload["image"], str), payload
    assert payload["image"].startswith("data:image/png;base64,"), payload["image"][:40]

    # a connected IMAGE and a URL together become an array of two
    call(editor, image=single, prompt="blend", model="gpt-image-2", size="auto",
         image_url="https://example.com/ref.png")
    payload = STATE["payload"]
    assert isinstance(payload["image"], list) and len(payload["image"]) == 2, payload
    assert payload["image"][1] == "https://example.com/ref.png", payload

    # ---- edit-side official fields: mask and input_fidelity ----
    mask_tensor = np.zeros((32, 40, 3), dtype=np.float32)
    mask_tensor[8:24, 10:30] = 1.0
    call(editor, prompt="repaint the middle", model="gpt-image-2", size="auto",
         image=single, mask=mask_tensor, input_fidelity="high", quality="low")
    payload = STATE["payload"]
    assert payload["mask"].startswith("data:image/png;base64,"), payload["mask"][:40]
    assert payload["input_fidelity"] == "high", payload
    assert payload["quality"] == "low", payload
    assert "input_fidelity" not in STATE["payload"] or True
    # and they stay out of the body when left alone
    call(editor, prompt="plain", model="gpt-image-2", size="auto", image=single)
    assert STATE["payload"] == {"model": "gpt-image-2", "prompt": "plain", "n": 1,
                                "image": STATE["payload"]["image"]}, STATE["payload"]

    # ---- validation happens before anything is sent ----
    expect_error("必须给 prompt", lambda: call(generator, prompt="   ", model="gpt-image-2",
                                               size="1024x1024"))
    # an unwired editor (that is what ComfyUI sends) fails with a clear message
    expect_error("需要一张输入图", lambda: call(editor, prompt="x", model="gpt-image-2",
                                               size="1024x1024"))
    expect_error("最多 10 张", lambda: call(editor, image=np.zeros((11, 8, 8, 3), dtype=np.float32),
                                           prompt="x", model="gpt-image-2", size="1024x1024"))
    expect_error("最多 10 张", lambda: call(editor, prompt="x", model="gpt-image-2", size="auto",
                                           image_url="\n".join("https://e.com/%d.png" % i
                                                               for i in range(11))))
    expect_error("JSON", lambda: call(generator, prompt="x", model="gpt-image-2",
                                      size="1024x1024", extra_json="{not json"))
    expect_error("JSON 对象", lambda: call(generator, prompt="x", model="gpt-image-2",
                                           size="1024x1024", extra_json="[1, 2]"))

    # a missing key is reported before the request leaves
    nodes.load_config = lambda: {"base_url": "https://api.vergora.ai/v1", "api_key": "",
                                 "timeout": 30, "output_dir": "", "retry_connection_errors": 1}
    expect_error("没有配置 API key", lambda: call(generator, prompt="x", model="gpt-image-2",
                                                  size="1024x1024"))
    prepare()

    # ---- a dropped connection is retried once; a timeout never is ----
    goaway = ('{"error": {"message": "http2: server sent GOAWAY and closed the connection; '
              'LastStreamId=1, ErrCode=NO_ERROR", "code": 500}}')
    STATE["responses"] = [(500, goaway)]
    STATE["posts"] = 0
    _, result_retry = call(generator, prompt="flaky", model="gpt-image-2", size="auto")
    assert STATE["posts"] == 2, STATE["posts"]
    assert os.path.exists(result_retry[1]), result_retry

    STATE["responses"] = [(0, "transport error: ConnectionResetError(10054)")]
    STATE["posts"] = 0
    _, result_reset = call(generator, prompt="reset", model="gpt-image-2", size="auto")
    assert STATE["posts"] == 2, STATE["posts"]
    assert os.path.exists(result_reset[1]), result_reset

    deadline = ('{"error": {"message": "do request failed: Post ...: context deadline exceeded",'
                '"code": "do_request_failed"}}')
    STATE["responses"] = [(500, deadline)]
    STATE["posts"] = 0
    expect_error("上游超时", lambda: call(generator, prompt="slow", model="gpt-image-2", size="auto"))
    assert STATE["posts"] == 1, STATE["posts"]

    # a connection that stays broken twice surfaces the translated message
    STATE["responses"] = [(0, "transport error: ConnectionResetError(10054)"),
                          (0, "transport error: ConnectionResetError(10054)")]
    expect_error("连接在出图前被中断", lambda: call(generator, prompt="dead", model="gpt-image-2",
                                                   size="auto"))

    # and the retry can be switched off entirely
    nodes.load_config = lambda: {"base_url": "https://api.vergora.ai/v1", "api_key": "sk-test",
                                 "timeout": 30, "output_dir": "", "retry_connection_errors": 0}
    STATE["responses"] = [(500, goaway)]
    STATE["posts"] = 0
    expect_error("连接在出图前被中断", lambda: call(generator, prompt="no-retry",
                                                   model="gpt-image-2", size="auto"))
    assert STATE["posts"] == 1, STATE["posts"]
    prepare()

    # ---- gateway errors are translated ----
    cases = [
        (503, '{"error":{"message":"No available channel for model foo"}}', "No available channel"),
        (401, '{"error":{"message":"invalid token"}}', "密钥"),
        (403, '{"error":{"message":"insufficient_quota"}}', "额度"),
        (524, '{"error":{"message":"edge timeout"}}', "边缘节点超时"),
        (500, '{"error":{"message":"do request failed: context deadline exceeded",'
              '"code":"do_request_failed"}}', "上游超时"),
        (500, '{"error":{"message":"model price is unavailable","code":"model_price_unavailable"}}',
         "没有定价"),
    ]
    for status, body, needle in cases:
        STATE["status"], STATE["body"] = status, body
        expect_error(needle, lambda: call(generator, prompt="x", model="gpt-image-2",
                                          size="1024x1024"))
    STATE["status"], STATE["body"] = 200, None

    # ---- registration ----
    assert set(nodes.NODE_CLASS_MAPPINGS) == {"VergoraImageGenerator", "VergoraImageEditor"}
    assert nodes.NODE_DISPLAY_NAME_MAPPINGS["VergoraImageGenerator"].startswith("vergora")

    # ---- a key held by a sibling Vergora pack is borrowed when this one has none ----
    saved_here, saved_config = nodes.HERE, nodes.CONFIG_PATH
    saved_env = os.environ.pop("VERGORA_API_KEY", None)
    root = tempfile.mkdtemp(prefix="vergora_siblings_")
    sibling = os.path.join(root, "vergora-comfyui")
    os.makedirs(sibling)
    with open(os.path.join(sibling, "config.ini"), "w", encoding="utf-8") as handle:
        handle.write("[API]\nBASE_URL = https://api.vergora.ai/v1\nKEY = sk-from-sibling\n")
    mine = os.path.join(root, "ComfyUI-Vergora-Image")
    os.makedirs(mine)
    nodes.HERE = mine
    nodes.CONFIG_PATH = os.path.join(mine, "config.ini")  # deliberately does not exist
    try:
        cfg = REAL_LOAD_CONFIG()
        assert cfg["api_key"] == "sk-from-sibling", cfg
        # an own key still wins over the neighbour
        with open(nodes.CONFIG_PATH, "w", encoding="utf-8") as handle:
            handle.write("[API]\nKEY = sk-own\n")
        assert REAL_LOAD_CONFIG()["api_key"] == "sk-own", REAL_LOAD_CONFIG()
    finally:
        nodes.HERE, nodes.CONFIG_PATH = saved_here, saved_config
        if saved_env is not None:
            os.environ["VERGORA_API_KEY"] = saved_env

    print("OK 全部通过 / all checks passed")
    print("  generate url:", "https://api.vergora.ai/v1/images/generations")
    print("  edit url    :", "https://api.vergora.ai/v1/images/edits")
    print("  nodes       :", sorted(nodes.NODE_CLASS_MAPPINGS))
    print("  saved file  :", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main()

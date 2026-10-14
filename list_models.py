# -*- coding: utf-8 -*-
"""Print the models this API key can see, grouped by what they produce.

The catalogue grows over time, so run this after the platform adds models: any id
it prints with an `image` output can be used right away - pick it from the node's
dropdown, or paste it into `model_override` if it is not listed there yet.

    python list_models.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import nodes  # noqa: E402


def fetch(cfg):
    request = urllib.request.Request(
        cfg["base_url"] + "/models",
        headers={"Authorization": "Bearer " + cfg["api_key"]},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def main():
    cfg = nodes.load_config()
    if not cfg["api_key"]:
        print("没有配置 API key / no API key: fill KEY in config.ini or set VERGORA_API_KEY")
        return 1
    try:
        data = fetch(cfg)
    except urllib.error.HTTPError as exc:
        print("HTTP %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
        return 1
    except Exception as exc:  # noqa: BLE001
        print("request failed / 请求失败: %s" % exc)
        return 1

    groups = {}
    image_capable = set()
    for entry in data.get("data", []):
        arch = entry.get("architecture") or {}
        outputs = arch.get("output_modalities") or ["?"]
        if "image" in (arch.get("output_modalities") or []):
            image_capable.add(entry["id"])
        for output in outputs:
            groups.setdefault(output, []).append(entry["id"])

    print("catalogue total: %d models" % len(data.get("data", [])))
    for output in sorted(groups, key=lambda name: (name != "image", name)):
        ids = sorted(groups[output])
        marker = "  <-- usable by the image nodes" if output in ("image", "image+text") else ""
        print("\n%s (%d)%s" % (output, len(ids), marker))
        for model_id in ids:
            offered = output in ("image", "image+text") and model_id in nodes.IMAGE_MODELS
            print("  %-34s%s" % (model_id, "  [in the node dropdown]" if offered else ""))
        if output == "image":
            print("    (image-capable models overall: %d)" % len(image_capable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

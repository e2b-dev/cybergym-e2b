from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

_ACCEPT = ", ".join(
    [
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
    ]
)


@dataclass(frozen=True)
class TaskImages:
    task_id: str
    vulnerable: str
    fixed: str


def task_images(task_id: str) -> TaskImages:
    family, identifier = task_id.split(":", 1)
    if family == "arvo":
        repository = "n132/arvo"
    elif family == "oss-fuzz":
        repository = "cybergym/oss-fuzz"
    else:
        raise ValueError(f"unsupported CyberGym task family: {family}")
    return TaskImages(
        task_id=task_id,
        vulnerable=f"{repository}:{identifier}-vul",
        fixed=f"{repository}:{identifier}-fix",
    )


def _json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def compressed_image_size(image: str) -> int:
    repository, tag = image.rsplit(":", 1)
    token_url = "https://auth.docker.io/token?" + urllib.parse.urlencode(
        {"service": "registry.docker.io", "scope": f"repository:{repository}:pull"}
    )
    token = _json(token_url)["token"]
    headers = {"Authorization": f"Bearer {token}", "Accept": _ACCEPT}
    manifest_url = f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}"
    manifest = _json(manifest_url, headers)
    if "manifests" in manifest:
        selected = next(
            item
            for item in manifest["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        )
        manifest = _json(
            f"https://registry-1.docker.io/v2/{repository}/manifests/{selected['digest']}",
            headers,
        )
    return sum(layer.get("size", 0) for layer in manifest.get("layers", []))

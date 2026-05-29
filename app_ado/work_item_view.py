"""工单"查看"模块共用的内容/图片处理工具。

被桌面端 ``WorkItemDetailDialog`` 和 TG 端 ``WorkItemsBridge.handle_view`` 共用：
- 从 WorkItem 描述 / 评论 / 关联附件里捞图片 URL；
- 用 PAT 把图片拉到本地缓存（桌面端要 file:// 内嵌）或拉成内存 bytes（TG sendMediaGroup）；
- 把 HTML 里的 ``<img src>`` 改写成本地 ``file://``；
- 把 HTML 剥成纯文本（TG 端不渲染 HTML）。
"""

from __future__ import annotations

import html as html_mod
import re
import shutil
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from app_ado.ado_work_item_http import (
    WorkItem,
    WorkItemComment,
    download_authenticated_file,
    fetch_attachment_bytes,
)


_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")
_IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def collect_image_urls(item: WorkItem, comments: Iterable[WorkItemComment] = ()) -> list[str]:
    """从工单描述 / 评论 / 关联附件里收集图片 URL，按出现顺序去重。

    描述、评论里的内联 ``<img>`` 都算，关系里的 ``attachedFile`` 也算（文件名后缀是图）。
    """
    found: list[str] = []
    desc = str((item.fields or {}).get("System.Description") or "")
    found.extend(_iter_img_src(desc))
    for c in comments or ():
        found.extend(_iter_img_src(c.text or ""))
    for rel in item.relations or []:
        if str(rel.get("rel") or "").lower() != "attachedfile":
            continue
        url = str(rel.get("url") or "").strip()
        if not url:
            continue
        attrs = dict(rel.get("attributes") or {})
        name = str(attrs.get("name") or "")
        if _looks_like_image(name) or _looks_like_image(url):
            found.append(url)

    seen: set[str] = set()
    out: list[str] = []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def view_cache_dir() -> Path:
    return Path.home() / ".config" / "my-own-script" / "work_item_view"


def download_images_to_cache(urls: list[str], *, pat: str, sub_key: str) -> dict[str, Path]:
    """把图片下载到 ``~/.config/my-own-script/work_item_view/<sub_key>/``，返回 ``{url: 本地路径}``。

    每次调用前会清空对应子目录，避免不同工单串图。
    """
    cache = view_cache_dir() / str(sub_key)
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for i, url in enumerate(urls, start=1):
        try:
            hint = _filename_hint(url, i)
            p = download_authenticated_file(url, pat=pat, dest_path=cache / hint)
            out[url] = p
        except Exception:
            continue
    return out


def fetch_image_blobs(urls: list[str], *, pat: str) -> list[tuple[str, bytes, str]]:
    """直接拉成内存字节流（TG sendMediaGroup 用，不落盘）。

    返回 ``[(filename, bytes, content_type), ...]``，下载失败的项跳过。
    """
    out: list[tuple[str, bytes, str]] = []
    for i, url in enumerate(urls, start=1):
        try:
            data, ct = fetch_attachment_bytes(url, pat=pat)
            out.append((_filename_hint(url, i), data, (ct or "image/png")))
        except Exception:
            continue
    return out


def rewrite_html_images(html: str, url_to_local: dict[str, Path]) -> str:
    """把 HTML 里的 ``<img src="http://...">`` 替换成 ``<img src="file://...">``。"""
    if not html or not url_to_local:
        return html or ""

    def repl(m: re.Match) -> str:
        full = m.group(0)
        src = m.group(1)
        local = url_to_local.get(src)
        if not local:
            return full
        return full.replace(src, local.as_uri())

    return _IMG_TAG_RE.sub(repl, html)


def clean_html_to_text(html: str, *, max_len: int = 4000) -> str:
    """剥 HTML 标签，保留段落 / 换行；TG 文本展示用。"""
    text = html_mod.unescape(str(html or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    text = re.sub(r"<img[^>]*>", "[图片]", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_len:
        text = text[: max_len].rstrip() + "…"
    return text


def _iter_img_src(html: str) -> list[str]:
    out: list[str] = []
    if not html:
        return out
    for m in _IMG_TAG_RE.finditer(html):
        url = (m.group(1) or "").strip()
        if url.startswith(("http://", "https://")):
            out.append(url)
    return out


def _looks_like_image(name: str) -> bool:
    lower = (name or "").lower()
    return any(lower.endswith(ext) for ext in _IMG_EXT)


def _filename_hint(url: str, idx: int) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name or f"image_{idx}"
    if "." not in name:
        name = f"{name}_{idx}.png"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe or f"image_{idx}.png"

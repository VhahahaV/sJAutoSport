from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
from rich.console import Console
from rich.table import Table

JS_PATH_RE = re.compile(r"""<script[^>]+src=["'](?P<src>[^"']+\.js)["']""")
API_STRING_RE = re.compile(r"""["'](/(?:pc/)?api/[^"']+)["']""")


def discover_endpoints(
    base_url: str,
    *,
    out_file: str = "endpoints.auto.json",
    console: Optional[Console] = None,
) -> Dict[str, List[str]]:
    console = console or Console()
    console.print(f"[cyan]扫描站点：{base_url}[/cyan]")
    sess = httpx.Client(http2=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=15.0, follow_redirects=True)
    try:
        resp = sess.get(base_url)
        resp.raise_for_status()
    except Exception as exc:
        console.print(f"[red]访问失败：{exc}[/red]")
        return {"candidates": []}

    html = resp.text
    Path("debug_html.html").write_text(html, encoding="utf-8")

    candidates: Set[str] = set(API_STRING_RE.findall(html))

    js_urls = {m.group("src") for m in JS_PATH_RE.finditer(html)}
    for js in js_urls:
        if js.startswith("//"):
            js = "https:" + js
        elif js.startswith("/"):
            js = base_url.rstrip("/") + js
        elif not js.startswith("http"):
            js = base_url.rstrip("/") + "/" + js.lstrip("/")
        try:
            code = sess.get(js).text
        except Exception:
            continue
        candidates.update(API_STRING_RE.findall(code))

    sorted_candidates = sorted(candidates)
    data: Dict[str, Any] = {"candidates": sorted_candidates}
    Path(out_file).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    table = Table(title="候选 API", show_lines=False)
    table.add_column("路径")
    for path in sorted_candidates[:50]:
        table.add_row(path)
    console.print(table)
    console.print(f"[green]已写入 {out_file}[/green]")
    return {"candidates": sorted_candidates}

"""图标加载模块：基于 Lucide SVG 路径解析 + PIL 渲染

从 assets/icons 目录加载 Lucide 风格 SVG 图标，
解析 SVG 路径数据并用 PIL ImageDraw 渲染。
图标在运行时按指定颜色和尺寸渲染并缓存。

渲染流程：
1. 读取 SVG 文件，解析 XML
2. 提取 path/rect/circle/line 元素及其描边属性
3. 在 4x 超采样画布上渲染（坐标从 24x24 正确缩放到 96x96）
4. 缩放到目标尺寸，转为 CTkImage

与旧实现的根本区别：
- 旧实现手写坐标，4x 超采样时坐标未缩放，图标只占左上角 1/4
- 新实现使用 Lucide 官方 SVG 路径数据，坐标按超采样倍数正确缩放
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageDraw
import customtkinter as ctk


def _resolve_assets_dir() -> Path:
    """解析资源目录，兼容开发环境和 PyInstaller 打包环境。"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "docmask" / "ui" / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


_ICON_DIR = _resolve_assets_dir() / "icons"
_CACHE: dict[str, Image.Image] = {}

_SCALE = 4
_SVG_BASE_SIZE = 24


def _resolve_color(color) -> str:
    if isinstance(color, (tuple, list)):
        mode = ctk.AppearanceModeTracker.get_mode()
        idx = 0 if mode == 0 else 1
        return color[idx]
    return str(color)


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        255,
    )


# ======================== SVG 路径解析 ========================

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _tokenize_path(d: str) -> list[tuple[str, list[float]]]:
    """将 SVG path d 属性解析为 [(command, [params]), ...]"""
    result: list[tuple[str, list[float]]] = []
    i = 0
    n = len(d)
    while i < n:
        ch = d[i]
        if ch.isalpha():
            cmd = ch
            i += 1
            # 收集该命令后的所有数字
            params: list[float] = []
            while i < n:
                # 跳过空格和逗号
                while i < n and d[i] in " ,\t\n\r":
                    i += 1
                if i < n and d[i].isalpha():
                    break
                m = _NUM_RE.match(d, i)
                if m:
                    params.append(float(m.group()))
                    i = m.end()
                else:
                    break
            result.append((cmd, params))
            if cmd in "Zz":
                # Z 不接受参数
                continue
        else:
            i += 1
    return result


def _flatten_cubic(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 16,
) -> list[tuple[float, float]]:
    """三次贝塞尔曲线展平"""
    pts: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _flatten_arc(
    p0: tuple[float, float],
    rx: float,
    ry: float,
    x_rot: float,
    large: int,
    sweep: int,
    p1: tuple[float, float],
    steps: int = 32,
) -> list[tuple[float, float]]:
    """SVG arc (A) 展平为线段点"""
    if rx == 0 or ry == 0:
        return [p1]

    phi = math.radians(x_rot)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx = (p0[0] - p1[0]) / 2
    dy = (p0[1] - p1[1]) / 2
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    rx = abs(rx)
    ry = abs(ry)
    lam = x1p**2 / rx**2 + y1p**2 / ry**2
    if lam > 1:
        s = math.sqrt(lam)
        rx *= s
        ry *= s

    denom = rx**2 * y1p**2 + ry**2 * x1p**2
    num = rx**2 * ry**2 - denom
    num = max(0, num)
    factor = math.sqrt(num / denom) if denom > 0 else 0
    if large == sweep:
        factor = -factor

    cxp = factor * rx * y1p / ry
    cyp = factor * -ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2

    def _angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        len_u = math.sqrt(ux * ux + uy * uy)
        len_v = math.sqrt(vx * vx + vy * vy)
        cos_a = max(-1, min(1, dot / (len_u * len_v))) if len_u * len_v > 0 else 1
        a = math.acos(cos_a)
        if ux * vy - uy * vx < 0:
            a = -a
        return a

    theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry,
        (-x1p - cxp) / rx, (-y1p - cyp) / ry,
    )
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    pts: list[tuple[float, float]] = []
    for i in range(1, steps + 1):
        t = theta1 + dtheta * i / steps
        x = cos_phi * rx * math.cos(t) - sin_phi * ry * math.sin(t) + cx
        y = sin_phi * rx * math.cos(t) + cos_phi * ry * math.sin(t) + cy
        pts.append((x, y))
    return pts


def _build_subpaths(tokens: list[tuple[str, list[float]]]) -> list[list[tuple[float, float]]]:
    """将 path tokens 转为子路径点列表（已展平贝塞尔和弧线）"""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    pos = (0.0, 0.0)
    start = (0.0, 0.0)

    for cmd, params in tokens:
        c = cmd.upper()
        rel = cmd.islower()

        if c == "M":
            if current:
                subpaths.append(current)
            x, y = params[0], params[1]
            if rel:
                x += pos[0]
                y += pos[1]
            pos = (x, y)
            start = pos
            current = [pos]
            i = 2
            while i + 1 < len(params):
                x, y = params[i], params[i + 1]
                if rel:
                    x += pos[0]
                    y += pos[1]
                pos = (x, y)
                current.append(pos)
                i += 2

        elif c == "L":
            i = 0
            while i + 1 < len(params):
                x, y = params[i], params[i + 1]
                if rel:
                    x += pos[0]
                    y += pos[1]
                pos = (x, y)
                current.append(pos)
                i += 2

        elif c == "H":
            for v in params:
                x = v + pos[0] if rel else v
                pos = (x, pos[1])
                current.append(pos)

        elif c == "V":
            for v in params:
                y = v + pos[1] if rel else v
                pos = (pos[0], y)
                current.append(pos)

        elif c == "C":
            i = 0
            while i + 5 < len(params):
                p1 = (params[i], params[i + 1])
                p2 = (params[i + 2], params[i + 3])
                p3 = (params[i + 4], params[i + 5])
                if rel:
                    p1 = (p1[0] + pos[0], p1[1] + pos[1])
                    p2 = (p2[0] + pos[0], p2[1] + pos[1])
                    p3 = (p3[0] + pos[0], p3[1] + pos[1])
                current.extend(_flatten_cubic(pos, p1, p2, p3))
                pos = p3
                i += 6

        elif c == "S":
            # 平滑三次贝塞尔
            i = 0
            while i + 3 < len(params):
                p2 = (params[i], params[i + 1])
                p3 = (params[i + 2], params[i + 3])
                if rel:
                    p2 = (p2[0] + pos[0], p2[1] + pos[1])
                    p3 = (p3[0] + pos[0], p3[1] + pos[1])
                # 简化：控制点取上一段终点的镜像或当前位置
                p1 = pos  # 近似
                current.extend(_flatten_cubic(pos, p1, p2, p3))
                pos = p3
                i += 4

        elif c == "A":
            i = 0
            while i + 6 < len(params):
                rx, ry, x_rot = params[i], params[i + 1], params[i + 2]
                large, sweep_flag = int(params[i + 3]), int(params[i + 4])
                x, y = params[i + 5], params[i + 6]
                if rel:
                    x += pos[0]
                    y += pos[1]
                p1 = (x, y)
                current.extend(_flatten_arc(pos, rx, ry, x_rot, large, sweep_flag, p1))
                pos = p1
                i += 7

        elif c == "Z":
            if current:
                current.append(start)
                subpaths.append(current)
            pos = start
            current = []

    if current:
        subpaths.append(current)

    return subpaths


# ======================== 渲染 ========================


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    w: float,
    h: float,
    rx: float,
    color,
    lw: int,
):
    """绘制圆角矩形描边"""
    s = _SCALE
    bbox = [x * s, y * s, (x + w) * s, (y + h) * s]
    r = rx * s
    if r > 0:
        draw.rounded_rectangle(bbox, radius=r, outline=color, width=lw)
    else:
        draw.rectangle(bbox, outline=color, width=lw)


def _draw_circle(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    color,
    lw: int,
):
    """绘制圆形描边"""
    s = _SCALE
    draw.ellipse(
        [(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s],
        outline=color,
        width=lw,
    )


def _draw_line_el(
    draw: ImageDraw.ImageDraw,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    color,
    lw: int,
):
    """绘制 line 元素"""
    s = _SCALE
    draw.line(
        [x1 * s, y1 * s, x2 * s, y2 * s],
        fill=color,
        width=lw,
        joint="curve",
    )
    # 圆角线帽
    r = lw / 2
    draw.ellipse([x1 * s - r, y1 * s - r, x1 * s + r, y1 * s + r], fill=color)
    draw.ellipse([x2 * s - r, y2 * s - r, x2 * s + r, y2 * s + r], fill=color)


def _draw_subpath(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color,
    lw: int,
):
    """绘制一条子路径（带圆角连接和端点）"""
    s = _SCALE
    scaled = [(p[0] * s, p[1] * s) for p in points]
    if len(scaled) < 2:
        if scaled:
            x, y = scaled[0]
            r = lw / 2
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        return

    draw.line(scaled, fill=color, width=lw, joint="curve")
    # 在每个顶点画圆以实现圆角连接
    r = lw / 2
    for x, y in scaled:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _render_icon(name: str, color_hex: str, size: int) -> Image.Image:
    """解析 Lucide SVG 并用 PIL 渲染为 RGBA Image。"""
    svg_path = _ICON_DIR / f"{name}.svg"
    if not svg_path.exists():
        raise FileNotFoundError(f"Icon SVG not found: {name} ({svg_path})")

    tree = ElementTree.parse(svg_path)
    root = tree.getroot()

    rgba = _hex_to_rgba(color_hex)
    canvas_size = _SVG_BASE_SIZE * _SCALE  # 96
    lw = max(1, int(2 * _SCALE))  # Lucide stroke-width=2，超采样后为 8

    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for elem in root.iter():
        tag = elem.tag
        # 去除命名空间
        if "}" in tag:
            tag = tag.split("}", 1)[1]

        if tag == "path":
            d = elem.get("d", "")
            if not d:
                continue
            tokens = _tokenize_path(d)
            subpaths = _build_subpaths(tokens)
            for sp in subpaths:
                _draw_subpath(draw, sp, rgba, lw)

        elif tag == "rect":
            x = float(elem.get("x", 0))
            y = float(elem.get("y", 0))
            w = float(elem.get("width", 0))
            h = float(elem.get("height", 0))
            rx = float(elem.get("rx", 0))
            _draw_rounded_rect(draw, x, y, w, h, rx, rgba, lw)

        elif tag == "circle":
            cx = float(elem.get("cx", 0))
            cy = float(elem.get("cy", 0))
            r = float(elem.get("r", 0))
            _draw_circle(draw, cx, cy, r, rgba, lw)

        elif tag == "line":
            x1 = float(elem.get("x1", 0))
            y1 = float(elem.get("y1", 0))
            x2 = float(elem.get("x2", 0))
            y2 = float(elem.get("y2", 0))
            _draw_line_el(draw, x1, y1, x2, y2, rgba, lw)

        elif tag == "polygon":
            pts_str = elem.get("points", "")
            nums = [float(x) for x in _NUM_RE.findall(pts_str)]
            if len(nums) >= 2:
                points = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
                _draw_subpath(draw, points, rgba, lw)

    # 缩放到目标尺寸
    img = img.resize((size, size), Image.LANCZOS)
    return img


# ======================== 公共 API ========================


def get_icon_image(name: str, size: int = 20, color=None) -> Image.Image:
    """获取 PIL Image 图标（可指定颜色）。"""
    if color is None:
        color_hex = "#000000"
    else:
        color_hex = _resolve_color(color)

    cache_key = f"{name}_{size}_{color_hex}"
    if cache_key not in _CACHE:
        _CACHE[cache_key] = _render_icon(name, color_hex, size)
    return _CACHE[cache_key]


def get_ctk_image(name: str, size: int = 20, color=None) -> ctk.CTkImage:
    """获取 CTkImage 图标。

    自动处理 (light, dark) 颜色元组，生成适配两种模式的 CTkImage。
    """
    if isinstance(color, (tuple, list)) and len(color) == 2:
        light_img = get_icon_image(name, size, color[0])
        dark_img = get_icon_image(name, size, color[1])
        return ctk.CTkImage(
            light_image=light_img,
            dark_image=dark_img,
            size=(size, size),
        )
    else:
        img = get_icon_image(name, size, color)
        return ctk.CTkImage(light_image=img, size=(size, size))


def make_icon_label(
    master, name: str, size: int = 20, color=None, **kwargs
) -> ctk.CTkLabel:
    """创建一个仅包含图标的 CTkLabel。"""
    img = get_ctk_image(name, size, color)
    return ctk.CTkLabel(master, image=img, text="", **kwargs)

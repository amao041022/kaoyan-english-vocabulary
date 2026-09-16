"""圈画与墨迹分析。

判断“哪些词被人用笔圈了或划了线”，不能只看文字框周围有没有墨迹——印刷正文
本身到处都是墨。这里先把印刷体分出去，再对剩下的笔迹做形状判断：

1. 笔画长度图（引擎输出）给出每个墨迹点的水平/垂直连续长度。印刷字母又小又碎，
   笔画短；手写的圈、线、波浪线笔画长。
2. 去掉短笔画后，剩下的连通域只可能是笔迹。
3. 对每个笔迹连通域看形状：空心闭合 → 圈；细长横条 → 下划线／荧光笔；
   其余成片笔迹 → 涂画。
4. 把笔迹与文字框求交，落在同一行同一带的词就是被标记的词。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

INK_DARK = 165          # 灰度低于此值算墨迹
PRINT_STROKE = 13       # 笔画长度不超过此值视为印刷体
MIN_MARK_PIXELS = 90    # 一个笔迹连通域至少这么多像素


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(1.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)

    def expand(self, dx: float, dy: float) -> "Box":
        return Box(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def overlaps(self, other: "Box") -> bool:
        return not (self.x1 < other.x0 or other.x1 < self.x0 or
                    self.y1 < other.y0 or other.y1 < self.y0)

    def intersection(self, other: "Box") -> float:
        width = max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))
        height = max(0.0, min(self.y1, other.y1) - max(self.y0, other.y0))
        return width * height


@dataclass
class Mark:
    kind: str                       # circle | underline | highlight | stroke
    box: Box                        # 像素坐标
    pixels: int = 0
    colored_pixels: int = 0
    filled: float = 0.0             # 连通域像素 / 外框面积
    hole_ratio: float = 0.0         # 内部空洞 / 外框面积（空心判据）
    stroke_p95: int = 0
    detail: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return {"circle": "圈画", "underline": "划线", "highlight": "荧光笔", "stroke": "涂画"}[self.kind]


class PageInk:
    """一页的墨迹数据：灰度、彩色墨迹、笔画长度。"""

    def __init__(self, grey: np.ndarray, stroke: np.ndarray | None = None,
                 rgb: np.ndarray | None = None):
        self.grey = grey
        self.height, self.width = grey.shape
        self.dark = grey < INK_DARK
        if stroke is None:
            self.stroke = np.where(self.dark, 1, 0).astype(np.uint8)
        else:
            self.stroke = stroke
        if rgb is None:
            self.colored = np.zeros_like(self.dark)
        else:
            red = rgb[..., 0].astype(np.int16)
            green = rgb[..., 1].astype(np.int16)
            blue = rgb[..., 2].astype(np.int16)
            self.colored = (((blue - red) > 24) & ((blue - green) > 12)) | \
                           (((red - blue) > 24) & ((red - green) > 12))

    @property
    def handwriting(self) -> np.ndarray:
        """去掉短笔画后剩下的墨迹，基本就是手写笔迹。"""
        return self.dark & (self.stroke > PRINT_STROKE)


def load_mask(mask_path: str, stroke_path: str | None = None,
              image_path: str | None = None) -> PageInk:
    grey = np.asarray(Image.open(mask_path).convert("L"), dtype=np.uint8)
    stroke = None
    if stroke_path:
        try:
            stroke = np.asarray(Image.open(stroke_path).convert("L"), dtype=np.uint8)
        except OSError:
            stroke = None
    rgb = None
    if image_path:
        try:
            rgb = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.uint8)
        except OSError:
            rgb = None
    if rgb is not None and rgb.shape[:2] != grey.shape[:2]:
        rgb = None
    return PageInk(grey, stroke, rgb)


# ---------------------------------------------------------------- 连通域

try:                                            # 装了 scipy 时用它的连通域标记，更快
    from scipy import ndimage as _ndimage
except Exception:                               # noqa: BLE001
    _ndimage = None


def label_components(mask: np.ndarray, min_pixels: int = MIN_MARK_PIXELS,
                     limit: int = 6000) -> list[dict]:
    """连通域标记（8 邻域），返回每个域的像素坐标与边框。"""
    if not mask.any():
        return []
    if _ndimage is not None:
        structure = np.ones((3, 3), dtype=np.uint8)
        labels, count = _ndimage.label(mask, structure=structure)
        if not count:
            return []
        sizes = np.bincount(labels.reshape(-1))
        slices = _ndimage.find_objects(labels)
        results: list[dict] = []
        for value in range(1, count + 1):
            if sizes[value] < min_pixels:
                continue
            window = slices[value - 1]
            if window is None:
                continue
            local = labels[window] == value
            ys, xs = np.nonzero(local)
            y0, x0 = window[0].start, window[1].start
            results.append({"label": value, "ys": ys + y0, "xs": xs + x0,
                            "x0": int(xs.min()) + x0, "y0": int(ys.min()) + y0,
                            "x1": int(xs.max()) + x0 + 1, "y1": int(ys.max()) + y0 + 1,
                            "pixels": int(sizes[value])})
        return results
    return _label_components_manual(mask, min_pixels, limit)


def _label_components_manual(mask: np.ndarray, min_pixels: int, limit: int) -> list[dict]:
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent: list[int] = [0]

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: int, b: int) -> int:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
        return min(ra, rb)

    next_label = 0
    for y in np.flatnonzero(mask.any(axis=1)):
        row = mask[y]
        starts = np.flatnonzero(row & ~np.concatenate(([False], row[:-1])))
        ends = np.flatnonzero(row & ~np.concatenate((row[1:], [False]))) + 1
        previous = labels[y - 1] if y > 0 else None
        for start, end in zip(starts, ends):
            touching = previous[start:end] if previous is not None else None
            if touching is not None:
                touching = touching[touching > 0]
            if touching is not None and touching.size:
                label = int(touching.min())
                for value in np.unique(touching):
                    label = union(label, int(value))
            else:
                if next_label >= limit:
                    continue
                next_label += 1
                parent.append(next_label)
                label = next_label
            labels[y, start:end] = label
    if not next_label:
        return []
    mapping = np.zeros(next_label + 1, dtype=np.int32)
    for value in range(1, next_label + 1):
        mapping[value] = find(value)
    labels = mapping[labels]
    results = []
    for value in np.unique(labels):
        if value == 0:
            continue
        ys, xs = np.nonzero(labels == value)
        if ys.size < min_pixels:
            continue
        results.append({"label": int(value), "ys": ys, "xs": xs,
                        "x0": int(xs.min()), "y0": int(ys.min()),
                        "x1": int(xs.max()) + 1, "y1": int(ys.max()) + 1,
                        "pixels": int(ys.size)})
    return results


def _hole_ratio(mask_region: np.ndarray) -> float:
    """外框内的“内部空洞”占比：空心圈接近 1，实心涂画接近 0。

    用游程做外部背景的连通扩散，避免逐像素的 Python 循环。
    """
    height, width = mask_region.shape
    if height < 3 or width < 3:
        return 0.0
    background = ~mask_region
    intervals: list[tuple[int, int, int]] = []      # (y, x0, x1)
    for y in range(height):
        row = background[y]
        if not row.any():
            continue
        starts = np.flatnonzero(row & ~np.concatenate(([False], row[:-1])))
        ends = np.flatnonzero(row & ~np.concatenate((row[1:], [False]))) + 1
        for start, end in zip(starts, ends):
            intervals.append((y, int(start), int(end)))
    index: dict[int, list[int]] = {}
    for position, (y, _, _) in enumerate(intervals):
        index.setdefault(y, []).append(position)
    outside: set[int] = set()
    stack: list[int] = []
    for position, (y, x0, x1) in enumerate(intervals):
        if y == 0 or y == height - 1 or x0 == 0 or x1 == width:
            outside.add(position)
            stack.append(position)
    while stack:
        position = stack.pop()
        y, x0, x1 = intervals[position]
        for neighbour_y in (y - 1, y + 1):
            for other in index.get(neighbour_y, ()):
                if other in outside:
                    continue
                _, ox0, ox1 = intervals[other]
                if ox0 < x1 and x0 < ox1:
                    outside.add(other)
                    stack.append(other)
    exterior = 0
    for position, (_, x0, x1) in enumerate(intervals):
        if position in outside:
            exterior += x1 - x0
    enclosed = int(background.sum()) - exterior
    return enclosed / float(height * width)


def _top_edge_variation(region: np.ndarray) -> float:
    """墨迹上沿的起伏：手画圆弧是弯的，直下划线是平的。返回上沿 y 的标准差。"""
    heights = []
    for column in range(region.shape[1]):
        ink = np.flatnonzero(region[:, column])
        if ink.size:
            heights.append(int(ink[0]))
    if len(heights) < 6:
        return 0.0
    return float(np.std(heights))


def _corner_hollowness(region: np.ndarray) -> float:
    """四个角附近的空白比例：圈是空心的（角上是纸），涂画是实心的。"""
    height, width = region.shape
    if height < 8 or width < 12:
        return 0.0
    dy, dx = max(2, int(height * 0.22)), max(3, int(width * 0.12))
    corners = [region[:dy, :dx], region[:dy, -dx:], region[-dy:, :dx], region[-dy:, -dx:]]
    empty = sum(1.0 - float(corner.mean()) for corner in corners) / 4
    return empty


def _center_hollowness(region: np.ndarray) -> float:
    """正中间一小块的空白比例：圈的正中是文字，圈线之间往往是空白。"""
    height, width = region.shape
    if height < 8 or width < 12:
        return 0.0
    dy, dx = max(1, int(height * 0.18)), max(2, int(width * 0.08))
    cy, cx = height // 2, width // 2
    centre = region[cy - dy:cy + dy + 1, cx - dx:cx + dx + 1]
    return 1.0 - float(centre.mean())


def _relative_gap(component: dict, box: Box) -> float:
    """连通域相对外框的松散程度：稀疏的笔迹（圈线）接近 1，实心块接近 0。"""
    area = max(1, int(box.width * box.height))
    return 1.0 - component["pixels"] / float(area)


def _merge_neighbours(marks: list[Mark], gap_limit: float) -> list[Mark]:
    """把同一行上位置相邻的笔迹碎片接回一条线。

    文字框被挖掉后，一条长的下划线会被切成好几段；这里按纵向位置与横向间隔
    合并，避免把一条线当成几个小墨点。
    """
    merged: list[Mark] = []
    for mark in sorted(marks, key=lambda item: (round(item.box.y0 / 12), item.box.x0)):
        joined = False
        for other in merged:
            if other.kind != mark.kind:
                continue
            vertical_gap = abs(other.box.y0 - mark.box.y0) + abs(other.box.y1 - mark.box.y1)
            horizontal_gap = max(mark.box.x0 - other.box.x1, other.box.x0 - mark.box.x1)
            if horizontal_gap <= gap_limit and vertical_gap <= max(other.box.height, mark.box.height, 8) * 1.6:
                other.box = Box(min(other.box.x0, mark.box.x0), min(other.box.y0, mark.box.y0),
                                max(other.box.x1, mark.box.x1), max(other.box.y1, mark.box.y1))
                other.pixels += mark.pixels
                other.colored_pixels += mark.colored_pixels
                other.parts = getattr(other, "parts", 1) + 1
                joined = True
                break
        if not joined:
            merged.append(mark)
    return merged


def detect_marks(page: PageInk, line_boxes: list["Box"] | None = None,
                 sensitivity: str = "standard") -> list[Mark]:
    """从整页里找出笔迹并分类。

    做法是“挖掉印刷体再看剩下什么”：
      1. 拿文字识别给出的文字框把印刷正文从图上挖掉；
      2. 剩下的墨迹做连通域标记，只可能是笔迹（圈、线、涂画）；
      3. 用原图的笔画长度图还原这些连通域的完整形状，按空心/细长分类。

    没有文字框时退回按笔画长度区分（不准，仅作兜底）。
    """
    if line_boxes:
        solid = np.zeros_like(page.dark)
        for box in line_boxes:
            x0 = max(0, int(box.x0) - 1)
            x1 = min(page.width, int(np.ceil(box.x1)) + 2)
            y0 = max(0, int(box.y0) - 2)
            y1 = min(page.height, int(np.ceil(box.y1)) + 3)
            if x1 > x0 and y1 > y0:
                solid[y0:y1, x0:x1] = True
        # 印刷体的特征：又黑又短的笔画，且不是彩色；彩色笔迹即使压在文字上也要保留
        printed = page.dark & solid & (page.stroke <= PRINT_STROKE) & ~page.colored
        candidates = page.dark & ~printed
    else:
        solid = None
        candidates = page.dark & (page.stroke > PRINT_STROKE)

    # 笔迹比印刷字更粗，用笔画长度做第一道门槛；宽松模式保留全部候选
    stroke_limit = {"strict": 2.2, "standard": 1.6, "loose": 0.0}.get(sensitivity, 1.6)
    printed_stroke = 0.0
    if line_boxes and stroke_limit:
        sample = np.zeros_like(page.dark)
        for box in line_boxes:
            sample[max(0, int(box.y0)):int(box.y1), max(0, int(box.x0)):int(box.x1)] = True
        # 只用“非彩色”的墨迹估计印刷笔画：彩色的一定是笔迹
        values = page.stroke[page.dark & sample & ~page.colored]
        if values.size:
            printed_stroke = float(np.percentile(values, 90)) * stroke_limit
    marks: list[Mark] = []
    page_area = page.width * page.height
    for component in label_components(candidates, min_pixels=MIN_MARK_PIXELS):
        x0, y0, x1, y1 = component["x0"], component["y0"], component["x1"], component["y1"]
        if component["pixels"] > page_area * 0.25:
            continue                                 # 整页连通（阴影、扫描噪声）
        width, height = x1 - x0, y1 - y0
        if width < 6 or height < 3:
            continue
        # 用笔画长度图还原完整形状：同一条笔迹在挖图前后是同一批长笔画
        window = page.stroke[y0:y1, x0:x1] > PRINT_STROKE
        region = window & page.dark[y0:y1, x0:x1]
        if region.sum() < component["pixels"] * 0.6:
            region = candidates[y0:y1, x0:x1]
        filled = float(region.mean())
        aspect = width / float(max(1, height))
        colored_pixels = int(page.colored[y0:y1, x0:x1].sum())
        colored_ratio = max(colored_pixels / float(max(1, component["pixels"])),
                            colored_pixels / float(max(1, width * height)))
        stroke_p95 = int(np.percentile(page.stroke[component["ys"], component["xs"]], 95))
        # 叠在哪些文字上：用于区分“贴着文字下方的下划线”和“包住文字的圈”
        covering = [box for box in (line_boxes or []) if box.overlaps(Box(x0, y0, x1, y1))]
        line_height = max((box.height for box in covering), default=height)
        line_span = max((box.width for box in covering), default=width)
        text_top = min((box.y0 for box in covering), default=y0)
        text_bottom = max((box.y1 for box in covering), default=y1)
        ink_above = bool(covering) and y0 < text_top - line_height * 0.25
        ink_below = bool(covering) and y1 > text_bottom + line_height * 0.25
        kind = ""
        hole = 0.0
        wide = width >= height * 1.6                  # 圈和下划线都是横长的
        curved = _top_edge_variation(region) if width >= 24 else 0.0
        corners = _corner_hollowness(region)
        # 笔迹必须比印刷文字更大：圈要把词整个包进去，线要压住大半个行宽。
        # 彩色笔迹（蓝/红笔、荧光笔）本身就是明确的人工标记，尺寸要求放宽。
        colored_mark = colored_ratio >= 0.5 and colored_pixels >= 60
        if colored_mark:
            # 下划线／荧光笔可以是细长的一条，圈仍要有足够高度把词包住
            big_enough = width >= line_span * 0.08 or height >= line_height * 1.1
        else:
            big_enough = height >= line_height * 1.25 or width >= line_span * 0.4
        # 彩色笔迹即使很细也算人工标记，只对黑色墨迹要求笔画更粗
        stroke_ok = stroke_p95 >= printed_stroke or colored_pixels >= 60
        if component["pixels"] >= 110 and width >= 22 and height >= 3 and wide and big_enough and stroke_ok:
            if (ink_above and ink_below) or (corners >= 0.5 and height >= line_height * 1.35):
                kind = "circle"                       # 一圈把文字包住
            elif aspect >= 3.0 and height <= max(40, line_height * 1.15) \
                    and width >= line_span * (0.08 if colored_mark else 0.25):
                # 细长横条：上沿起伏明显说明是手画弧
                if curved >= 2.2 and height >= line_height * 0.85:
                    kind = "circle"
                elif colored_ratio >= 0.35 and height > 11 and filled >= 0.7:
                    kind = "highlight"                # 彩色的宽带子是荧光笔
                else:
                    kind = "underline"                # 压在文字下方的横线（含很细的彩色笔道）
            elif 1.6 <= aspect <= 9.0 and corners >= 0.5 and height >= line_height * 1.3:
                kind = "circle"
            elif component["pixels"] >= 900 and width >= line_span * 0.2 and height >= line_height * 1.3:
                kind = "stroke"
        if not kind:
            continue
        marks.append(Mark(kind=kind, box=Box(x0, y0, x1, y1), pixels=int(region.sum()),
                          colored_pixels=colored_pixels, filled=round(filled, 3),
                          hole_ratio=round(hole, 3), stroke_p95=stroke_p95,
                          detail={"aspect": round(aspect, 2), "ink_outside_text": component["pixels"],
                                  "curve": round(curved, 2),
                                  "ink_above": ink_above, "ink_below": ink_below}))
    merged = _merge_neighbours(marks, gap_limit=page.width * 0.03)
    for mark in merged:
        parts = getattr(mark, "parts", 1)
        mark.detail["parts"] = parts
        if mark.kind == "stroke" and parts >= 2 and mark.box.width >= 60:
            # 多段碎片连成一条长横线：本来就是下划线
            mark.kind = "highlight" if (mark.colored_pixels > mark.pixels * 0.35 and (mark.box.y1 - mark.box.y0) > 11) else "underline"
    return merged


def _covered_by(mark: "Mark", box: Box, line_box: Box | None = None,
                tolerance: float = 0.45) -> bool:
    """词的横向范围基本落在笔迹里，才算这支笔作用于这个词。"""
    slack = box.width * 0.12
    if box.x0 < mark.box.x0 - slack or box.x1 > mark.box.x1 + slack:
        return False
    if line_box is not None:
        # 笔迹要落在同一行：整页里 x 位置相近的上下行文字不能被同一个圈命中
        line_height = max(1.0, line_box.height)
        if mark.box.y1 < line_box.y0 - line_height * 0.7:
            return False
        if mark.box.y0 > line_box.y1 + line_height * 0.7:
            return False
    overlap_width = max(0.0, min(mark.box.x1, box.x1) - max(mark.box.x0, box.x0))
    return overlap_width / box.width >= tolerance


def marks_for_box(marks: list[Mark], box: Box, line_box: Box | None = None,
                  tolerance: float = 0.5) -> list[Mark]:
    """找出真正作用于这个词的笔迹。

    要求笔迹横向罩住整个词、且落在同一行（圈会包住词，下划线会垫在词下面），
    再按纵向距离筛选。相邻词因此不会被同一个圈顺带命中。
    """
    related: list[Mark] = []
    for mark in marks:
        if not _covered_by(mark, box, line_box, tolerance):
            continue
        vertical_gap = max(0.0, max(mark.box.y0 - box.y1, box.y0 - mark.box.y1))
        limit = max(8.0, box.height * (2.6 if mark.kind == "circle" else 1.4))
        if vertical_gap > limit:
            continue
        related.append(mark)
    return related


def best_kind(marks: list[Mark]) -> tuple[str, float, dict]:
    """从相关笔迹里挑出最能说明问题的那个。"""
    if not marks:
        return "", 0.0, {}
    priority = {"circle": 3, "underline": 2, "highlight": 2, "stroke": 1}
    marks = sorted(marks, key=lambda mark: (priority[mark.kind], mark.pixels), reverse=True)
    best = marks[0]
    strength = min(1.0, best.pixels / 900.0)
    score = {"circle": 0.62 + 0.36 * strength,
             "underline": 0.55 + 0.42 * strength,
             "highlight": 0.6 + 0.35 * strength,
             "stroke": 0.4 + 0.3 * strength}[best.kind]
    detail = {"kind": best.kind, "pixels": best.pixels, "colored_pixels": best.colored_pixels,
              "filled": best.filled, "hole_ratio": best.hole_ratio,
              "stroke_p95": best.stroke_p95, "marks": len(marks)}
    return best.kind, round(min(score, 0.99), 3), detail


# ---------------------------------------------------------------- 词图裁剪

def crop_bytes(image_path: str, box: Box, padding: float = 0.35, max_width: int = 1000) -> bytes:
    """裁出词（连同圈画痕迹）的小图，供工作台核对。"""
    import io

    with Image.open(image_path) as source:
        image = source.convert("RGB")
        pad_x = box.width * (0.35 + padding)
        pad_y = box.height * (0.55 + padding)
        left = max(0, int(box.x0 - pad_x))
        top = max(0, int(box.y0 - pad_y))
        right = min(image.width, int(box.x1 + pad_x))
        bottom = min(image.height, int(box.y1 + pad_y))
        if right <= left or bottom <= top:
            left, top, right, bottom = 0, 0, image.width, image.height
        crop = image.crop((left, top, right, bottom))
        if crop.width > max_width:
            ratio = max_width / crop.width
            crop = crop.resize((max_width, max(1, int(crop.height * ratio))), Image.LANCZOS)
    buffer = io.BytesIO()
    crop.save(buffer, format="JPEG", quality=86)
    return buffer.getvalue()

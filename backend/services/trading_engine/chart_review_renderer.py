from __future__ import annotations

import struct
import zlib

import pandas as pd

_CHART_WIDTH = 960
_CHART_HEIGHT = 640
_CHART_MARGIN_LEFT = 48
_CHART_MARGIN_RIGHT = 20
_CHART_MARGIN_TOP = 24
_CHART_MARGIN_BOTTOM = 28
_DAY_PANEL_HEIGHT = 350
_INTRADAY_PANEL_GAP = 26
_BACKGROUND = (250, 251, 253)
_GRID = (225, 229, 235)
_FRAME = (190, 196, 205)
_TEXT_STRONG = (40, 47, 58)
_UP = (204, 64, 64)
_DOWN = (51, 122, 183)
_MA20 = (240, 134, 48)
_VOLUME = (152, 161, 175)


class _Canvas:
    def __init__(self, width: int, height: int, bg: tuple[int, int, int]) -> None:
        self.width = int(width)
        self.height = int(height)
        self._pixels = bytearray(self.width * self.height * 3)
        self.fill(bg)

    def fill(self, color: tuple[int, int, int]) -> None:
        r, g, b = color
        row = bytes([r, g, b]) * self.width
        raw = row * self.height
        self._pixels[:] = raw

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        idx = (y * self.width + x) * 3
        self._pixels[idx:idx + 3] = bytes(color)

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.dot(x0, y0, color, radius=max(0, thickness - 1))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def dot(self, x: int, y: int, color: tuple[int, int, int], radius: int = 0) -> None:
        for yy in range(y - radius, y + radius + 1):
            for xx in range(x - radius, x + radius + 1):
                self.set_pixel(xx, yy, color)

    def rect(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        *,
        outline: tuple[int, int, int] | None = None,
        fill: tuple[int, int, int] | None = None,
    ) -> None:
        left = max(0, min(x0, x1))
        right = min(self.width - 1, max(x0, x1))
        top = max(0, min(y0, y1))
        bottom = min(self.height - 1, max(y0, y1))
        if fill is not None:
            fr, fg, fb = fill
            fill_row = bytes([fr, fg, fb]) * max(0, right - left + 1)
            for yy in range(top, bottom + 1):
                start = (yy * self.width + left) * 3
                end = start + len(fill_row)
                self._pixels[start:end] = fill_row
        if outline is not None:
            for xx in range(left, right + 1):
                self.set_pixel(xx, top, outline)
                self.set_pixel(xx, bottom, outline)
            for yy in range(top, bottom + 1):
                self.set_pixel(left, yy, outline)
                self.set_pixel(right, yy, outline)

    def save_png(self, path: str) -> None:
        def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
            body = chunk_type + payload
            return (
                struct.pack(">I", len(payload))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        rows = []
        row_size = self.width * 3
        for idx in range(self.height):
            start = idx * row_size
            rows.append(b"\x00" + bytes(self._pixels[start:start + row_size]))
        compressed = zlib.compress(b"".join(rows), level=9)
        png = [
            b"\x89PNG\r\n\x1a\n",
            _chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0),
            ),
            _chunk(b"IDAT", compressed),
            _chunk(b"IEND", b""),
        ]
        with open(path, "wb") as f:
            f.write(b"".join(png))


def render_candidate_chart_png(
    *,
    path: str,
    code: str,
    daily_bars: pd.DataFrame,
    intraday_bars: pd.DataFrame,
) -> None:
    canvas = _Canvas(_CHART_WIDTH, _CHART_HEIGHT, _BACKGROUND)
    day_left = _CHART_MARGIN_LEFT
    day_top = _CHART_MARGIN_TOP
    day_right = _CHART_WIDTH - _CHART_MARGIN_RIGHT
    day_bottom = day_top + _DAY_PANEL_HEIGHT
    intraday_top = day_bottom + _INTRADAY_PANEL_GAP
    intraday_bottom = _CHART_HEIGHT - _CHART_MARGIN_BOTTOM

    canvas.rect(day_left, day_top, day_right, day_bottom, outline=_FRAME, fill=(255, 255, 255))
    canvas.rect(day_left, intraday_top, day_right, intraday_bottom, outline=_FRAME, fill=(255, 255, 255))
    _draw_grid(canvas, day_left, day_top, day_right, day_bottom)
    _draw_grid(canvas, day_left, intraday_top, day_right, intraday_bottom)
    _draw_title_strip(canvas, code=code)
    _draw_price_panel(canvas, daily_bars.tail(60), day_left, day_top, day_right, day_bottom)
    _draw_intraday_panel(canvas, intraday_bars.tail(48), day_left, intraday_top, day_right, intraday_bottom)
    canvas.save_png(path)


def _draw_title_strip(canvas: _Canvas, *, code: str) -> None:
    strip_top = 4
    strip_bottom = _CHART_MARGIN_TOP - 8
    canvas.rect(_CHART_MARGIN_LEFT, strip_top, _CHART_WIDTH - _CHART_MARGIN_RIGHT, strip_bottom, fill=(244, 246, 250))
    # Small visual anchors since this renderer intentionally avoids font rendering.
    for idx, color in enumerate((_UP, _MA20, _DOWN)):
        center_x = _CHART_MARGIN_LEFT + 12 + idx * 14
        canvas.dot(center_x, strip_top + 6, color, radius=3)
    for offset in range(0, min(len(code), 8) * 10, 10):
        canvas.line(
            _CHART_MARGIN_LEFT + 70 + offset,
            strip_top + 5,
            _CHART_MARGIN_LEFT + 75 + offset,
            strip_top + 11,
            _TEXT_STRONG,
        )


def _draw_grid(canvas: _Canvas, left: int, top: int, right: int, bottom: int) -> None:
    width = max(1, right - left)
    height = max(1, bottom - top)
    for i in range(1, 4):
        y = top + int(height * i / 4)
        canvas.line(left, y, right, y, _GRID)
    for i in range(1, 5):
        x = left + int(width * i / 5)
        canvas.line(x, top, x, bottom, _GRID)


def _draw_price_panel(
    canvas: _Canvas,
    bars: pd.DataFrame,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    if bars is None or bars.empty:
        return
    ohlc = _prepare_ohlc_frame(bars)
    if ohlc.empty:
        return
    min_price = float(ohlc["low"].min())
    max_price = float(ohlc["high"].max())
    if max_price <= min_price:
        max_price = min_price + 1.0
    width = max(1, right - left)
    body_width = max(2, int(width / max(12, len(ohlc) * 2)))
    x_positions = _x_positions(count=len(ohlc), left=left + 8, right=right - 8)
    for idx, row in enumerate(ohlc.itertuples(index=False)):
        x = x_positions[idx]
        high_y = _price_to_y(float(row.high), min_price, max_price, top + 6, bottom - 6)
        low_y = _price_to_y(float(row.low), min_price, max_price, top + 6, bottom - 6)
        open_y = _price_to_y(float(row.open), min_price, max_price, top + 6, bottom - 6)
        close_y = _price_to_y(float(row.close), min_price, max_price, top + 6, bottom - 6)
        color = _UP if float(row.close) >= float(row.open) else _DOWN
        canvas.line(x, high_y, x, low_y, color)
        canvas.rect(
            x - body_width,
            min(open_y, close_y),
            x + body_width,
            max(open_y, close_y),
            outline=color,
            fill=color,
        )
    ma20 = _moving_average_series(ohlc["close"], window=20)
    _draw_line_series(canvas, x_positions, ma20, min_price, max_price, top + 6, bottom - 6, _MA20)


def _draw_intraday_panel(
    canvas: _Canvas,
    bars: pd.DataFrame,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> None:
    if bars is None or bars.empty:
        return
    ohlc = _prepare_ohlc_frame(bars)
    if ohlc.empty:
        return
    min_price = float(ohlc["low"].min())
    max_price = float(ohlc["high"].max())
    if max_price <= min_price:
        max_price = min_price + 1.0
    x_positions = _x_positions(count=len(ohlc), left=left + 8, right=right - 8)
    body_width = max(2, int((right - left) / max(20, len(ohlc) * 3)))
    for idx, row in enumerate(ohlc.itertuples(index=False)):
        x = x_positions[idx]
        high_y = _price_to_y(float(row.high), min_price, max_price, top + 6, bottom - 6)
        low_y = _price_to_y(float(row.low), min_price, max_price, top + 6, bottom - 6)
        open_y = _price_to_y(float(row.open), min_price, max_price, top + 6, bottom - 6)
        close_y = _price_to_y(float(row.close), min_price, max_price, top + 6, bottom - 6)
        color = _UP if float(row.close) >= float(row.open) else _DOWN
        canvas.line(x, high_y, x, low_y, color)
        canvas.rect(
            x - body_width,
            min(open_y, close_y),
            x + body_width,
            max(open_y, close_y),
            outline=color,
            fill=color,
        )
    close_series = pd.to_numeric(ohlc["close"], errors="coerce")
    _draw_line_series(canvas, x_positions, close_series, min_price, max_price, top + 6, bottom - 6, _VOLUME)


def _prepare_ohlc_frame(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    view = bars.copy()
    for column in ("open", "high", "low", "close"):
        if column not in view.columns:
            if column == "open":
                view[column] = view.get("close")
            elif column == "high":
                view[column] = view.get("close")
            elif column == "low":
                view[column] = view.get("close")
            else:
                view[column] = pd.NA
        view[column] = pd.to_numeric(view[column], errors="coerce")
    view = view.dropna(subset=["close"])
    if view.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    for column in ("open", "high", "low"):
        if view[column].isna().all():
            view[column] = view["close"]
        else:
            view[column] = view[column].fillna(view["close"])
    return view[["open", "high", "low", "close"]].reset_index(drop=True)


def _moving_average_series(series: pd.Series, *, window: int) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.rolling(window).mean()


def _draw_line_series(
    canvas: _Canvas,
    x_positions: list[int],
    values: pd.Series,
    min_price: float,
    max_price: float,
    top: int,
    bottom: int,
    color: tuple[int, int, int],
) -> None:
    numeric = pd.to_numeric(values, errors="coerce")
    points: list[tuple[int, int]] = []
    for idx, value in enumerate(numeric.tolist()):
        if idx >= len(x_positions) or pd.isna(value):
            continue
        points.append((x_positions[idx], _price_to_y(float(value), min_price, max_price, top, bottom)))
    for idx in range(1, len(points)):
        x0, y0 = points[idx - 1]
        x1, y1 = points[idx]
        canvas.line(x0, y0, x1, y1, color, thickness=1)


def _x_positions(*, count: int, left: int, right: int) -> list[int]:
    if count <= 1:
        return [left]
    span = max(1, right - left)
    return [left + int(span * idx / max(1, count - 1)) for idx in range(count)]


def _price_to_y(value: float, min_price: float, max_price: float, top: int, bottom: int) -> int:
    ratio = (value - min_price) / max(max_price - min_price, 1e-9)
    ratio = min(1.0, max(0.0, ratio))
    return int(bottom - (bottom - top) * ratio)

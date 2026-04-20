from __future__ import annotations

import argparse
import base64
import json
import struct
import zlib
from pathlib import Path

import requests


class Canvas:
    def __init__(self, width: int, height: int, bg: tuple[int, int, int]) -> None:
        self.width = width
        self.height = height
        self._pixels = bytearray(width * height * 3)
        self.fill(bg)

    def fill(self, color: tuple[int, int, int]) -> None:
        row = bytes(color) * self.width
        self._pixels[:] = row * self.height

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        idx = (y * self.width + x) * 3
        self._pixels[idx:idx + 3] = bytes(color)

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
            row = bytes(fill) * (right - left + 1)
            for yy in range(top, bottom + 1):
                start = (yy * self.width + left) * 3
                self._pixels[start:start + len(row)] = row
        if outline is not None:
            for xx in range(left, right + 1):
                self.set_pixel(xx, top, outline)
                self.set_pixel(xx, bottom, outline)
            for yy in range(top, bottom + 1):
                self.set_pixel(left, yy, outline)
                self.set_pixel(right, yy, outline)

    def line(self, x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = err * 2
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def save_png(self, path: Path) -> None:
        def chunk(chunk_type: bytes, payload: bytes) -> bytes:
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
            chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)),
            chunk(b"IDAT", compressed),
            chunk(b"IEND", b""),
        ]
        path.write_bytes(b"".join(png))


def _render_chart(closes: list[float], path: Path) -> None:
    width = 960
    height = 640
    left = 48
    right = width - 24
    top = 24
    bottom = 520
    canvas = Canvas(width, height, (248, 250, 252))
    grid = (225, 229, 235)
    frame = (185, 192, 202)
    up = (203, 68, 68)
    down = (48, 114, 184)
    volume = (170, 178, 188)
    ma_color = (239, 135, 53)

    canvas.rect(left, top, right, bottom, outline=frame)
    for step in range(1, 5):
        yy = top + ((bottom - top) * step) // 5
        canvas.line(left, yy, right, yy, grid)

    lows: list[float] = []
    highs: list[float] = []
    candles: list[tuple[float, float, float, float]] = []
    prev_close = closes[0] * 0.985
    for idx, close in enumerate(closes):
        if idx == 0:
            open_price = prev_close
        else:
            open_price = closes[idx - 1]
        high = max(open_price, close) * 1.012
        low = min(open_price, close) * 0.988
        candles.append((open_price, high, low, close))
        lows.append(low)
        highs.append(high)

    min_price = min(lows)
    max_price = max(highs)
    price_span = max(max_price - min_price, 1.0)
    candle_gap = (right - left) / max(len(candles), 1)
    body_width = max(int(candle_gap * 0.58), 8)

    def y_for(price: float) -> int:
        ratio = (price - min_price) / price_span
        return int(bottom - ratio * (bottom - top))

    ma_points: list[tuple[int, int]] = []
    volumes = [80 + idx * 10 for idx in range(len(candles))]
    vol_top = 544
    vol_bottom = 612
    max_vol = max(volumes)

    for idx, candle in enumerate(candles):
        open_price, high, low, close = candle
        cx = int(left + candle_gap * idx + candle_gap / 2)
        wick_color = up if close >= open_price else down
        canvas.line(cx, y_for(high), cx, y_for(low), wick_color)
        body_top = min(y_for(open_price), y_for(close))
        body_bottom = max(y_for(open_price), y_for(close))
        if body_bottom == body_top:
            body_bottom += 1
        canvas.rect(
            cx - body_width // 2,
            body_top,
            cx + body_width // 2,
            body_bottom,
            outline=wick_color,
            fill=wick_color,
        )

        start = max(0, idx - 4)
        ma_close = sum(closes[start:idx + 1]) / float(idx - start + 1)
        ma_points.append((cx, y_for(ma_close)))

        vol_height = int((volumes[idx] / max_vol) * (vol_bottom - vol_top))
        canvas.rect(
            cx - body_width // 2,
            vol_bottom - vol_height,
            cx + body_width // 2,
            vol_bottom,
            fill=volume,
        )

    for idx in range(1, len(ma_points)):
        x0, y0 = ma_points[idx - 1]
        x1, y1 = ma_points[idx]
        canvas.line(x0, y0, x1, y1, ma_color)

    canvas.save_png(path)


def _to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _create_prompt(label_hint: str) -> str:
    return (
        "당신은 한국 주식 차트를 보는 어시스턴트다. "
        "이미지 하나만 보고 최근 구조를 분류해라. "
        "반드시 JSON으로만 답해라. "
        '형식: {"label":"UPTREND_BREAKOUT|BEARISH_BREAKDOWN|SIDEWAYS|UNSURE","reason":"한 문장"} '
        f"기대 시나리오 참고: {label_hint}"
    )


def _call_model(base_url: str, image_path: Path, prompt: str, timeout: float) -> dict:
    models = requests.get(f"{base_url}/v1/models", timeout=timeout)
    models.raise_for_status()
    model_id = (models.json().get("data") or [{}])[0].get("id") or "local-model"

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": _to_data_url(image_path),
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 220,
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 40,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "chart_label",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "label": {
                            "type": "string",
                            "enum": [
                                "UPTREND_BREAKOUT",
                                "BEARISH_BREAKDOWN",
                                "SIDEWAYS",
                                "UNSURE",
                            ],
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["label", "reason"],
                },
            },
        },
    }
    response = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return {
        "model": model_id,
        "raw": content,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual multimodal smoke test for local llama-server")
    parser.add_argument("--base-url", default="http://127.0.0.1:8083")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--output-dir",
        default="backend/storage/multimodal_smoke",
        help="Directory inside the repo where sample charts will be written",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenarios = {
        "uptrend_breakout": [100, 101, 102, 104, 105, 107, 108, 109, 111, 113, 114, 116, 118, 121, 124, 126],
        "bearish_breakdown": [128, 127, 126, 125, 123, 121, 120, 118, 115, 112, 108, 104, 100, 96, 92, 88],
    }

    print("=== Multimodal Smoke Test ===")
    print(f"Base URL: {args.base_url}")
    for label, closes in scenarios.items():
        image_path = output_dir / f"{label}.png"
        _render_chart(closes, image_path)
        result = _call_model(
            base_url=args.base_url,
            image_path=image_path,
            prompt=_create_prompt(label),
            timeout=args.timeout,
        )
        print(f"\n[{label}]")
        print(f"image={image_path}")
        print(f"model={result['model']}")
        print(result["raw"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

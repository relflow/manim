"""Manim scenes for the docs primers. Text is drawn with Pango, without LaTeX."""

from __future__ import annotations

import json
import os
from pathlib import Path

import manimpango
import numpy as np
from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Arrow,
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Indicate,
    LaggedStart,
    Line,
    RoundedRectangle,
    Scene,
    SVGMobject,
    Text,
    VGroup,
    config,
    linear,
    register_font,
)

ROOT = Path(__file__).resolve().parent
SERIES = json.loads((ROOT / "series.json").read_text())
INK = "#dce5ce"
DIM = "#93a29d"
FIELD = "#7abbb1"
BRANCH = "#c6afdf"
TARGET = "#efb079"
PANEL = "#182127"
BACKGROUND = "#0e1117"
config.background_color = BACKGROUND
for filename in ("notosans.ttf", "notosansmono.ttf"):
    if not manimpango.register_font(str(ROOT / "assets" / filename)):
        raise RuntimeError(f"Cannot register bundled font: {filename}")


def text(value: str, size: float = 28, color: str = INK, mono: bool = False) -> Text:
    result = Text(value or " ", font="Noto Sans Mono" if mono else "Noto Sans", font_size=size, color=color)
    if result.width > 12.3:
        result.scale_to_fit_width(12.3)
    return result


def field_color(value: str) -> str:
    if any(part in value.lower() for part in ("disputed", "target", "reconstruct", "loss", "predict")):
        return TARGET
    if any(part in value.lower() for part in ("recent_transactions", "history", "branch", "context")):
        return BRANCH
    return FIELD


def card(value: str, width: float = 5.2, height: float = 0.75, color: str = FIELD) -> VGroup:
    label = text(value, 23, color)
    if label.width > width - 0.4:
        label.scale_to_fit_width(width - 0.4)
    rect = RoundedRectangle(
        width=width,
        height=height,
        corner_radius=0.13,
        stroke_color=color,
        stroke_width=1.6,
        fill_color=PANEL,
        fill_opacity=1,
    )
    return VGroup(rect, label.move_to(rect))


class Primer(Scene):
    segment_id = "first-model"

    def construct(self):
        segment = next(item for item in SERIES["segments"] if item["id"] == self.segment_id)
        timing_file = ROOT / "build" / self.segment_id / "timing.json"
        timing = json.loads(timing_file.read_text())
        self.fps = config.frame_rate
        with register_font(str(ROOT / "assets/LibertinusSerif-Semibold.otf")):
            mark = SVGMobject(str(ROOT / "assets/relflow_logo.svg")).set(height=0.52)
            brand = Text("relflow", font="Libertinus Serif", weight="SEMIBOLD", font_size=31, color=INK)
        logo = VGroup(mark, brand).arrange(RIGHT, buff=0.16).to_corner(UP + LEFT, buff=0.4)
        series = text("VISUALIZED", 14, DIM).to_corner(UP + RIGHT, buff=0.48)
        rule = Line(LEFT * 6.7 + UP * 2.95, RIGHT * 6.7 + UP * 2.95, stroke_color="#34443d")
        footer = text("relflow.github.io/docs  |  schematic", 16, DIM).to_edge(DOWN, buff=0.23)
        title = text(segment["title"], 41).move_to(UP * 0.6)
        subtitle = text("A short guide to structured data", 23, DIM).next_to(title, DOWN, buff=0.25)
        self.add(logo, series, rule, footer)
        self.play(FadeIn(title, shift=UP * 0.12), FadeIn(subtitle), run_time=0.6)
        self.wait(max(0, timing["intro"] - 1.0))
        self.play(FadeOut(title), FadeOut(subtitle), run_time=0.4)

        for index, (beat, schedule) in enumerate(zip(segment["beats"], timing["beats"], strict=True)):
            started = self.renderer.time
            heading = text(beat["title"], 32).move_to(UP * 2.38)
            counter = text(f"{index + 1:02d} / {len(segment['beats']):02d}", 17, DIM).to_corner(DOWN + RIGHT, 0.28)
            group, sequence = self.visual(beat)
            self.add(counter)
            if schedule["audio"]:
                self.renderer.file_writer.add_sound(schedule["audio"], self.renderer.time)
            self.play(FadeIn(heading, shift=UP * 0.1), run_time=0.4)
            self.play(LaggedStart(*[FadeIn(item, shift=RIGHT * 0.14) for item in group], lag_ratio=0.12), run_time=1.2)
            self.demonstrate(beat, group, sequence)
            left = schedule["duration"] - (self.renderer.time - started) - 0.4
            if left > 0:
                self.wait(left)
            self.play(FadeOut(heading), FadeOut(group), FadeOut(counter), run_time=0.4)

        closing = text("Continue in the documentation", 34).move_to(UP * 0.35)
        link = text(segment["page"].removesuffix(".qmd"), 24, FIELD).next_to(closing, DOWN, buff=0.35)
        self.play(FadeIn(closing), FadeIn(link), run_time=0.5)
        self.wait(timing["outro"] - 1.0)
        self.play(FadeOut(closing), FadeOut(link), run_time=0.5)

    def visual(self, beat: dict) -> tuple[VGroup, VGroup]:
        kind, lines = beat["visual"], beat["lines"]
        if kind in {"record", "code", "prediction"}:
            rows = VGroup()
            for value in lines:
                indent = len(value) - len(value.lstrip())
                label = text(value.strip(), 26 if kind == "record" else 23, field_color(value), mono=True)
                rows.add(label)
                label.indent = indent
            rows.arrange(DOWN, aligned_edge=LEFT, buff=0.16)
            left = min(row.get_left()[0] for row in rows)
            for row in rows:
                row.shift(RIGHT * (left + row.indent * 0.11 - row.get_left()[0]))
            if rows.width > 11.7:
                rows.scale_to_fit_width(11.7)
            if rows.height > 3.7:
                rows.scale_to_fit_height(3.7)
            rows.move_to(DOWN * 0.15)
            rect = RoundedRectangle(
                width=max(7.2, rows.width + 0.8),
                height=max(2.1, rows.height + 0.65),
                corner_radius=0.16,
                stroke_color="#40544c",
                fill_color=PANEL,
                fill_opacity=0.9,
            ).move_to(rows)
            rows.align_to(rect.get_left() + RIGHT * 0.4, LEFT)
            return VGroup(rect, *rows), rows

        if kind == "tree":
            root = card("payment", width=2.5, color=INK).move_to(UP * 1.1)
            labels = VGroup(*[card(value, width=5.7, height=0.6, color=field_color(value)) for value in lines])
            labels.arrange(DOWN, buff=0.14).move_to(RIGHT * 2.8 + DOWN * 0.55)
            root.move_to(LEFT * 4.2)
            edges = VGroup(*[Line(root.get_right(), label.get_left(), color=BRANCH) for label in labels])
            return VGroup(edges, root, *labels), labels

        width = 10.8 if kind in {"history", "mask", "embedding"} else 9.0
        nodes = VGroup(*[card(value, width=width, color=field_color(value)) for value in lines])
        nodes.arrange(DOWN, buff=0.23).move_to(DOWN * 0.15)
        if nodes.height > 4.0:
            nodes.scale_to_fit_height(4.0)
        arrows = VGroup(
            *[
                Arrow(a.get_bottom(), b.get_top(), buff=0.025, stroke_width=2, color=DIM)
                for a, b in zip(nodes, nodes[1:])
            ]
        )
        return VGroup(arrows, *nodes), nodes

    def demonstrate(self, beat: dict, group: VGroup, sequence: VGroup):
        kind = beat["visual"]
        if kind == "code":
            selected = [
                row for row, line in zip(sequence, beat["lines"], strict=True) if "mask" in line or "fit(" in line
            ]
            if selected:
                self.play(*[Indicate(row, color=TARGET, scale_factor=1.02) for row in selected], run_time=1.0)
            return
        if kind in {"flow", "history", "tree"} and len(sequence) > 1:
            dot = Dot(sequence[0].get_left() + LEFT * 0.2, radius=0.06, color=INK)
            self.add(dot)
            for item in sequence[1:]:
                self.play(dot.animate.move_to(item.get_left() + LEFT * 0.2), run_time=0.35, rate_func=linear)
            self.play(FadeOut(dot), run_time=0.2)
        elif kind == "mask":
            self.play(Indicate(sequence[-1], color=TARGET, scale_factor=1.02), run_time=1)
        elif kind == "embedding":
            bars = VGroup(
                *[
                    Line(np.array([x, -2.55, 0]), np.array([x, -2.55 + value, 0]), color=FIELD, stroke_width=7)
                    for x, value in zip(np.linspace(-2.5, 2.5, 24), np.random.default_rng(7).uniform(0.1, 0.55, 24))
                ]
            )
            self.play(Create(bars), run_time=0.7)
            group.add(bars)


for segment in SERIES["segments"]:
    name = segment["scene"]
    globals()[name] = type(name, (Primer,), {"segment_id": segment["id"], "__module__": __name__})

if os.environ.get("RELFLOW_MANIM_SEGMENT"):
    # The CLI selects a class explicitly; this guard catches accidental name drift.
    assert any(item["id"] == os.environ["RELFLOW_MANIM_SEGMENT"] for item in SERIES["segments"])

import argparse
import datetime as dt
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scene:
    name: str
    duration_s: float
    title: str
    lines: list[str]
    theme: str


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n\n{proc.stdout}")


def _pick_fontfile() -> str | None:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _pick_monofontfile() -> str | None:
    candidates = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _parse_demo_kit(markdown_path: Path) -> list[Scene]:
    text = markdown_path.read_text(encoding="utf-8", errors="replace")

    slide_blocks: list[tuple[str, str]] = []
    slide_pattern = re.compile(r"^###\s+Slide\s+(\d+)\s+—\s+(.+?)\s*$", re.MULTILINE)
    matches = list(slide_pattern.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        slide_no = m.group(1).strip()
        slide_title = m.group(2).strip()
        slide_blocks.append((slide_no, slide_title + "\n" + text[start:end]))

    scenes: list[Scene] = []
    for slide_no, block in slide_blocks:
        title_line = block.splitlines()[0].strip()
        on_slide_match = re.search(r"\*\*On-slide\*\*\s*(.*?)\n\n\*\*Voiceover", block, re.DOTALL)
        bullets: list[str] = []
        if on_slide_match:
            raw = on_slide_match.group(1)
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("- "):
                    bullets.append(line[2:].strip())
        if not bullets:
            bullets = ["OpenVisionX demo"]

        duration = 12.0
        if slide_no in {"2", "3", "4", "5", "9", "10"}:
            duration = 14.0
        if slide_no in {"6", "8"}:
            duration = 10.0

        theme = "blue"
        if slide_no in {"2"}:
            theme = "dark"
        if slide_no in {"5", "6"}:
            theme = "green"
        if slide_no in {"7", "8"}:
            theme = "purple"

        scenes.append(
            Scene(
                name=f"slide_{slide_no}",
                duration_s=duration,
                title=title_line,
                lines=bullets,
                theme=theme,
            )
        )

    return scenes


def _demo_data_scenes(now: dt.datetime) -> list[Scene]:
    today = now.strftime("%Y-%m-%d")
    start = now.replace(hour=8, minute=55, second=0, microsecond=0)
    entries = [
        (start + dt.timedelta(minutes=3), "Worker 001", "CHECK_IN", "Assembly"),
        (start + dt.timedelta(minutes=6), "Worker 002", "CHECK_IN", "Assembly"),
        (start + dt.timedelta(minutes=11), "Worker 003", "CHECK_IN", "Packing"),
        (start + dt.timedelta(minutes=25), "Worker 002", "CHECK_OUT", "Assembly"),
        (start + dt.timedelta(minutes=28), "Worker 002", "CHECK_IN", "Assembly"),
        (start + dt.timedelta(minutes=36), "Worker 004", "CHECK_IN", "Stores"),
    ]
    table_lines = ["TIME     PERSON       STATUS     DEPT", "-" * 44]
    for t, person, status, dept in entries[:6]:
        table_lines.append(f"{t.strftime('%H:%M')}   {person:<10}   {status:<9} {dept}")

    wages_lines = [
        f"DATE: {today}",
        "",
        "SUMMARY",
        "Present: 4",
        "Absent:  1",
        "Late:    1",
        "",
        "TOTALS (sample)",
        "Daily wage total: ₹ 5,400",
        "Overtime total:   ₹ 1,200",
        "",
        "Exports: CSV / Excel-ready",
    ]

    school_lines = [
        "PARENT MODE (No-login)",
        "",
        "Student Number: 1023",
        "Class/Section:  8-A",
        "",
        "TODAY",
        f"{today}  09:05  CHECK_IN   Gate 1",
        f"{today}  15:32  CHECK_OUT  Gate 1",
        "",
        "History: date filter available",
        "Privacy: parent view is image-free",
    ]

    return [
        Scene(
            name="manufacturing_live_feed",
            duration_s=14.0,
            title="Manufacturing — Live Attendance (Demo Data)",
            lines=table_lines,
            theme="green",
        ),
        Scene(
            name="manufacturing_wages_report",
            duration_s=14.0,
            title="Manufacturing — Wages/Payroll Summary (Demo Data)",
            lines=wages_lines,
            theme="green",
        ),
        Scene(
            name="school_parent_view",
            duration_s=14.0,
            title="School — Parent View (Demo Data)",
            lines=school_lines,
            theme="purple",
        ),
    ]


def _theme(theme: str) -> dict[str, str]:
    palettes = {
        "blue": {"bg": "#0b1220", "accent": "#2563eb", "fg": "white"},
        "dark": {"bg": "#0b0b0c", "accent": "#9ca3af", "fg": "white"},
        "green": {"bg": "#071a12", "accent": "#22c55e", "fg": "white"},
        "purple": {"bg": "#12061a", "accent": "#a855f7", "fg": "white"},
    }
    return palettes.get(theme, palettes["blue"])


def _escape_drawtext_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("%", "\\%")
        .replace("'", "\\'")
        .replace("\n", " ")
    )


def _alpha_ramp(start_s: float, ramp_s: float = 0.55) -> str:
    start = f"{start_s:.2f}"
    ramp = f"{ramp_s:.2f}"
    return f"if(lt(t,{start}),0,if(lt(t,{start}+{ramp}),(t-{start})/{ramp},1))"


def _render_scene(
    *,
    ffmpeg: str,
    out_path: Path,
    title: str,
    lines: list[str],
    duration_s: float,
    width: int,
    height: int,
    fps: int,
    theme: str,
    fontfile: str | None,
    monofontfile: str | None,
    preset: str,
    crf: int,
) -> None:
    pal = _theme(theme)

    is_table_like = any(("  " in ln or ln.startswith("-" * 5)) for ln in lines)
    scene_font = monofontfile if is_table_like and monofontfile else fontfile

    accent_bar = f"drawbox=x=80:y=140:w=10:h=800:color={pal['accent']}@1:t=fill"

    title_text = _escape_drawtext_text(title)
    title_alpha = _alpha_ramp(0.0)
    title_x = "100-(1-min(1,t/0.7))*30"
    draw_title = (
        "drawtext="
        f"text='{title_text}':"
        f"fontcolor={pal['fg']}:"
        "fontsize=54:"
        f"x='{title_x}':y=140:"
        f"alpha='{title_alpha}':"
        "line_spacing=8"
    )
    if scene_font:
        draw_title += f":fontfile={scene_font}"

    bullet_filters: list[str] = []
    start_y = 260
    line_gap = 62 if not is_table_like else 44
    bullet_size = 38 if not is_table_like else 34
    max_lines = 12 if not is_table_like else 16
    trimmed_lines = lines[:max_lines]
    for i, ln in enumerate(trimmed_lines):
        t0 = 0.70 + i * (0.45 if not is_table_like else 0.18)
        alpha = _alpha_ramp(t0, 0.45)
        x = f"120-(1-min(1,(t-{t0:.2f})/0.45))*40"
        y = start_y + i * line_gap
        content = ln
        if not is_table_like:
            content = f"• {content}"
        text = _escape_drawtext_text(content)
        dtf = (
            "drawtext="
            f"text='{text}':"
            f"fontcolor={pal['fg']}:"
            f"fontsize={bullet_size}:"
            f"x='{x}':y={y}:"
            f"alpha='{alpha}'"
        )
        if scene_font:
            dtf += f":fontfile={scene_font}"
        bullet_filters.append(dtf)

    footer_alpha = _alpha_ramp(max(0.0, duration_s - 3.0), 0.35)
    footer = (
        "drawtext="
        "text='OpenVisionX Demo':"
        f"fontcolor={pal['fg']}:"
        "fontsize=24:"
        "x=w-320:y=h-70:"
        f"alpha='{footer_alpha}'"
    )
    if fontfile:
        footer += f":fontfile={fontfile}"

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={pal['bg']}:s={width}x{height}:d={duration_s}",
        "-vf",
        ",".join(
            [
                accent_bar,
                draw_title,
                *bullet_filters,
                footer,
                "fade=t=in:st=0:d=0.6",
                f"fade=t=out:st={max(0.0, duration_s - 0.6):.2f}:d=0.6",
            ]
        ),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        preset,
        "-tune",
        "stillimage",
        "-crf",
        str(crf),
        out_path.as_posix(),
    ]
    _run(cmd)


def generate_demo_video(
    *,
    demo_kit_path: Path,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    preset: str = "ultrafast",
    crf: int = 28,
) -> Path:
    if _which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found. Install it (macOS): brew install ffmpeg")

    ffmpeg = "ffmpeg"
    fontfile = _pick_fontfile()
    monofontfile = _pick_monofontfile()
    now = dt.datetime.now()

    slides = _parse_demo_kit(demo_kit_path)
    demo_scenes = _demo_data_scenes(now)

    scenes: list[Scene] = []
    for s in slides:
        scenes.append(s)
        if s.name == "slide_6":
            scenes.extend([demo_scenes[0], demo_scenes[1]])
        if s.name == "slide_8":
            scenes.append(demo_scenes[2])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="openvisionx_demo_video_") as tmpdir:
        tmp = Path(tmpdir)
        parts_dir = tmp / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        part_paths: list[Path] = []
        for idx, scene in enumerate(scenes, start=1):
            part = parts_dir / f"{idx:02d}_{scene.name}.mp4"
            _render_scene(
                ffmpeg=ffmpeg,
                out_path=part,
                title=scene.title,
                lines=scene.lines,
                duration_s=scene.duration_s,
                width=width,
                height=height,
                fps=fps,
                theme=scene.theme,
                fontfile=fontfile,
                monofontfile=monofontfile,
                preset=preset,
                crf=crf,
            )
            part_paths.append(part)

        concat_file = tmp / "concat.txt"
        concat_lines = []
        for p in part_paths:
            concat_lines.append(f"file '{p.as_posix()}'")
        concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_file.as_posix(),
            "-c",
            "copy",
            output_path.as_posix(),
        ]
        _run(cmd)

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo-kit",
        default=str(Path(__file__).resolve().parents[1] / "DEMO_VIDEO_KIT.md"),
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "demo_video" / "output" / "openvisionx_demo.mp4"),
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--preset", default="ultrafast")
    parser.add_argument("--crf", type=int, default=28)
    args = parser.parse_args()

    out = generate_demo_video(
        demo_kit_path=Path(args.demo_kit),
        output_path=Path(args.out),
        width=args.width,
        height=args.height,
        fps=args.fps,
        preset=args.preset,
        crf=args.crf,
    )
    print(out.as_posix())


if __name__ == "__main__":
    main()

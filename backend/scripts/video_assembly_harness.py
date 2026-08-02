#!/usr/bin/env python3
"""
Assemble generated UGC video clips into Meta-ready 9:16 ad drafts.

Standalone research script only. It reads finetuning_output/manifest.json and
writes under assembly_output/. It does not import app code, write to the DB, or
touch shipped routes/models.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = Path(__file__).resolve().parent
FINETUNING_DIR = SCRIPT_DIR / "finetuning_output"
MANIFEST_PATH = FINETUNING_DIR / "manifest.json"
OUTPUT_DIR = SCRIPT_DIR / "assembly_output"
PLAN_PATH = OUTPUT_DIR / "assembly_plan.json"
REVIEW_PATH = OUTPUT_DIR / "review.html"
OVERLAY_DIR = OUTPUT_DIR / "overlays"

DEFAULT_CTA = "Compare auto insurance rates"
DEFAULT_DISCLOSURE = "Availability and savings vary by driver."
QA_CHECKS = [
    "No fake, garbled, or cloaked on-screen text",
    "US left-hand-drive context preserved",
    "Steering wheel, hands, phone, and dashboard are physically plausible",
    "Phone screen has no readable fake quote UI",
    "Voice matches actor age and energy",
    "Lip sync tracks the audio through the full line",
    "Actor face, clothing, lighting, and background stay consistent across cuts",
    "Hook lands in first 1.5 seconds",
    "CTA is Meta-safe and avoids fixed savings guarantees",
]


@dataclass(frozen=True)
class AssemblyPlan:
    assembly_id: str
    cast_id: str
    niche_id: str
    format_id: str
    talking_head_file: str
    broll_file: str
    script_text: str
    hook_text: str
    cta_text: str
    disclosure_text: str
    output_file: str


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"Missing manifest: {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text())


def words_to_caption_lines(text: str, max_chars: int = 34, max_lines: int = 4) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:max_lines]


def hook_from_script(text: str) -> str:
    lowered = text.lower()
    if "vary this much" in lowered or "insurance prices" in lowered:
        return "Insurance rates can vary"
    if "rate changed" in lowered or "renewal" in lowered:
        return "Rate changed recently?"
    return "Check your rate options"


def build_plans(manifest: dict[str, Any], cta_text: str, disclosure_text: str) -> list[AssemblyPlan]:
    successful = [
        clip
        for clip in manifest.get("clips", [])
        if clip.get("status") in {"success", "reused"}
        and clip.get("local_file")
        and (FINETUNING_DIR / clip["local_file"]).exists()
    ]
    by_key: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for clip in successful:
        key = (clip.get("cast_id", ""), clip.get("niche_id", ""), clip.get("format_id", ""))
        by_key.setdefault(key, {})[clip.get("clip_type", "")] = clip

    plans: list[AssemblyPlan] = []
    for (cast_id, niche_id, format_id), clips in sorted(by_key.items()):
        talking = clips.get("talking_head")
        broll = clips.get("broll")
        if not talking or not broll:
            continue
        script_text = talking.get("script_text") or ""
        assembly_id = f"{cast_id}_{niche_id}_{format_id}"
        plans.append(
            AssemblyPlan(
                assembly_id=assembly_id,
                cast_id=cast_id,
                niche_id=niche_id,
                format_id=format_id,
                talking_head_file=talking.get("local_file") or "",
                broll_file=broll.get("local_file") or "",
                script_text=script_text,
                hook_text=hook_from_script(script_text),
                cta_text=cta_text,
                disclosure_text=disclosure_text,
                output_file=f"{assembly_id}_assembled.mp4",
            )
        )
    return plans


def font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_for_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in text.split():
        candidate = " ".join([*current, word])
        bbox = draw.textbbox((0, 0), candidate, font=text_font)
        if current and bbox[2] - bbox[0] > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def centered_box(draw: ImageDraw.ImageDraw, text: str, y: int, text_font: ImageFont.ImageFont, fill: tuple[int, int, int, int], max_width: int = 900) -> int:
    pad_x = 34
    pad_y = 18
    line_gap = 8
    lines = wrap_for_width(draw, text, text_font, max_width)
    boxes = [draw.textbbox((0, 0), line, font=text_font) for line in lines]
    text_w = max((box[2] - box[0] for box in boxes), default=0)
    line_heights = [box[3] - box[1] for box in boxes]
    text_h = sum(line_heights) + line_gap * max(0, len(lines) - 1)
    x = max(40, (1080 - text_w) // 2)
    draw.rounded_rectangle(
        (x - pad_x, y - pad_y, x + text_w + pad_x, y + text_h + pad_y),
        radius=18,
        fill=fill,
    )
    line_y = y
    for line, line_h, box in zip(lines, line_heights, boxes):
        line_w = box[2] - box[0]
        draw.text(((1080 - line_w) // 2, line_y), line, font=text_font, fill=(255, 255, 255, 255))
        line_y += line_h + line_gap
    return y + text_h + pad_y


def create_overlay_image(plan: AssemblyPlan) -> Path:
    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    path = OVERLAY_DIR / f"{plan.assembly_id}_overlay.png"
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    centered_box(draw, plan.hook_text, 130, font(46), (0, 0, 0, 165), max_width=860)
    for index, line in enumerate(words_to_caption_lines(plan.script_text, max_chars=34, max_lines=2)):
        centered_box(draw, line, 1518 + index * 58, font(32), (0, 0, 0, 128), max_width=780)
    centered_box(draw, plan.cta_text, 1718, font(38), (249, 115, 22, 235), max_width=780)
    centered_box(draw, plan.disclosure_text, 1838, font(20), (0, 0, 0, 105), max_width=760)
    image.save(path)
    return path


def build_filter() -> str:
    return ";".join(
        [
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,trim=0:7,setpts=PTS-STARTPTS[v0]",
        "[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,trim=0:5,setpts=PTS-STARTPTS[v1]",
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,trim=start=7:end=15,setpts=PTS-STARTPTS[v2]",
        "[v0][v1][v2]concat=n=3:v=1:a=0[vcat]",
        "[0:a]atrim=0:15,asetpts=PTS-STARTPTS[aout]",
        "[2:v]scale=1080:1920,format=rgba[ovr]",
        "[vcat][ovr]overlay=0:0:format=auto[vout]",
        ]
    )


def run_ffmpeg(plan: AssemblyPlan, ffmpeg_bin: str) -> dict[str, Any]:
    talking_path = FINETUNING_DIR / plan.talking_head_file
    broll_path = FINETUNING_DIR / plan.broll_file
    overlay_path = create_overlay_image(plan)
    output_path = OUTPUT_DIR / plan.output_file
    if not talking_path.exists():
        raise FileNotFoundError(talking_path)
    if not broll_path.exists():
        raise FileNotFoundError(broll_path)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(talking_path),
        "-i",
        str(broll_path),
        "-i",
        str(overlay_path),
        "-filter_complex",
        build_filter(),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "output_file": plan.output_file,
        "status": "success" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stderr_tail": result.stderr[-3000:],
    }


def write_plan(plans: list[AssemblyPlan], results: list[dict[str, Any]] | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now().isoformat(),
        "input_manifest": str(MANIFEST_PATH),
        "plans": [plan.__dict__ for plan in plans],
        "results": results or [],
    }
    PLAN_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def build_review_html(plans: list[AssemblyPlan], results: list[dict[str, Any]] | None = None) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_by_file = {row.get("output_file"): row for row in results or []}
    cards = []
    for plan in plans:
        result = results_by_file.get(plan.output_file, {})
        output_path = OUTPUT_DIR / plan.output_file
        clip_id = f"{plan.assembly_id}_assembled"
        video_html = (
            f'<video controls preload="metadata" src="{escape(plan.output_file)}"></video>'
            if output_path.exists()
            else '<div class="missing">Assembly not rendered yet. Install ffmpeg or run on the VPS.</div>'
        )
        caption_lines = "".join(f"<li>{escape(line)}</li>" for line in words_to_caption_lines(plan.script_text, max_lines=2))
        cards.append(
            f"""
            <article class="card">
              <h2>{escape(plan.cast_id)} | {escape(plan.format_id)}</h2>
              {video_html}
              <dl>
                <dt>Structure</dt><dd>Talking head -> B-roll -> talking head</dd>
                <dt>Hook</dt><dd>{escape(plan.hook_text)}</dd>
                <dt>CTA</dt><dd>{escape(plan.cta_text)}</dd>
                <dt>Disclosure</dt><dd>{escape(plan.disclosure_text)}</dd>
                <dt>Status</dt><dd>{escape(result.get("status", "planned"))}</dd>
              </dl>
              <h3>Caption Lines</h3>
              <ol>{caption_lines}</ol>
              <h3>QA</h3>
              <ol>{''.join(f'<li>{escape(check)}</li>' for check in QA_CHECKS)}</ol>
              <section class="feedback" data-clip-id="{escape(clip_id)}" data-format="{escape(plan.format_id)}" data-clip-type="assembled">
                <h3>Joel Decision</h3>
                <label><input type="radio" name="{escape(clip_id)}_decision" value="winner"> Winner</label>
                <label><input type="radio" name="{escape(clip_id)}_decision" value="maybe"> Maybe</label>
                <label><input type="radio" name="{escape(clip_id)}_decision" value="reject"> Reject</label>
                <label><input type="checkbox" data-field="would_test_meta"> Would test in Meta</label>
                <textarea data-field="notes" placeholder="Best hook, worst artifact, what would make it launchable"></textarea>
              </section>
            </article>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Assembly Review</title>
  <style>
    body {{ margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #14213d; }}
    main {{ max-width: 1200px; margin: 0 auto; padding: 28px 18px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 36px; letter-spacing: 0; }}
    .summary {{ color: #526070; margin-bottom: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 18px; }}
    .feedback-panel {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
    .card {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(20,33,61,.08); }}
    h2 {{ margin: 0 0 12px; font-size: 18px; letter-spacing: 0; }}
    h3 {{ margin: 16px 0 6px; font-size: 12px; text-transform: uppercase; color: #637083; letter-spacing: .04em; }}
    video {{ width: 100%; aspect-ratio: 9 / 16; max-height: 620px; background: #111827; border-radius: 6px; }}
    .missing {{ aspect-ratio: 9 / 16; display: grid; place-items: center; padding: 18px; border-radius: 6px; background: #fff2f0; color: #9f1d14; text-align: center; }}
    dl {{ display: grid; grid-template-columns: 92px 1fr; gap: 6px 10px; font-size: 14px; }}
    dt {{ font-weight: 700; color: #374151; }}
    dd {{ margin: 0; color: #526070; }}
    ol {{ padding-left: 20px; line-height: 1.5; }}
    label {{ display: inline-flex; align-items: center; gap: 6px; margin: 6px 10px 6px 0; font-size: 13px; color: #374151; }}
    textarea {{ width: 100%; min-height: 76px; margin-top: 8px; border: 1px solid #cfd7e2; border-radius: 6px; padding: 8px; font: inherit; box-sizing: border-box; }}
    button {{ border: 0; border-radius: 6px; background: #4f46e5; color: #fff; padding: 9px 12px; font-weight: 700; cursor: pointer; }}
    #feedback-output {{ min-height: 110px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
  </style>
</head>
<body>
  <main>
    <h1>Video Assembly Review</h1>
    <p class="summary">{len(plans)} planned assemblies | generated {escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}</p>
    <section class="feedback-panel">
      <h2>Joel Feedback Export</h2>
      <p>Mark winners/rejects, add notes, then copy the JSON for Steven/Codex/Claude.</p>
      <button type="button" onclick="copyFeedback()">Copy Feedback JSON</button>
      <textarea id="feedback-output" readonly placeholder="Feedback JSON appears here after copying."></textarea>
    </section>
    <section class="grid">{''.join(cards)}</section>
  </main>
  <script>
    function copyFeedback() {{
      const rows = Array.from(document.querySelectorAll('.feedback')).map(section => {{
        const decision = section.querySelector('input[type="radio"]:checked');
        const wouldTest = section.querySelector('[data-field="would_test_meta"]').checked;
        const notes = section.querySelector('[data-field="notes"]').value;
        return {{
          clip_id: section.dataset.clipId,
          format: section.dataset.format,
          clip_type: section.dataset.clipType,
          decision: decision ? decision.value : '',
          would_test_meta: wouldTest,
          notes
        }};
      }});
      const payload = {{
        reviewed_at: new Date().toISOString(),
        review_page: 'assembly_output/review.html',
        feedback: rows
      }};
      const output = document.getElementById('feedback-output');
      output.value = JSON.stringify(payload, null, 2);
      output.select();
      navigator.clipboard?.writeText(output.value);
    }}
  </script>
</body>
</html>
"""
    REVIEW_PATH.write_text(html)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble fine-tuned video clips into polished 9:16 ad drafts.")
    parser.add_argument("--plan-only", action="store_true", help="Write assembly_plan.json and review.html without rendering videos.")
    parser.add_argument("--yes", action="store_true", help="Render videos with ffmpeg.")
    parser.add_argument("--cta", default=DEFAULT_CTA, help="CTA overlay text.")
    parser.add_argument("--disclosure", default=DEFAULT_DISCLOSURE, help="Small disclosure overlay text.")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "", help="Path to ffmpeg.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if bool(args.plan_only) == bool(args.yes):
        print("Choose exactly one mode: --plan-only or --yes", file=sys.stderr)
        return 2

    manifest = load_manifest()
    plans = build_plans(manifest, args.cta, args.disclosure)
    if not plans:
        print("No complete talking-head + B-roll pairs found in the fine-tuning manifest.", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    if args.yes:
        if not args.ffmpeg:
            print("ffmpeg was not found. Install ffmpeg or pass --ffmpeg /path/to/ffmpeg.", file=sys.stderr)
            return 1
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for plan in plans:
            print(f"Assembling {plan.output_file}")
            results.append(run_ffmpeg(plan, args.ffmpeg))

    write_plan(plans, results)
    build_review_html(plans, results)
    print(f"Assembly plan: {PLAN_PATH}")
    print(f"Review page: {REVIEW_PATH}")
    if results:
        print(f"Rendered: {sum(row['status'] == 'success' for row in results)} succeeded, {sum(row['status'] != 'success' for row in results)} failed")
    else:
        print("Plan-only mode complete. Render on a machine with ffmpeg using --yes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

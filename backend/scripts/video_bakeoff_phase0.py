#!/usr/bin/env python3
"""
Phase 0 kie.ai video provider bakeoff.

Standalone research script only. It does not import the app, write to the DB,
or touch shipped routes/models. Output is written under bakeoff_output/.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "bakeoff_output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
REVIEW_PATH = OUTPUT_DIR / "review.html"
BATCH_SUMMARY_PATH = OUTPUT_DIR / "batch_summary.json"

JOBS_URL = "https://api.kie.ai/api/v1/jobs"
FLUX_URL = "https://api.kie.ai/api/v1/flux/kontext"
UPLOAD_BASE64_URL = "https://kieai.redpandaai.co/api/file-base64-upload"
COMMON_API_URL = "https://api.kie.ai/api/v1"

POLL_INTERVAL_SECONDS = 5
TASK_TIMEOUT_SECONDS = 300

REVIEW_QUESTIONS = [
    "Does the person look believable?",
    "Is lip sync acceptable?",
    "Does commercial-insurance context read correctly?",
    "Is the first 3 seconds strong enough?",
    "Are captions/overlays needed to make it usable?",
]

NICHE_INPUTS = {
    "Barber shops": {
        "slug": "barber_shops",
        "risk_framing": "Slip/fall, equipment damage, client injury, lease/vendor requirements",
        "b_roll_scenes": "barber chair, tools, storefront, stylist cleaning station, customer waiting area",
        "proof_angle": "A small incident can become expensive fast.",
    },
    "Trucking": {
        "slug": "trucking",
        "risk_framing": "Liability, cargo, downtime, contract requirements",
        "b_roll_scenes": "truck yard, driver checking cab, loading area, road shot, paperwork",
        "proof_angle": "One claim or lapse can put the route at risk.",
    },
    "Religious organizations": {
        "slug": "religious_organizations",
        "risk_framing": "Property, events, volunteers, gatherings",
        "b_roll_scenes": "church exterior, fellowship hall, volunteers setting chairs, community event setup",
        "proof_angle": "Events and facilities create risks many teams overlook.",
    },
}

FORMAT_INPUTS = {
    "Business owner risk": {
        "slug": "business_owner_risk",
        "hook_style": "If you run a [niche], check this before your next busy day.",
        "body_structure": "overlooked risk -> consequence -> coverage reminder",
        "cta": "Compare coverage options",
    },
    "Cost shock / rate check": {
        "slug": "cost_shock_rate_check",
        "hook_style": "I didn't realize [niche] insurance could vary this much.",
        "body_structure": "rate variation -> why comparing matters -> no-pressure check",
        "cta": "Check your rate",
    },
    "Niche testimonial": {
        "slug": "niche_testimonial",
        "hook_style": "We thought we were covered until we looked closer.",
        "body_structure": "scenario -> gap/risk -> coverage option -> CTA",
        "cta": "Compare coverage options",
    },
}


@dataclass(frozen=True)
class ClipPlan:
    niche: str
    format_name: str
    clip_type: str
    model: str
    duration_seconds: int
    estimated_credits: float
    estimated_cost_usd: float
    prompt: str
    script_text: str | None = None

    @property
    def output_filename(self) -> str:
        niche_slug = NICHE_INPUTS[self.niche]["slug"]
        format_slug = FORMAT_INPUTS[self.format_name]["slug"]
        return f"{niche_slug}_{format_slug}_{self.clip_type}.mp4"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_api_key() -> str:
    load_env_file(Path.cwd() / ".env.local")
    load_env_file(Path.cwd() / "backend" / ".env.local")
    api_key = os.getenv("KIE_AI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "KIE_AI_API_KEY is not set. Put it in .env.local or export it in the shell; never commit it."
        )
    return api_key


def headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def request_json(method: str, url: str, api_key: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method, url, headers=headers(api_key), timeout=60, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:1000]}
    if response.status_code >= 400:
        message = payload.get("msg") or payload.get("message") or payload.get("raw") or payload
        raise RuntimeError(f"{method} {url} returned HTTP {response.status_code}: {message}")
    return payload


def parse_result_urls(data: dict[str, Any]) -> list[str]:
    result_json = data.get("resultJson") or data.get("response") or data.get("result")
    if isinstance(result_json, str):
        try:
            result = json.loads(result_json)
        except json.JSONDecodeError:
            result = {}
    elif isinstance(result_json, dict):
        result = result_json
    else:
        result = {}

    urls = result.get("resultUrls") or result.get("urls") or []
    if isinstance(urls, str):
        urls = [urls]

    for key in ("resultImageUrl", "resultAudioUrl", "audioUrl", "videoUrl", "url"):
        value = result.get(key) or data.get(key)
        if value and value not in urls:
            urls.append(value)
    return [url for url in urls if isinstance(url, str) and url.startswith("http")]


def create_task(api_key: str, payload: dict[str, Any]) -> str:
    task_data = request_json("POST", f"{JOBS_URL}/createTask", api_key, json=payload)
    data = task_data.get("data") or {}
    task_id = data.get("taskId")
    if not task_id:
        raise RuntimeError(f"kie.ai did not return a taskId: {task_data}")
    return task_id


def poll_task(api_key: str, task_id: str, label: str) -> dict[str, Any]:
    deadline = time.time() + TASK_TIMEOUT_SECONDS
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        time.sleep(POLL_INTERVAL_SECONDS)
        status = request_json(
            "GET",
            f"{JOBS_URL}/recordInfo",
            api_key,
            params={"taskId": task_id},
        )
        data = status.get("data") or {}
        state = (data.get("state") or "").lower()
        success_flag = data.get("successFlag")
        print(f"{label}: task={task_id} state={state or success_flag!r} attempt={attempt}")

        if state == "success" or success_flag == 1:
            return data
        if state in {"fail", "failed", "error"} or success_flag in {2, 3}:
            error = data.get("failMsg") or data.get("errorMessage") or data.get("msg") or status.get("msg")
            raise RuntimeError(error or f"kie.ai task failed with state={state} successFlag={success_flag}")

    raise TimeoutError(f"{label}: task {task_id} did not complete within {TASK_TIMEOUT_SECONDS} seconds")


def check_credit_balance(api_key: str) -> float | None:
    try:
        payload = request_json("GET", f"{COMMON_API_URL}/chat/credit", api_key)
        data = payload.get("data")
        return float(data) if data is not None else None
    except Exception as exc:
        print(f"Credit balance check skipped: {exc}")
        return None


def submit_flux_presenter_image(api_key: str) -> tuple[str, str, str]:
    prompt = (
        "professional adult in business casual attire, friendly expression, plain background, "
        "portrait orientation, facing camera, realistic commercial insurance UGC presenter, "
        "clean studio lighting, no text, no logos"
    )
    payload = {
        "model": "flux-kontext-pro",
        "prompt": prompt,
        "aspectRatio": "9:16",
        "outputFormat": "png",
        "promptUpsampling": True,
    }
    failures: list[str] = []

    try:
        response = request_json("POST", f"{FLUX_URL}/generate", api_key, json=payload)
        data = response.get("data") or {}
        task_id = data.get("taskId")
        if not task_id:
            raise RuntimeError(f"Flux presenter image did not return taskId: {response}")

        deadline = time.time() + TASK_TIMEOUT_SECONDS
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            status = request_json(
                "GET",
                f"{FLUX_URL}/record-info",
                api_key,
                params={"taskId": task_id},
            )
            data = status.get("data") or {}
            flag = data.get("successFlag")
            print(f"presenter image flux-kontext-pro: task={task_id} successFlag={flag!r}")
            if flag == 1:
                image_url = (data.get("response") or {}).get("resultImageUrl")
                if not image_url:
                    raise RuntimeError("Flux presenter image succeeded but returned no resultImageUrl")
                return image_url, task_id, "flux-kontext-pro"
            if flag in {2, 3}:
                error = data.get("errorMessage") or data.get("msg") or status.get("msg")
                raise RuntimeError(error or f"Flux presenter image failed with successFlag={flag}")

        raise TimeoutError(f"Presenter image flux-kontext-pro task {task_id} did not complete within {TASK_TIMEOUT_SECONDS} seconds")
    except Exception as exc:
        failures.append(f"flux-kontext-pro: {exc}")
        print(f"Presenter image flux-kontext-pro failed; falling back to flux-2/pro-text-to-image: {exc}")

    fallback_payload = {
        "model": "flux-2/pro-text-to-image",
        "input": {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "nsfw_checker": False,
        },
    }
    try:
        task_id = create_task(api_key, fallback_payload)
        data = poll_task(api_key, task_id, "presenter image flux-2/pro-text-to-image")
        urls = parse_result_urls(data)
        if not urls:
            raise RuntimeError(f"Flux fallback task {task_id} succeeded but no result URL was found")
        return urls[0], task_id, "flux-2/pro-text-to-image"
    except Exception as exc:
        failures.append(f"flux-2/pro-text-to-image: {exc}")
        raise RuntimeError("Both presenter image models failed: " + " | ".join(failures)) from exc


def submit_tts(api_key: str, text: str) -> tuple[str, str]:
    payload = {
        "model": "google/gemini-3-1-flash-tts",
        "input": {
            "temperature": 0.8,
            "scene": "Direct-response commercial insurance UGC ad hook. Natural, trustworthy, direct.",
            "sample_context": "A media buyer is testing short Meta ad hooks for commercial insurance niches.",
            "speakers": [
                {
                    "speaker_id": "Speaker 1",
                    "voice_name": "Puck",
                    "audio_profile": "A credible American business advisor, warm and clear.",
                    "accent": "American (Gen)",
                    "style": "Newscaster",
                    "pace": "Natural",
                }
            ],
            "dialogue_turns": [{"speaker_id": "Speaker 1", "text": text}],
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, "tts")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"TTS task {task_id} succeeded but no audio URL was found in resultJson")
    return urls[0], task_id


def upload_generated_url(api_key: str, source_url: str, file_name: str) -> str:
    response = requests.get(source_url, timeout=120)
    response.raise_for_status()
    mime_type = response.headers.get("content-type") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    data_url = f"data:{mime_type};base64,{base64.b64encode(response.content).decode('ascii')}"
    payload = {"base64Data": data_url, "uploadPath": "adbuilder/video-bakeoff", "fileName": file_name}
    upload = request_json("POST", UPLOAD_BASE64_URL, api_key, json=payload)
    uploaded = upload.get("data") or {}
    download_url = uploaded.get("downloadUrl")
    if not download_url:
        raise RuntimeError(f"File upload succeeded without downloadUrl: {upload}")
    return download_url


def build_talking_head_prompt(plan: ClipPlan) -> str:
    niche_data = NICHE_INPUTS[plan.niche]
    format_data = FORMAT_INPUTS[plan.format_name]
    return (
        "Speaking directly to camera in a serious but approachable tone. "
        "Plain UGC-style commercial insurance hook, realistic facial movement, natural lip sync. "
        f"Niche: {plan.niche}. Risk framing: {niche_data['risk_framing']}. "
        f"Body structure: {format_data['body_structure']}. CTA context: {format_data['cta']}. "
        "No on-screen text, no brand logos, no exaggerated emotion."
    )


def render_hook(format_name: str, niche: str) -> str:
    niche_phrase = {
        "Barber shops": "barber shop",
        "Trucking": "trucking business",
        "Religious organizations": "religious organization",
    }[niche]
    return FORMAT_INPUTS[format_name]["hook_style"].replace("[niche]", niche_phrase)


def build_script_text(niche: str, format_name: str) -> str:
    niche_data = NICHE_INPUTS[niche]
    format_data = FORMAT_INPUTS[format_name]
    hook = render_hook(format_name, niche)
    return (
        f"{hook} {niche_data['proof_angle']} "
        f"Business insurance and general liability coverage options can vary, so it is worth a no-pressure review."
    )


def build_broll_prompt(niche: str, format_name: str) -> str:
    niche_data = NICHE_INPUTS[niche]
    format_data = FORMAT_INPUTS[format_name]
    return (
        "Vertical 9:16 realistic UGC-style commercial insurance B-roll, no text, no logos, no identifiable brands. "
        f"Niche: {niche}. Scenes to show: {niche_data['b_roll_scenes']}. "
        f"Risk framing: {niche_data['risk_framing']}. Proof angle: {niche_data['proof_angle']} "
        f"Format hook style: {format_data['hook_style']} Body structure: {format_data['body_structure']}. "
        "Natural handheld camera feel, practical business environment, believable Meta ad creative."
    )


def build_clip_plans(include_extra: bool = False) -> list[ClipPlan]:
    plans = [
        ("Barber shops", "Business owner risk", "talking_head_hook"),
        ("Barber shops", "Cost shock / rate check", "broll_only"),
        ("Trucking", "Business owner risk", "talking_head_hook"),
        ("Trucking", "Niche testimonial", "broll_only"),
        ("Religious organizations", "Business owner risk", "talking_head_hook"),
        ("Religious organizations", "Niche testimonial", "broll_only"),
    ]
    if include_extra:
        plans.extend(
            [
                ("Barber shops", "Niche testimonial", "talking_head_hook"),
                ("Religious organizations", "Cost shock / rate check", "talking_head_hook"),
            ]
        )

    clip_plans: list[ClipPlan] = []
    for niche, format_name, clip_type in plans:
        if clip_type == "talking_head_hook":
            script_text = build_script_text(niche, format_name)
            prompt = build_talking_head_prompt(
                ClipPlan(niche, format_name, clip_type, "kling/ai-avatar-standard", 15, 120, 0.60, "", script_text)
            )
            clip_plans.append(
                ClipPlan(niche, format_name, clip_type, "kling/ai-avatar-standard", 15, 120, 0.60, prompt, script_text)
            )
        else:
            clip_plans.append(
                ClipPlan(
                    niche,
                    format_name,
                    clip_type,
                    "kling-3.0/video",
                    8,
                    112,
                    0.72,
                    build_broll_prompt(niche, format_name),
                )
            )
    return clip_plans


def print_dry_run(plans: list[ClipPlan]) -> None:
    print("Phase 0 kie.ai video bakeoff dry run")
    print(f"Output dir: {OUTPUT_DIR}")
    print("")
    for index, plan in enumerate(plans, 1):
        print(f"{index}. {plan.niche} | {plan.format_name} | {plan.clip_type}")
        print(f"   model={plan.model} duration={plan.duration_seconds}s")
        if plan.script_text:
            print(f"   script={plan.script_text}")
        print(f"   prompt={plan.prompt}")
        print("")
    total_credits = sum(plan.estimated_credits for plan in plans)
    total_cost = sum(plan.estimated_cost_usd for plan in plans)
    print(f"Estimated clip credits: {total_credits:.0f}")
    print(f"Estimated out-of-pocket cost: ${total_cost:.2f} plus negligible TTS/image setup")
    print("Confirmed account balance in brief: 4,698 credits as of 2026-07-30")


def load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return []
    return json.loads(MANIFEST_PATH.read_text())


def save_manifest(rows: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(rows, indent=2) + "\n")


def save_batch_summary(summary: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BATCH_SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")


def download_file(url: str, path: Path) -> None:
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def run_broll_clip(api_key: str, plan: ClipPlan) -> tuple[str, str]:
    payload = {
        "model": plan.model,
        "input": {
            "prompt": plan.prompt,
            "aspect_ratio": "9:16",
            "duration": str(plan.duration_seconds),
            "mode": "std",
            "multi_shots": False,
            "sound": False,
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, f"{plan.niche} {plan.clip_type}")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"B-roll task {task_id} succeeded but no result URL was found")
    return urls[0], task_id


def run_talking_head_clip(
    api_key: str,
    plan: ClipPlan,
    presenter_image_url: str,
    prebuilt_audio_url: str | None = None,
) -> tuple[str, str, str | None]:
    audio_task_id = None
    audio_url = prebuilt_audio_url
    if not audio_url:
        if not plan.script_text:
            raise RuntimeError("Talking-head clip is missing script_text")
        audio_url, audio_task_id = submit_tts(api_key, plan.script_text)
        audio_url = upload_generated_url(api_key, audio_url, f"{slugify(plan.niche)}_{slugify(plan.format_name)}.mp3")

    payload = {
        "model": plan.model,
        "input": {
            "image_url": presenter_image_url,
            "audio_url": audio_url,
            "prompt": plan.prompt,
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, f"{plan.niche} {plan.clip_type}")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"Talking-head task {task_id} succeeded but no result URL was found")
    return urls[0], task_id, audio_task_id


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def run_batch(args: argparse.Namespace) -> None:
    api_key = require_api_key()
    plans = build_clip_plans(include_extra=args.extra)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_credits = check_credit_balance(api_key)
    if start_credits is not None:
        print(f"Starting kie.ai credits: {start_credits:.2f}")

    presenter_image_url = args.presenter_image_url
    presenter_task_id = None
    presenter_model = "manual_url" if presenter_image_url else None
    if not presenter_image_url and any(plan.clip_type == "talking_head_hook" for plan in plans):
        print("Generating shared presenter image...")
        presenter_image_url, presenter_task_id, presenter_model = submit_flux_presenter_image(api_key)
        presenter_image_url = upload_generated_url(api_key, presenter_image_url, "phase0_presenter.png")
        print(f"Presenter image URL ready via {presenter_model}: {presenter_image_url}")

    rows = load_manifest()
    success_count = 0
    failure_count = 0

    for plan in plans:
        output_path = OUTPUT_DIR / plan.output_filename
        row = {
            "niche": plan.niche,
            "format": plan.format_name,
            "clip_type": plan.clip_type,
            "model": plan.model,
            "prompt": plan.prompt,
            "script_text": plan.script_text,
            "task_id": None,
            "audio_task_id": None,
            "presenter_task_id": presenter_task_id,
            "presenter_model": presenter_model,
            "result_url": None,
            "local_file": output_path.name,
            "status": "pending",
            "error": None,
            "credits_spent": None,
            "estimated_credits": plan.estimated_credits,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"\nRunning {plan.niche} | {plan.format_name} | {plan.clip_type}")
        try:
            if plan.clip_type == "talking_head_hook":
                if not presenter_image_url:
                    raise RuntimeError("No presenter image URL available for talking-head clip")
                result_url, task_id, audio_task_id = run_talking_head_clip(
                    api_key,
                    plan,
                    presenter_image_url,
                    prebuilt_audio_url=args.audio_url,
                )
                row["audio_task_id"] = audio_task_id
            else:
                result_url, task_id = run_broll_clip(api_key, plan)
            row["task_id"] = task_id
            row["result_url"] = result_url
            download_file(result_url, output_path)
            row["status"] = "success"
            success_count += 1
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            failure_count += 1
            print(f"FAILED: {exc}")
        rows.append(row)
        save_manifest(rows)

    end_credits = check_credit_balance(api_key)
    batch_summary = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "clips_planned": len(plans),
        "clips_succeeded": success_count,
        "clips_failed": failure_count,
        "start_credits": start_credits,
        "end_credits": end_credits,
        "credits_spent": None,
        "estimated_clip_credits": sum(plan.estimated_credits for plan in plans),
        "estimated_clip_cost_usd": sum(plan.estimated_cost_usd for plan in plans),
    }
    if start_credits is not None and end_credits is not None:
        spent = start_credits - end_credits
        batch_summary["credits_spent"] = spent
        print(f"Ending kie.ai credits: {end_credits:.2f}")
        print(f"Approx credits spent: {spent:.2f}")
    save_batch_summary(batch_summary)

    build_review_html(rows)
    print(f"\nBatch complete: {success_count} succeeded, {failure_count} failed")
    if failure_count:
        print("Failures:")
        for row in rows[-len(plans):]:
            if row["status"] == "failed":
                print(f"- {row['niche']} | {row['format']} | {row['clip_type']}: {row['error']}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Batch summary: {BATCH_SUMMARY_PATH}")
    print(f"Review page: {REVIEW_PATH}")


def build_review_html(rows: list[dict[str, Any]] | None = None) -> None:
    rows = rows if rows is not None else load_manifest()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cards = []
    for row in rows:
        local_file = row.get("local_file")
        video_html = (
            f'<video controls preload="metadata" src="{escape(local_file)}"></video>'
            if row.get("status") == "success" and local_file
            else f'<div class="missing">No playable local video. Status: {escape(str(row.get("status")))}</div>'
        )
        questions = "".join(f"<li>{escape(question)}</li>" for question in REVIEW_QUESTIONS)
        cards.append(
            f"""
            <article class="card">
              <header>
                <h2>{escape(row.get("niche", ""))}</h2>
                <div class="meta">{escape(row.get("format", ""))} | {escape(row.get("clip_type", ""))}</div>
              </header>
              {video_html}
              <section>
                <h3>Prompt</h3>
                <p>{escape(row.get("prompt") or "")}</p>
              </section>
              <section>
                <h3>Review Questions</h3>
                <ol>{questions}</ol>
              </section>
              {f'<p class="error">{escape(row.get("error") or "")}</p>' if row.get("error") else ""}
            </article>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phase 0 Video Provider Bakeoff</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #14213d;
      background: #f6f7f9;
    }}
    body {{ margin: 0; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 18px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 44px); letter-spacing: 0; }}
    .summary {{ margin: 0 0 24px; color: #526070; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
    .card {{
      background: #fff;
      border: 1px solid #dde3ea;
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(20, 33, 61, 0.08);
    }}
    h2 {{ margin: 0 0 4px; font-size: 20px; letter-spacing: 0; }}
    h3 {{ margin: 16px 0 6px; font-size: 13px; text-transform: uppercase; color: #637083; letter-spacing: 0.04em; }}
    .meta {{ color: #637083; font-size: 14px; }}
    video {{ width: 100%; aspect-ratio: 9 / 16; max-height: 620px; background: #111827; border-radius: 6px; margin-top: 14px; }}
    p {{ line-height: 1.5; }}
    ol {{ padding-left: 20px; line-height: 1.55; }}
    .missing {{ margin-top: 14px; padding: 18px; border-radius: 6px; background: #fff2f0; color: #9f1d14; }}
    .error {{ color: #9f1d14; background: #fff2f0; padding: 10px; border-radius: 6px; }}
  </style>
</head>
<body>
  <main>
    <h1>Phase 0 Video Provider Bakeoff</h1>
    <p class="summary">{len(rows)} manifest rows | generated {escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}</p>
    <div class="grid">
      {''.join(cards)}
    </div>
  </main>
</body>
</html>
"""
    REVIEW_PATH.write_text(html)
    print(f"Review page written: {REVIEW_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 0 kie.ai video provider bakeoff.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned calls and cost estimate; make no API calls.")
    parser.add_argument("--yes", action="store_true", help="Actually run the bakeoff batch.")
    parser.add_argument("--build-review", action="store_true", help="Regenerate review.html from manifest.json.")
    parser.add_argument("--extra", action="store_true", help="Add two extra talking-head variants for an 8-clip batch.")
    parser.add_argument("--presenter-image-url", help="Use an existing public presenter image URL instead of generating one.")
    parser.add_argument("--audio-url", help="Use an existing public audio URL for all talking-head clips instead of generating TTS.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = sum(bool(value) for value in (args.dry_run, args.yes, args.build_review))
    if selected != 1:
        print("Choose exactly one mode: --dry-run, --yes, or --build-review", file=sys.stderr)
        return 2

    if args.dry_run:
        print_dry_run(build_clip_plans(include_extra=args.extra))
        return 0
    if args.build_review:
        build_review_html()
        return 0
    run_batch(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

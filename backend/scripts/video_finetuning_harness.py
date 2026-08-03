#!/usr/bin/env python3
"""
Phase 0.5 kie.ai video fine-tuning harness.

Standalone research script only. It does not import app code, write to the DB,
or touch shipped routes/models. Output is written under finetuning_output/.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "finetuning_output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
REVIEW_PATH = OUTPUT_DIR / "review.html"
BATCH_SUMMARY_PATH = OUTPUT_DIR / "batch_summary.json"
CAST_ASSET_DIR = OUTPUT_DIR / "cast_assets"

JOBS_URL = "https://api.kie.ai/api/v1/jobs"
UPLOAD_BASE64_URL = "https://kieai.redpandaai.co/api/file-base64-upload"
COMMON_API_URL = "https://api.kie.ai/api/v1"

POLL_INTERVAL_SECONDS = 5
TASK_TIMEOUT_SECONDS = 900
REQUEST_TIMEOUT_SECONDS = 30
DOWNLOAD_TIMEOUT_SECONDS = 60
MEDIA_DURATION_TOLERANCE_SECONDS = 0.5
DEFAULT_MAX_PLANNED_CREDITS = 350
SEEDANCE_FAST_MODEL = "bytedance/seedance-2-fast"
OMNIHUMAN_LIP_SYNC_MODEL = "omnihuman-1-5"
SEEDANCE_RESOLUTION = "480p"
OMNIHUMAN_CREDITS_PER_SECOND = 27
SEEDANCE_BROLL_CREDITS_PER_SECOND = 15.5
MODE_FORMATS = {
    "draft": "quick_psa,loyalty_check",
    "contender": "driving,phone_check,loyalty_check,quick_psa",
    "final": "driving,phone_check,loyalty_check,quick_psa",
}
MODE_INCLUDE_BROLL = {
    "draft": False,
    "contender": False,
    "final": True,
}

NO_TEXT_CLOTHING_CLAUSE = (
    "Plain solid-color outfit with absolutely no text, no writing, no letters, "
    "no logo, no graphic, no pattern printed on it. Do not generate any readable or garbled text "
    "on clothing, backgrounds, dashboard displays, phone screens, road signs, captions, or watermarks."
)

NO_VEHICLE_MARKINGS_CLAUSE = (
    "Use tight chest-up or interior-only framing. Do not show exterior car doors, side panels, decals, "
    "stickers, labels, badges, brand marks, license plates, signage, or any typography-like shapes. "
    "All visible vehicle surfaces must be plain, cropped, and unmarked."
)

US_DRIVING_VISUAL_CLAUSE = (
    "United States left-hand-drive car only: steering wheel on the driver's left side, "
    "driver seated on the left side of the vehicle, right-side road driving context. "
    "Do not show right-hand-drive interiors."
)

PHONE_SCREEN_CLAUSE = (
    "Phone screen angled away from camera or dark/blurred; no readable text, no app UI, "
    "no fake insurance quote text, no numbers visible on the screen."
)

AUTO_INSURANCE_COMPLIANCE_CLAUSE = (
    "Use compliant auto insurance rate-shopping language only. Do not promise fixed savings, "
    "do not say the viewer is owed money, do not fake urgency, and do not mention competitor brands."
)

REVIEW_QUESTIONS = [
    "Does this match the cast photo?",
    "Does the person look believable?",
    "Is lip sync acceptable?",
    "Does the niche context read correctly?",
    "Is the first 3 seconds strong enough?",
    "Are captions/overlays needed to make it usable?",
    "Is all on-screen text real Latin text with no garbling or cloaked characters?",
    "Are hands, steering wheel, phone, and dashboard physically plausible?",
    "Does the CTA avoid fixed savings guarantees and fake scarcity?",
]

DEFAULT_CONFIG = {
    "niches": {
        "auto_insurance": {
            "label": "Auto Insurance",
            "audience": "drivers shopping for auto insurance coverage options",
            "risk_framing": "rate changes, coverage gaps, accident liability, deductible pressure",
            "cast_prompt": (
                "realistic adult driver age 30-45 in a clean parked United States left-hand-drive car, "
                "driver seated on the left side, casual solid-color shirt, friendly expression, "
                "natural daylight, phone visible but angled away with no screen text, auto insurance UGC ad presenter, "
                "no logos, no text, no writing, no patterns"
            ),
            "cast_identity_description": (
                "the same realistic adult driver from the reference photos, casual solid-color outfit, "
                "friendly and credible auto insurance shopper"
            ),
        }
    },
    "formats": {
        "driving": {
            "label": "Renewal Check",
            "script": (
                "If your insurance renewed automatically this year, watch this. "
                "That is exactly when you should compare your rate. "
                "Check your options before the next bill."
            ),
            "tone": "speaking directly to camera, calm and practical, helpful driver-to-driver tone, no hype",
            "broll_action": (
                "@driver sits in the driver's left-side seat of a parked United States car, checks mirrors, starts the car, "
                "and looks thoughtful before driving away"
            ),
            "broll_prompt": (
                "Vertical 9:16 realistic UGC-style auto insurance B-roll. @driver is in and around a parked United States "
                "left-hand-drive car, checking mirrors and preparing to drive. Natural daylight, handheld phone-shot feel. "
                "No text, no logos, no watermarks, no readable license plates, no dashboard text."
            ),
        },
        "phone_check": {
            "label": "Phone Rate Check",
            "script": (
                "I thought switching insurance was a whole thing. "
                "It is one form and a quick rate check. "
                "See what options show up for you."
            ),
            "tone": "speaking directly to camera, surprised but measured, no hype",
            "broll_action": (
                "@driver sits in the driver's left-side seat of a parked United States car and checks a phone for auto insurance "
                "options, then reacts with mild interest"
            ),
            "broll_prompt": (
                "Vertical 9:16 realistic UGC-style auto insurance B-roll. @driver sits in a parked United States left-hand-drive "
                "car checking a phone, then looks up with mild interest. Natural light. Phone screen angled away or blurred. "
                "No readable phone text, no logos, no captions, no watermark, no dashboard text."
            ),
        },
        "loyalty_check": {
            "label": "Loyalty Check",
            "script": (
                "I had the same insurance for years. "
                "Never once checked if it was still the best fit. "
                "Took less than two minutes to compare."
            ),
            "tone": "direct-to-camera UGC confession, credible, slightly surprised, conversational",
            "broll_action": (
                "@driver sits in a parked United States left-hand-drive car, looks at an insurance renewal email on a phone "
                "with the screen turned away, then looks back to camera with a small surprised reaction"
            ),
            "broll_prompt": (
                "Vertical 9:16 realistic UGC-style auto insurance B-roll. @driver sits in a parked United States left-hand-drive "
                "car and checks a phone angled away from camera. Natural handheld phone-shot feel, direct-response ad pacing. "
                "No readable phone text, no logos, no captions, no watermark, no dashboard text."
            ),
        },
        "quick_psa": {
            "label": "Quick PSA",
            "script": (
                "Quick PSA if you drive and have not checked your insurance in a year. "
                "You might be overpaying without realizing it. "
                "Compare your rate free."
            ),
            "tone": "fast but natural UGC PSA, friendly, confident, strong first three seconds",
            "broll_action": (
                "@driver stands near a parked United States car in a driveway or parking lot and gestures lightly while speaking, "
                "then glances toward the car keys or phone"
            ),
            "broll_prompt": (
                "Vertical 9:16 realistic UGC-style auto insurance B-roll. @driver stands near a parked United States car in "
                "natural daylight, holding keys or a phone. Handheld creator-style framing, clean background. "
                "No readable text, no logos, no watermarks, no license plate text."
            ),
        },
    },
}


@dataclass(frozen=True)
class CastPlan:
    niche_id: str
    cast_index: int
    element_name: str
    base_prompt: str
    variant_prompts: tuple[str, ...]
    identity_description: str
    voice_profile: dict[str, str]

    @property
    def cast_id(self) -> str:
        return f"{self.niche_id}_cast_{self.cast_index}"


@dataclass(frozen=True)
class ClipPlan:
    niche_id: str
    format_id: str
    cast_id: str
    clip_type: str
    model: str
    prompt: str
    script_text: str | None
    duration_seconds: int
    estimated_credits: float
    estimated_cost_usd: float

    @property
    def output_filename(self) -> str:
        if is_seedance_model(self.model) or is_omnihuman_model(self.model):
            model_slug = slugify(self.model.split("/", 1)[-1])
            return f"{self.cast_id}_{self.niche_id}_{self.format_id}_{self.clip_type}_{model_slug}.mp4"
        return f"{self.cast_id}_{self.niche_id}_{self.format_id}_{self.clip_type}.mp4"


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def is_seedance_model(model: str) -> bool:
    return model.startswith("bytedance/seedance")


def is_omnihuman_model(model: str) -> bool:
    return model == OMNIHUMAN_LIP_SYNC_MODEL


def log(message: str) -> None:
    print(message, flush=True)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def read_keychain_secret(service_names: tuple[str, ...]) -> str:
    for service_name in service_names:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", os.getenv("USER", ""), "-s", service_name, "-w"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
        value = result.stdout.strip()
        if value:
            return value
    return ""


def require_api_key() -> str:
    load_env_file(Path.cwd() / ".env.local")
    load_env_file(Path.cwd() / "backend" / ".env.local")
    api_key = os.getenv("KIE_AI_API_KEY", "").strip()
    if not api_key:
        api_key = read_keychain_secret(("kie-ai-api", "KIE_AI_API_KEY", "kie.ai"))
    if not api_key:
        raise SystemExit("KIE_AI_API_KEY is not set. Export it, put it in a gitignored .env.local, or save it in Keychain service kie-ai-api.")
    return api_key


def headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def request_json(method: str, url: str, api_key: str, **kwargs: Any) -> dict[str, Any]:
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT_SECONDS)
    response = requests.request(method, url, headers=headers(api_key), timeout=timeout, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:1000]}
    if response.status_code >= 400:
        message = payload.get("msg") or payload.get("message") or payload.get("raw") or payload
        raise RuntimeError(f"{method} {url} returned HTTP {response.status_code}: {message}")
    return payload


def create_task(api_key: str, payload: dict[str, Any]) -> str:
    model = payload.get("model", "unknown")
    log(f"Submitting kie.ai task: model={model}")
    task_data = request_json("POST", f"{JOBS_URL}/createTask", api_key, json=payload)
    data = task_data.get("data") or {}
    task_id = data.get("taskId")
    if not task_id:
        raise RuntimeError(f"kie.ai did not return a taskId: {task_data}")
    log(f"Created kie.ai task: model={model} task={task_id}")
    return task_id


def poll_task(api_key: str, task_id: str, label: str) -> dict[str, Any]:
    deadline = time.time() + TASK_TIMEOUT_SECONDS
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        time.sleep(POLL_INTERVAL_SECONDS)
        status = request_json("GET", f"{JOBS_URL}/recordInfo", api_key, params={"taskId": task_id})
        data = status.get("data") or {}
        state = (data.get("state") or "").lower()
        success_flag = data.get("successFlag")
        log(f"{label}: task={task_id} state={state or success_flag!r} attempt={attempt}")
        if state == "success" or success_flag == 1:
            return data
        if state in {"fail", "failed", "error"} or success_flag in {2, 3}:
            error = data.get("failMsg") or data.get("errorMessage") or data.get("msg") or status.get("msg")
            raise RuntimeError(error or f"kie.ai task failed with state={state} successFlag={success_flag}")
    raise TimeoutError(f"{label}: task {task_id} did not complete within {TASK_TIMEOUT_SECONDS} seconds")


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


def check_credit_balance(api_key: str) -> float | None:
    try:
        payload = request_json("GET", f"{COMMON_API_URL}/chat/credit", api_key)
        data = payload.get("data")
        return float(data) if data is not None else None
    except Exception as exc:
        log(f"Credit balance check skipped: {exc}")
        return None


def upload_bytes(api_key: str, content: bytes, file_name: str, mime_type: str | None = None) -> str:
    resolved_mime_type = mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    data_url = f"data:{resolved_mime_type};base64,{base64.b64encode(content).decode('ascii')}"
    payload = {"base64Data": data_url, "uploadPath": "adbuilder/video-finetuning", "fileName": file_name}
    log(f"Uploading file to kie.ai storage: {file_name} ({len(content)} bytes)")
    upload = request_json("POST", UPLOAD_BASE64_URL, api_key, json=payload)
    uploaded = upload.get("data") or {}
    download_url = uploaded.get("downloadUrl")
    if not download_url:
        raise RuntimeError(f"File upload succeeded without downloadUrl: {upload}")
    return download_url


def upload_generated_url(api_key: str, source_url: str, file_name: str, local_path: Path | None = None) -> str:
    log(f"Downloading generated asset for upload: {file_name}")
    response = requests.get(source_url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    if local_path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.content)
    return upload_bytes(api_key, response.content, file_name, response.headers.get("content-type"))


def hosted_url_is_fetchable(url: str) -> bool:
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        if response.status_code == 405:
            response = requests.get(url, stream=True, timeout=10)
        return response.status_code < 400
    except requests.RequestException:
        return False


def refresh_cast_photo_urls(api_key: str, cast: dict[str, Any], force: bool = False) -> bool:
    refreshed = False
    photo_rows = cast.get("photos") or []
    for index, photo in enumerate(photo_rows):
        current_url = photo.get("url") or ""
        if current_url and not force and hosted_url_is_fetchable(current_url):
            continue

        kind = photo.get("kind") or f"photo_{index + 1}"
        file_name = f"{cast['cast_id']}_{kind}.png"
        local_file = photo.get("local_file") or f"cast_assets/{file_name}"
        local_path = OUTPUT_DIR / local_file

        if local_path.exists():
            hosted_url = upload_bytes(api_key, local_path.read_bytes(), file_name, mimetypes.guess_type(file_name)[0])
        elif photo.get("source_url"):
            hosted_url = upload_generated_url(api_key, photo["source_url"], file_name, local_path)
        else:
            raise RuntimeError(f"Cast {cast['cast_id']} photo {kind} has no reusable local_file or source_url")

        photo["url"] = hosted_url
        photo["local_file"] = local_file
        refreshed = True
        print(f"Refreshed cast photo {cast['cast_id']} {kind}")

    if photo_rows:
        cast["photo_urls"] = [row["url"] for row in photo_rows if row.get("url")]
    return refreshed


def download_file(url: str, path: Path) -> None:
    log(f"Downloading completed clip: {path.name}")
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def probe_media(path: Path | str) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,duration,width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def parse_duration(value: Any) -> float | None:
    if value in (None, "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def media_summary(path: Path | str) -> dict[str, Any]:
    data = probe_media(path)
    streams = data.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    format_duration = parse_duration(data.get("format", {}).get("duration"))
    video_duration = parse_duration((video_stream or {}).get("duration")) or format_duration
    audio_duration = parse_duration((audio_stream or {}).get("duration"))
    duration_delta = None
    if video_duration is not None and audio_duration is not None:
        duration_delta = abs(video_duration - audio_duration)
    return {
        "duration": format_duration,
        "video_duration": video_duration,
        "audio_duration": audio_duration,
        "duration_delta": duration_delta,
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "streams": streams,
    }


def media_has_audio(path: Path) -> bool:
    return media_summary(path)["has_audio"]


def mux_audio(video_path: Path, audio_url: str) -> None:
    tmp_path = video_path.with_name(f"{video_path.stem}_with_audio_tmp{video_path.suffix}")
    log(f"Muxing cached TTS audio onto clip and trimming to spoken length: {video_path.name}")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            audio_url,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tmp_path.replace(video_path)


def trim_to_audio(video_path: Path) -> None:
    tmp_path = video_path.with_name(f"{video_path.stem}_trimmed_tmp{video_path.suffix}")
    log(f"Trimming clip to shortest stream for audio/video duration match: {video_path.name}")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-shortest",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tmp_path.replace(video_path)


def validate_clip_file(path: Path, plan: ClipPlan, tts: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Downloaded clip is missing or empty: {path}")

    summary = media_summary(path)
    if not summary["has_video"]:
        raise RuntimeError(f"Downloaded clip is missing a video stream: {path.name}")

    if plan.clip_type == "talking_head":
        audio_url = (tts or {}).get("url")
        if not summary["has_audio"]:
            if audio_url:
                mux_audio(path, audio_url)
                summary = media_summary(path)
            if not summary["has_audio"]:
                raise RuntimeError(f"Talking-head clip is missing an audio stream after download: {path.name}")

        duration_delta = summary.get("duration_delta")
        if duration_delta is None or duration_delta > MEDIA_DURATION_TOLERANCE_SECONDS:
            if audio_url:
                mux_audio(path, audio_url)
            else:
                trim_to_audio(path)
            summary = media_summary(path)
            duration_delta = summary.get("duration_delta")

        if duration_delta is None or duration_delta > MEDIA_DURATION_TOLERANCE_SECONDS:
            raise RuntimeError(
                f"Talking-head audio/video duration mismatch for {path.name}: "
                f"video={summary.get('video_duration')}s audio={summary.get('audio_duration')}s "
                f"delta={duration_delta}s"
            )

    return summary


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return DEFAULT_CONFIG
    config_path = Path(path)
    with config_path.open() as handle:
        data = json.load(handle)
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged["niches"].update(data.get("niches", {}))
    merged["formats"].update(data.get("formats", {}))
    return merged


def selected_ids(raw: str, available: dict[str, Any], label: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    missing = [item for item in values if item not in available]
    if missing:
        raise SystemExit(f"Unknown {label}: {', '.join(missing)}. Available: {', '.join(sorted(available))}")
    return values


def hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def build_cast_plans(config: dict[str, Any], niche_ids: list[str], cast_count: int) -> list[CastPlan]:
    plans: list[CastPlan] = []
    for niche_id in niche_ids:
        niche = config["niches"][niche_id]
        for index in range(1, cast_count + 1):
            element_name = f"{slugify(niche_id)}_driver_{index}"
            cast_age_band = "30-45" if index % 2 else "50-65"
            voice_profile = {
                "age_band": cast_age_band,
                "elevenlabs_voice": "Rachel" if index % 2 else "Antoni",
                "gemini_voice_name": "Puck" if index % 2 else "Charon",
                "audio_profile": (
                    "A credible American driver in their thirties or early forties, warm and clear."
                    if index % 2
                    else "A credible older American driver, grounded, lower register, measured and clear."
                ),
                "style": "Newscaster" if index % 2 else "Empathetic",
                "pace": "Natural",
            }
            base_prompt = (
                f"{niche['cast_prompt']}. Cast identity {index}: distinct realistic face, age {cast_age_band}. "
                f"{US_DRIVING_VISUAL_CLAUSE} {PHONE_SCREEN_CLAUSE} "
                "Same person must be reusable across later reference edits."
            )
            variant_prompts = (
                (
                    "Create a second angle of the same person from the reference image, seated in the driver's left-side seat "
                    "of a parked United States left-hand-drive car, solid-color outfit, natural expression. "
                    f"{US_DRIVING_VISUAL_CLAUSE} {PHONE_SCREEN_CLAUSE} {NO_TEXT_CLOTHING_CLAUSE}"
                ),
                (
                    "Create a waist-up outdoor parking-lot angle of the same person from the reference image, "
                    f"same face and age {cast_age_band}, solid-color outfit, standing near a United States car. "
                    f"{NO_TEXT_CLOTHING_CLAUSE}"
                ),
            )
            plans.append(
                CastPlan(
                    niche_id=niche_id,
                    cast_index=index,
                    element_name=element_name,
                    base_prompt=base_prompt,
                    variant_prompts=variant_prompts,
                    identity_description=niche["cast_identity_description"],
                    voice_profile=voice_profile,
                )
            )
    return plans


def avatar_prompt(format_data: dict[str, Any], niche_data: dict[str, Any]) -> str:
    return (
        f"{format_data['tone']}. Realistic lip sync for a short UGC auto insurance ad. "
        f"Audience: {niche_data['audience']}. "
        f"Risk framing: {niche_data['risk_framing']}. "
        f"{AUTO_INSURANCE_COMPLIANCE_CLAUSE} {NO_TEXT_CLOTHING_CLAUSE} {NO_VEHICLE_MARKINGS_CLAUSE}"
    )


def build_clip_plans(
    config: dict[str, Any],
    niche_ids: list[str],
    format_ids: list[str],
    cast_plans: list[CastPlan],
    video_provider: str = "kling",
) -> list[ClipPlan]:
    plans: list[ClipPlan] = []
    for cast in cast_plans:
        niche = config["niches"][cast.niche_id]
        for format_id in format_ids:
            format_data = config["formats"][format_id]
            talking_head_duration = 15
            talking_head_model = "kling/ai-avatar-standard"
            talking_head_credits = 120
            talking_head_cost = 0.60
            broll_duration = 8
            broll_model = "kling-3.0/video"
            broll_credits = 112
            broll_cost = 0.72
            if video_provider == "seedance":
                talking_head_model = OMNIHUMAN_LIP_SYNC_MODEL
                talking_head_credits = talking_head_duration * OMNIHUMAN_CREDITS_PER_SECOND
                talking_head_cost = talking_head_credits * 0.005
                broll_model = SEEDANCE_FAST_MODEL
                broll_credits = broll_duration * SEEDANCE_BROLL_CREDITS_PER_SECOND
                broll_cost = broll_credits * 0.005
            plans.append(
                ClipPlan(
                    niche_id=cast.niche_id,
                    format_id=format_id,
                    cast_id=cast.cast_id,
                    clip_type="talking_head",
                    model=talking_head_model,
                    prompt=avatar_prompt(format_data, niche),
                    script_text=format_data["script"],
                    duration_seconds=talking_head_duration,
                    estimated_credits=talking_head_credits,
                    estimated_cost_usd=talking_head_cost,
                )
            )
            broll_prompt = (
                f"{format_data['broll_prompt'].replace('@driver', f'@{cast.element_name}')} "
                f"{format_data['broll_action'].replace('@driver', f'@{cast.element_name}')}. "
                f"Context: {niche['risk_framing']}. Keep the same person as @{cast.element_name}. "
                f"{US_DRIVING_VISUAL_CLAUSE} {PHONE_SCREEN_CLAUSE} {AUTO_INSURANCE_COMPLIANCE_CLAUSE} "
                f"{NO_TEXT_CLOTHING_CLAUSE} {NO_VEHICLE_MARKINGS_CLAUSE}"
            )
            plans.append(
                ClipPlan(
                    niche_id=cast.niche_id,
                    format_id=format_id,
                    cast_id=cast.cast_id,
                    clip_type="broll",
                    model=broll_model,
                    prompt=broll_prompt,
                    script_text=None,
                    duration_seconds=broll_duration,
                    estimated_credits=broll_credits,
                    estimated_cost_usd=broll_cost,
                )
            )
    return plans


def filter_clip_plans(clip_plans: list[ClipPlan], include_broll: bool) -> list[ClipPlan]:
    if include_broll:
        return clip_plans
    return [plan for plan in clip_plans if plan.clip_type == "talking_head"]


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"casts": {}, "clips": [], "batches": []}
    return json.loads(MANIFEST_PATH.read_text())


def save_manifest(manifest: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")


def submit_flux_text_to_image(api_key: str, prompt: str, label: str) -> tuple[str, str]:
    payload = {
        "model": "flux-2/pro-text-to-image",
        "input": {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "nsfw_checker": False,
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, label)
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"{label} succeeded but no result URL was found")
    return urls[0], task_id


def submit_flux_image_to_image(api_key: str, input_urls: list[str], prompt: str, label: str) -> tuple[str, str]:
    payload = {
        "model": "flux-2/pro-image-to-image",
        "input": {
            "input_urls": input_urls,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "1K",
            "nsfw_checker": False,
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, label)
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"{label} succeeded but no result URL was found")
    return urls[0], task_id


def ensure_cast_library(api_key: str, cast_plans: list[CastPlan], manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    casts = manifest.setdefault("casts", {})
    for cast in cast_plans:
        existing = casts.get(cast.cast_id)
        if existing and len(existing.get("photo_urls", [])) >= 2:
            existing.setdefault("voice_profile", cast.voice_profile)
            existing.setdefault("identity_description", cast.identity_description)
            if refresh_cast_photo_urls(api_key, existing):
                print(f"Refreshed hosted image URLs for reused cast {cast.cast_id}")
            save_manifest(manifest)
            print(f"Reusing cast {cast.cast_id} with {len(existing['photo_urls'])} photos")
            continue

        print(f"Generating cast library for {cast.cast_id}")
        photo_rows = []
        base_url, base_task_id = submit_flux_text_to_image(api_key, cast.base_prompt, f"{cast.cast_id} base photo")
        base_local_file = f"cast_assets/{cast.cast_id}_base.png"
        hosted_base_url = upload_generated_url(api_key, base_url, f"{cast.cast_id}_base.png", OUTPUT_DIR / base_local_file)
        photo_rows.append(
            {
                "kind": "base",
                "url": hosted_base_url,
                "source_url": base_url,
                "local_file": base_local_file,
                "task_id": base_task_id,
                "prompt": cast.base_prompt,
            }
        )

        for variant_index, prompt in enumerate(cast.variant_prompts, 1):
            variant_url, variant_task_id = submit_flux_image_to_image(
                api_key,
                [hosted_base_url],
                prompt,
                f"{cast.cast_id} variant {variant_index}",
            )
            variant_local_file = f"cast_assets/{cast.cast_id}_variant_{variant_index}.png"
            hosted_variant_url = upload_generated_url(
                api_key,
                variant_url,
                f"{cast.cast_id}_variant_{variant_index}.png",
                OUTPUT_DIR / variant_local_file,
            )
            photo_rows.append(
                {
                    "kind": f"variant_{variant_index}",
                    "url": hosted_variant_url,
                    "source_url": variant_url,
                    "local_file": variant_local_file,
                    "task_id": variant_task_id,
                    "prompt": prompt,
                }
            )

        casts[cast.cast_id] = {
            "cast_id": cast.cast_id,
            "niche_id": cast.niche_id,
            "element_name": cast.element_name,
            "identity_description": cast.identity_description,
            "voice_profile": cast.voice_profile,
            "photos": photo_rows,
            "photo_urls": [row["url"] for row in photo_rows],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        save_manifest(manifest)
    return casts


def submit_tts_elevenlabs(api_key: str, text: str, voice_profile: dict[str, str]) -> tuple[str, str, str]:
    payload = {
        "model": "elevenlabs/text-to-speech-turbo-2-5",
        "input": {
            "text": text,
            "voice": voice_profile.get("elevenlabs_voice", "Rachel"),
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0,
            "speed": 1,
            "timestamps": False,
            "previous_text": "",
            "next_text": "",
            "language_code": "",
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, "tts elevenlabs")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"ElevenLabs TTS task {task_id} succeeded but no audio URL was found")
    return urls[0], task_id, "elevenlabs/text-to-speech-turbo-2-5"


def submit_tts_gemini(api_key: str, text: str, voice_profile: dict[str, str]) -> tuple[str, str, str]:
    payload = {
        "model": "google/gemini-3-1-flash-tts",
        "input": {
            "temperature": 0.8,
            "scene": "Short direct-response auto insurance UGC ad hook. Natural, trustworthy, direct.",
            "sample_context": "A media buyer is testing short Meta ad hooks for auto insurance creative.",
            "speakers": [
                {
                    "speaker_id": "Speaker 1",
                    "voice_name": voice_profile.get("gemini_voice_name", "Puck"),
                    "audio_profile": voice_profile.get("audio_profile", "A credible American driver, warm and clear."),
                    "accent": "American (Gen)",
                    "style": voice_profile.get("style", "Newscaster"),
                    "pace": voice_profile.get("pace", "Natural"),
                }
            ],
            "dialogue_turns": [{"speaker_id": "Speaker 1", "text": text}],
        },
    }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, "tts gemini")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"Gemini TTS task {task_id} succeeded but no audio URL was found")
    return urls[0], task_id, "google/gemini-3-1-flash-tts"


def submit_tts_with_fallback(
    api_key: str,
    text: str,
    file_stem: str,
    voice_profile: dict[str, str],
    provider_mode: str,
    manifest: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    cache_key = hash_payload(
        {
            "provider_mode": provider_mode,
            "text": text,
            "voice_profile": voice_profile,
        }
    )
    tts_cache = manifest.setdefault("tts_cache", {})
    if not force and cache_key in tts_cache:
        cached = dict(tts_cache[cache_key])
        cached["cache_key"] = cache_key
        cached["reused"] = True
        print(f"Reusing TTS cache for {file_stem}")
        return cached

    provider_modes = {
        "auto": (submit_tts_elevenlabs, submit_tts_gemini),
        "elevenlabs": (submit_tts_elevenlabs,),
        "gemini": (submit_tts_gemini,),
    }
    failures = []
    for submitter in provider_modes[provider_mode]:
        try:
            audio_url, task_id, provider = submitter(api_key, text, voice_profile)
            hosted_audio_url = upload_generated_url(api_key, audio_url, f"{file_stem}.mp3")
            return {
                "cache_key": cache_key,
                "url": hosted_audio_url,
                "source_url": audio_url,
                "task_id": task_id,
                "provider": provider,
                "voice_profile": voice_profile,
                "failures": failures,
                "reused": False,
            }
        except Exception as exc:
            provider_name = "elevenlabs/text-to-speech-turbo-2-5" if submitter is submit_tts_elevenlabs else "google/gemini-3-1-flash-tts"
            failures.append({"provider": provider_name, "error": str(exc)})
            print(f"TTS provider failed ({provider_name}); trying fallback if available: {exc}")
    raise RuntimeError("All TTS providers failed: " + json.dumps(failures))


def run_talking_head(api_key: str, plan: ClipPlan, cast: dict[str, Any], provider_mode: str, manifest: dict[str, Any], force_tts: bool = False) -> tuple[str, str, dict[str, Any]]:
    tts = submit_tts_with_fallback(
        api_key,
        plan.script_text or "",
        f"{plan.cast_id}_{plan.format_id}_voice",
        cast.get("voice_profile") or {},
        provider_mode,
        manifest,
        force_tts,
    )
    if not tts.get("reused"):
        manifest.setdefault("tts_cache", {})[tts["cache_key"]] = tts
        save_manifest(manifest)
    if is_omnihuman_model(plan.model):
        payload = {
            "model": plan.model,
            "input": {
                "image_url": cast["photo_urls"][0],
                "audio_url": tts["url"],
                "prompt": plan.prompt,
            },
        }
    elif is_seedance_model(plan.model):
        raise RuntimeError("Seedance is not a lip-sync model; use OmniHuman for talking-head clips")
    else:
        payload = {
            "model": plan.model,
            "input": {
                "image_url": cast["photo_urls"][0],
                "audio_url": tts["url"],
                "prompt": plan.prompt,
            },
        }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, f"{plan.cast_id} {plan.format_id} talking head")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"Talking-head task {task_id} succeeded but no result URL was found")
    return urls[0], task_id, tts


def run_broll(api_key: str, plan: ClipPlan, cast: dict[str, Any]) -> tuple[str, str]:
    if is_seedance_model(plan.model):
        payload = {
            "model": plan.model,
            "input": {
                "prompt": plan.prompt.replace(f"@{cast['element_name']}", "the referenced driver"),
                "reference_image_urls": cast["photo_urls"][:3],
                "reference_video_urls": [],
                "reference_audio_urls": [],
                "generate_audio": False,
                "resolution": SEEDANCE_RESOLUTION,
                "aspect_ratio": "9:16",
                "duration": plan.duration_seconds,
            },
        }
    else:
        payload = {
            "model": plan.model,
            "input": {
                "prompt": plan.prompt,
                "aspect_ratio": "9:16",
                "duration": str(plan.duration_seconds),
                "mode": "std",
                "multi_shots": False,
                "sound": False,
                "kling_elements": [
                    {
                        "name": cast["element_name"],
                        "description": cast["identity_description"],
                        "element_input_urls": cast["photo_urls"][:3],
                    }
                ],
            },
        }
    task_id = create_task(api_key, payload)
    data = poll_task(api_key, task_id, f"{plan.cast_id} {plan.format_id} broll")
    urls = parse_result_urls(data)
    if not urls:
        raise RuntimeError(f"B-roll task {task_id} succeeded but no result URL was found")
    return urls[0], task_id


def estimate(cast_count: int, clip_plans: list[ClipPlan]) -> dict[str, float]:
    cast_image_count = cast_count * 3
    cast_image_credits = cast_image_count * 8
    clip_credits = sum(plan.estimated_credits for plan in clip_plans)
    clip_cost = sum(plan.estimated_cost_usd for plan in clip_plans)
    cast_image_cost = cast_image_count * 0.04
    return {
        "cast_image_count": cast_image_count,
        "cast_image_credits": cast_image_credits,
        "cast_image_cost_usd": cast_image_cost,
        "clip_credits": clip_credits,
        "clip_cost_usd": clip_cost,
        "total_credits": cast_image_credits + clip_credits,
        "total_cost_usd": cast_image_cost + clip_cost,
    }


def print_dry_run(cast_plans: list[CastPlan], clip_plans: list[ClipPlan], provider_mode: str, video_provider: str) -> None:
    costs = estimate(len(cast_plans), clip_plans)
    print("Phase 0.5 video fine-tuning harness dry run")
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Video provider: {video_provider}")
    print(f"TTS provider mode: {provider_mode}")
    print("")
    print(f"Cast identities: {len(cast_plans)}")
    for cast in cast_plans:
        print(
            f"- {cast.cast_id}: @{cast.element_name} | age {cast.voice_profile['age_band']} | "
            f"ElevenLabs {cast.voice_profile['elevenlabs_voice']} / Gemini {cast.voice_profile['gemini_voice_name']}"
        )
    print("")
    print(f"Clips planned: {len(clip_plans)}")
    for index, plan in enumerate(clip_plans, 1):
        print(f"{index}. {plan.cast_id} | {plan.niche_id} | {plan.format_id} | {plan.clip_type}")
        print(f"   model={plan.model} duration={plan.duration_seconds}s")
        if plan.clip_type == "talking_head" and is_omnihuman_model(plan.model):
            print("   lip_sync=OmniHuman derives timing from audio_url; duration/cost is a conservative planning estimate")
        if plan.script_text:
            print(f"   script={plan.script_text}")
        print(f"   prompt={plan.prompt}")
    print("")
    print(f"Estimated cast images: {costs['cast_image_count']:.0f} images, ~{costs['cast_image_credits']:.0f} credits, ~${costs['cast_image_cost_usd']:.2f}")
    print(f"Estimated clips: ~{costs['clip_credits']:.0f} credits, ~${costs['clip_cost_usd']:.2f}")
    print(f"Estimated total: ~{costs['total_credits']:.0f} credits, ~${costs['total_cost_usd']:.2f}")
    print(
        "Pricing note: image estimates use Kie/Flux public pages checked 2026-07-31; "
        "Kling video estimates reuse confirmed Phase 0 planning costs; OmniHuman talking-head "
        "estimates use 27 credits/s; Seedance B-roll estimates use 480p no-reference-video pricing."
    )


def find_reusable_clip(manifest: dict[str, Any], plan: ClipPlan) -> dict[str, Any] | None:
    for clip in reversed(manifest.get("clips", [])):
        if clip.get("status") not in {"success", "reused"}:
            continue
        if clip.get("cast_id") != plan.cast_id:
            continue
        if clip.get("model") != plan.model:
            continue
        if clip.get("format_id") != plan.format_id or clip.get("clip_type") != plan.clip_type:
            continue
        if clip.get("prompt") != plan.prompt or (clip.get("script_text") or None) != plan.script_text:
            continue
        local_file = clip.get("local_file")
        if local_file and (OUTPUT_DIR / local_file).exists():
            return clip
    return None


def run_batch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    niche_ids = selected_ids(args.niches, config["niches"], "niches")
    format_ids = selected_ids(args.formats or MODE_FORMATS[args.mode], config["formats"], "formats")
    cast_plans = build_cast_plans(config, niche_ids, args.cast_count)
    clip_plans = filter_clip_plans(
        build_clip_plans(config, niche_ids, format_ids, cast_plans, args.video_provider),
        include_broll=args.include_broll,
    )
    planned_costs = estimate(len(cast_plans), clip_plans)
    if planned_costs["total_credits"] > args.max_planned_credits and not args.override_cost_cap:
        raise SystemExit(
            f"Planned batch is ~{planned_costs['total_credits']:.0f} credits, above cap "
            f"{args.max_planned_credits:.0f}. Use --max-planned-credits or --override-cost-cap intentionally."
        )

    api_key = require_api_key()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    start_credits = check_credit_balance(api_key)
    if start_credits is not None:
        print(f"Starting kie.ai credits: {start_credits:.2f}")

    casts = ensure_cast_library(api_key, cast_plans, manifest)
    success_count = 0
    failure_count = 0
    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for plan in clip_plans:
        cast = casts[plan.cast_id]
        output_path = OUTPUT_DIR / plan.output_filename
        row = {
            "batch_id": batch_id,
            "cast_id": plan.cast_id,
            "niche_id": plan.niche_id,
            "format_id": plan.format_id,
            "clip_type": plan.clip_type,
            "model": plan.model,
            "prompt": plan.prompt,
            "script_text": plan.script_text,
            "task_id": None,
            "result_url": None,
            "local_file": output_path.name,
            "status": "pending",
            "error": None,
            "tts_provider": None,
            "tts_task_id": None,
            "voice_profile": cast.get("voice_profile") or {},
            "tts_failures": [],
            "estimated_credits": plan.estimated_credits,
            "estimated_cost_usd": plan.estimated_cost_usd,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"\nRunning {plan.cast_id} | {plan.format_id} | {plan.clip_type}")
        try:
            reusable = None if args.force_video else find_reusable_clip(manifest, plan)
            if reusable:
                row.update(
                    {
                        "task_id": reusable.get("task_id"),
                        "result_url": reusable.get("result_url"),
                        "local_file": reusable.get("local_file"),
                        "status": "reused",
                        "reused_from_batch_id": reusable.get("batch_id"),
                        "tts_provider": reusable.get("tts_provider"),
                        "tts_task_id": reusable.get("tts_task_id"),
                        "voice_profile": reusable.get("voice_profile") or row["voice_profile"],
                        "estimated_credits": 0,
                        "estimated_cost_usd": 0,
                    }
                )
                print(f"Reused local clip: {row['local_file']}")
                success_count += 1
                manifest.setdefault("clips", []).append(row)
                save_manifest(manifest)
                continue

            if plan.clip_type == "talking_head":
                result_url, task_id, tts = run_talking_head(api_key, plan, cast, args.tts_provider, manifest, args.force_tts)
                row["tts_provider"] = tts["provider"]
                row["tts_task_id"] = tts["task_id"]
                row["voice_profile"] = tts["voice_profile"]
                row["tts_failures"] = tts["failures"]
                row["tts_reused"] = tts.get("reused", False)
                row["tts_duration_seconds"] = tts.get("duration_seconds")
            else:
                result_url, task_id = run_broll(api_key, plan, cast)
            row["task_id"] = task_id
            row["result_url"] = result_url
            download_file(result_url, output_path)
            row["media_validation"] = validate_clip_file(output_path, plan, tts if plan.clip_type == "talking_head" else None)
            row["status"] = "success"
            success_count += 1
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = str(exc)
            task_match = re.search(r"task ([a-zA-Z0-9]+)", str(exc))
            if task_match:
                row["task_id"] = task_match.group(1)
            failure_count += 1
            print(f"FAILED: {exc}")
        manifest.setdefault("clips", []).append(row)
        save_manifest(manifest)

    end_credits = check_credit_balance(api_key)
    summary = {
        "batch_id": batch_id,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "niches": niche_ids,
        "formats": format_ids,
        "mode": args.mode,
        "video_provider": args.video_provider,
        "include_broll": args.include_broll,
        "cast_count": args.cast_count,
        "clips_planned": len(clip_plans),
        "clips_succeeded": success_count,
        "clips_failed": failure_count,
        "start_credits": start_credits,
        "end_credits": end_credits,
        "credits_spent": (start_credits - end_credits) if start_credits is not None and end_credits is not None else None,
        "estimated": planned_costs,
    }
    manifest.setdefault("batches", []).append(summary)
    save_manifest(manifest)
    BATCH_SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    build_review_html(manifest)

    print(f"\nBatch complete: {success_count} succeeded, {failure_count} failed")
    if summary["credits_spent"] is not None:
        print(f"Approx credits spent: {summary['credits_spent']:.2f}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Batch summary: {BATCH_SUMMARY_PATH}")
    print(f"Review page: {REVIEW_PATH}")


def build_review_html(manifest: dict[str, Any] | None = None) -> None:
    manifest = manifest if manifest is not None else load_manifest()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    casts = manifest.get("casts", {})
    clips = manifest.get("clips", [])
    latest_batch = (manifest.get("batches") or [{}])[-1]
    estimated = latest_batch.get("estimated") or {}
    review_tools = """
      <section class="feedback-panel">
        <h2>Joel Feedback Export</h2>
        <p>Mark winners/rejects, add notes, then copy the JSON for Steven/Codex/Claude.</p>
        <button type="button" onclick="copyFeedback()">Copy Feedback JSON</button>
        <textarea id="feedback-output" readonly placeholder="Feedback JSON appears here after copying."></textarea>
      </section>
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for clip in clips:
        grouped.setdefault(clip.get("cast_id", "unknown"), []).append(clip)

    sections = []
    for cast_id, cast_clips in sorted(grouped.items()):
        cast = casts.get(cast_id, {})
        photos = cast.get("photos", [])
        photo_html = "".join(
            f'<figure><img src="{escape(photo.get("url", ""))}" alt="{escape(photo.get("kind", "cast photo"))}"><figcaption>{escape(photo.get("kind", ""))}</figcaption></figure>'
            for photo in photos
        )
        clip_cards = []
        for clip in cast_clips:
            local_file = clip.get("local_file")
            clip_id = f"{clip.get('cast_id', '')}_{clip.get('format_id', '')}_{clip.get('clip_type', '')}_{clip.get('batch_id', '')}"
            video_html = (
                f'<video controls preload="metadata" src="{escape(local_file)}"></video>'
                if clip.get("status") in {"success", "reused"} and local_file
                else f'<div class="missing">No playable local video. Status: {escape(str(clip.get("status")))}</div>'
            )
            questions = "".join(f"<li>{escape(question)}</li>" for question in REVIEW_QUESTIONS)
            clip_cards.append(
                f"""
                <article class="card">
                  <header>
                    <h3>{escape(clip.get("format_id", ""))} | {escape(clip.get("clip_type", ""))}</h3>
                    <div class="meta">{escape(clip.get("model", ""))}</div>
                  </header>
                  {video_html}
                  <section>
                    <h4>Prompt</h4>
                    <p>{escape(clip.get("prompt") or "")}</p>
                  </section>
                  {f'<section><h4>Script</h4><p>{escape(clip.get("script_text") or "")}</p></section>' if clip.get("script_text") else ""}
                  {f'<p class="meta">TTS: {escape(clip.get("tts_provider") or "")}</p>' if clip.get("tts_provider") else ""}
                  {f'<p class="meta">Voice: age {escape((clip.get("voice_profile") or {}).get("age_band", ""))}, ElevenLabs {escape((clip.get("voice_profile") or {}).get("elevenlabs_voice", ""))}, Gemini {escape((clip.get("voice_profile") or {}).get("gemini_voice_name", ""))}</p>' if clip.get("voice_profile") else ""}
                  <section>
                    <h4>Review Questions</h4>
                    <ol>{questions}</ol>
                  </section>
                  <section class="feedback" data-clip-id="{escape(clip_id)}" data-format="{escape(clip.get("format_id", ""))}" data-clip-type="{escape(clip.get("clip_type", ""))}">
                    <h4>Joel Decision</h4>
                    <label><input type="radio" name="{escape(clip_id)}_decision" value="winner"> Winner</label>
                    <label><input type="radio" name="{escape(clip_id)}_decision" value="maybe"> Maybe</label>
                    <label><input type="radio" name="{escape(clip_id)}_decision" value="reject"> Reject</label>
                    <label class="meta-check"><input type="checkbox" data-field="would_test_meta"> Would test in Meta</label>
                    <textarea data-field="notes" placeholder="Best hook, worst artifact, what would make it launchable"></textarea>
                  </section>
                  {f'<p class="error">{escape(clip.get("error") or "")}</p>' if clip.get("error") else ""}
                </article>
                """
            )
        sections.append(
            f"""
            <section class="cast-section">
              <div class="cast-header">
                <div>
                  <h2>{escape(cast_id)}</h2>
                  <p>{escape(cast.get("identity_description", ""))}</p>
                </div>
                <div class="photos">{photo_html}</div>
              </div>
              <div class="grid">{''.join(clip_cards)}</div>
            </section>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Video Fine-Tuning Harness Review</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #14213d;
      background: #f6f7f9;
    }}
    body {{ margin: 0; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 32px 18px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 44px); letter-spacing: 0; }}
    h2 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }}
    h3 {{ margin: 0 0 4px; font-size: 18px; letter-spacing: 0; }}
    h4 {{ margin: 16px 0 6px; font-size: 12px; text-transform: uppercase; color: #637083; letter-spacing: 0.04em; }}
    .summary, .meta, .cast-header p {{ color: #526070; }}
    .metrics {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 18px; }}
    .metric {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 10px 12px; min-width: 130px; }}
    .metric strong {{ display: block; font-size: 18px; }}
    .cast-section {{ margin-top: 28px; }}
    .cast-header {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(260px, 520px);
      gap: 18px;
      align-items: start;
      background: #fff;
      border: 1px solid #dde3ea;
      border-radius: 8px;
      padding: 16px;
    }}
    .photos {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: 10px; }}
    figure {{ margin: 0; }}
    figure img {{ width: 100%; aspect-ratio: 9 / 16; object-fit: cover; border-radius: 6px; background: #e5e7eb; }}
    figcaption {{ margin-top: 4px; font-size: 11px; color: #637083; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin-top: 18px; }}
    .card {{
      background: #fff;
      border: 1px solid #dde3ea;
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(20, 33, 61, 0.08);
    }}
    video {{ width: 100%; aspect-ratio: 9 / 16; max-height: 620px; background: #111827; border-radius: 6px; margin-top: 14px; }}
    p {{ line-height: 1.5; }}
    ol {{ padding-left: 20px; line-height: 1.55; }}
    label {{ display: inline-flex; align-items: center; gap: 6px; margin: 6px 10px 6px 0; font-size: 13px; color: #374151; }}
    textarea {{ width: 100%; min-height: 76px; margin-top: 8px; border: 1px solid #cfd7e2; border-radius: 6px; padding: 8px; font: inherit; box-sizing: border-box; }}
    button {{ border: 0; border-radius: 6px; background: #4f46e5; color: #fff; padding: 9px 12px; font-weight: 700; cursor: pointer; }}
    .feedback-panel {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; margin: 18px 0 24px; }}
    .feedback-panel textarea {{ min-height: 110px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .missing {{ margin-top: 14px; padding: 18px; border-radius: 6px; background: #fff2f0; color: #9f1d14; }}
    .error {{ color: #9f1d14; background: #fff2f0; padding: 10px; border-radius: 6px; }}
    @media (max-width: 760px) {{
      .cast-header {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
	  <main>
	    <h1>Video Fine-Tuning Harness Review</h1>
	    <p class="summary">{len(casts)} cast identities | {len(clips)} clips | generated {escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}</p>
	    <section class="metrics">
	      <div class="metric"><strong>{escape(str(latest_batch.get("mode", "n/a")))}</strong><span>Mode</span></div>
	      <div class="metric"><strong>{escape(str(latest_batch.get("clips_succeeded", "n/a")))}</strong><span>Succeeded</span></div>
	      <div class="metric"><strong>{escape(str(latest_batch.get("clips_failed", "n/a")))}</strong><span>Failed</span></div>
	      <div class="metric"><strong>{estimated.get("total_credits", 0):.0f}</strong><span>Estimated credits</span></div>
	      <div class="metric"><strong>${estimated.get("total_cost_usd", 0):.2f}</strong><span>Estimated cost</span></div>
	      <div class="metric"><strong>{escape(str(latest_batch.get("credits_spent", "n/a")))}</strong><span>Credits spent</span></div>
	    </section>
	    {review_tools}
	    {''.join(sections)}
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
          review_page: 'finetuning_output/review.html',
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
    print(f"Review page written: {REVIEW_PATH}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 0.5 kie.ai video fine-tuning harness.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned calls and cost estimate; make no API calls.")
    parser.add_argument("--yes", action="store_true", help="Actually run the harness.")
    parser.add_argument("--build-review", action="store_true", help="Regenerate review.html from manifest.json.")
    parser.add_argument(
        "--mode",
        choices=("draft", "contender", "final"),
        default="draft",
        help="Cost/speed profile. draft: 2 talking-head tests. contender: 4 talking-head tests. final: full talking-head + B-roll.",
    )
    parser.add_argument("--config", help="Optional JSON config with niches/formats overrides.")
    parser.add_argument("--niches", default="auto_insurance", help="Comma-separated niche IDs.")
    parser.add_argument("--formats", help="Comma-separated format IDs. Defaults are selected by --mode.")
    parser.add_argument("--cast-count", type=int, default=2, help="Number of cast identities per niche.")
    parser.add_argument("--task-timeout", type=int, default=TASK_TIMEOUT_SECONDS, help="Seconds to wait for each kie.ai task.")
    parser.add_argument("--max-planned-credits", type=float, default=DEFAULT_MAX_PLANNED_CREDITS, help="Fail before live generation if the planned batch exceeds this credit estimate.")
    parser.add_argument("--override-cost-cap", action="store_true", help="Allow live generation even when planned credits exceed --max-planned-credits.")
    parser.add_argument("--include-broll", action="store_true", help="Include B-roll clips. Defaults on for --mode final.")
    parser.add_argument("--force-video", action="store_true", help="Ignore reusable local video clips and generate again.")
    parser.add_argument("--force-tts", action="store_true", help="Ignore cached TTS assets and generate audio again.")
    parser.add_argument(
        "--video-provider",
        choices=("kling", "seedance"),
        default="kling",
        help="Video model family to use. Default keeps existing Kling behavior; seedance uses OmniHuman for lip-sync talking-heads and Seedance 2 Fast for B-roll.",
    )
    parser.add_argument(
        "--tts-provider",
        choices=("auto", "elevenlabs", "gemini"),
        default="auto",
        help="TTS provider mode. auto tries ElevenLabs first, then Gemini.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.mode == "final":
        args.include_broll = True
    selected = sum(bool(value) for value in (args.dry_run, args.yes, args.build_review))
    if selected != 1:
        print("Choose exactly one mode: --dry-run, --yes, or --build-review", file=sys.stderr)
        return 2
    if args.cast_count < 1:
        print("--cast-count must be at least 1", file=sys.stderr)
        return 2
    if args.task_timeout < POLL_INTERVAL_SECONDS:
        print(f"--task-timeout must be at least {POLL_INTERVAL_SECONDS}", file=sys.stderr)
        return 2

    global TASK_TIMEOUT_SECONDS
    TASK_TIMEOUT_SECONDS = args.task_timeout

    config = load_config(args.config)
    niche_ids = selected_ids(args.niches, config["niches"], "niches")
    format_ids = selected_ids(args.formats or MODE_FORMATS[args.mode], config["formats"], "formats")
    cast_plans = build_cast_plans(config, niche_ids, args.cast_count)
    clip_plans = filter_clip_plans(
        build_clip_plans(config, niche_ids, format_ids, cast_plans, args.video_provider),
        include_broll=args.include_broll,
    )

    if args.dry_run:
        print_dry_run(cast_plans, clip_plans, args.tts_provider, args.video_provider)
        return 0
    if args.build_review:
        build_review_html()
        return 0
    run_batch(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

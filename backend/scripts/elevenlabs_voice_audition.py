#!/usr/bin/env python3
"""
Generate a small direct-ElevenLabs voice audition set for video ads.

This bypasses Kie.ai's ElevenLabs wrapper and reads the API key from macOS
Keychain service `elevenlabs-api-key`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "finetuning_output" / "voice_auditions" / "elevenlabs_direct"
KEYCHAIN_SERVICE = "elevenlabs-api-key"
API_BASE = "https://api.elevenlabs.io/v1"
REQUEST_TIMEOUT_SECONDS = 60

DEFAULT_TEXT = (
    "Why pay more for the same kind of coverage? A quick comparison can show whether "
    "your current rate still makes sense. Compare free quotes."
)

DEFAULT_VOICES = [
    ("roger", "CwhRBWXzGAHq8TQ4Fs17", "Roger - Laid-Back, Casual, Resonant"),
    ("will", "bIHbv24MWmeRgasZH58o", "Will - Relaxed Optimist"),
    ("chris", "iP95p4xoKVk53GoZ742B", "Chris - Charming, Down-to-Earth"),
    ("eric", "cjVigY5qzO86Huf0OWal", "Eric - Smooth, Trustworthy"),
    ("liam", "TX3LPaxmHKxFdv7VOQHJ", "Liam - Energetic, Social Media Creator"),
]


def keychain_secret(service: str) -> str:
    user = subprocess.check_output(["whoami"], text=True).strip()
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-a", user, "-s", service, "-w"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Missing Keychain secret `{service}` for user `{user}`") from exc


def probe_duration(path: Path) -> float | None:
    try:
        raw = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
        ).strip()
        return round(float(raw), 2)
    except Exception:
        return None


def fetch_models(api_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{API_BASE}/models",
        headers={"xi-api-key": api_key},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else data.get("models", [])


def create_speech(api_key: str, voice_id: str, model_id: str, text: str, output_path: Path) -> None:
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.38,
            "similarity_boost": 0.78,
            "style": 0.35,
            "use_speaker_boost": True,
            "speed": 1.0,
        },
    }
    response = requests.post(
        f"{API_BASE}/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(f"ElevenLabs TTS failed for {voice_id}: {response.status_code} {response.text[:500]}")
    output_path.write_bytes(response.content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="eleven_v3", help="ElevenLabs model_id to use.")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Text to synthesize.")
    parser.add_argument("--limit", type=int, default=5, help="Number of default voices to audition.")
    parser.add_argument("--dry-run", action="store_true", help="Validate key/model/voice plan without generating audio.")
    args = parser.parse_args()

    api_key = keychain_secret(KEYCHAIN_SERVICE)
    models = fetch_models(api_key)
    tts_models = {model.get("model_id") for model in models if model.get("can_do_text_to_speech")}
    if args.model not in tts_models:
        raise SystemExit(f"Model `{args.model}` is not available for TTS. Available: {', '.join(sorted(tts_models))}")

    selected = DEFAULT_VOICES[: args.limit]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "elevenlabs_direct",
        "model_id": args.model,
        "text": args.text,
        "dry_run": args.dry_run,
        "voices": [],
    }

    for slug, voice_id, name in selected:
        output_path = OUTPUT_DIR / f"{slug}_{args.model}_mapped_why_pay_more.mp3"
        row = {"slug": slug, "voice_id": voice_id, "name": name, "file": str(output_path)}
        if args.dry_run:
            print(f"DRY RUN {slug}: {name} ({voice_id})")
        else:
            print(f"Generating {slug}: {name}", flush=True)
            create_speech(api_key, voice_id, args.model, args.text, output_path)
            row["duration_seconds"] = probe_duration(output_path)
            print(f"Saved {output_path} ({row['duration_seconds']}s)", flush=True)
        summary["voices"].append(row)

    summary_path = OUTPUT_DIR / "audition_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()

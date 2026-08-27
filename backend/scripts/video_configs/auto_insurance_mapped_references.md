# Auto Insurance Mapped Reference Config

This config turns Claude's clean Facebook Ad Library scrape into a reusable `video_finetuning_harness.py` override. It does not change the default harness modes.

## Source

- File: `backend/scripts/ad_library_references/auto_insurance_cheap_import_payload.json`
- Query: `auto insurance cheap`
- Country: US
- Sort: active ads, most impressions
- Clean set: 35 on-vertical ads
- Video-mapped set: 15 ads with exact Library ID to video mapping
- Dominant CTA: `Get Quote`

## Format IDs

- `mapped_young_driver_rate_check`
- `mapped_one_minute_quote`
- `mapped_why_pay_more`
- `mapped_renewal_shock_story`
- `mapped_full_coverage_check`
- `mapped_local_rate_review`

## Dry Run

```bash
python3 backend/scripts/video_finetuning_harness.py \
  --dry-run \
  --config backend/scripts/video_configs/auto_insurance_mapped_references.json \
  --formats mapped_young_driver_rate_check,mapped_one_minute_quote,mapped_why_pay_more,mapped_renewal_shock_story,mapped_full_coverage_check,mapped_local_rate_review \
  --cast-count 1 \
  --tts-provider gemini
```

## Paid Draft Run

Only run this after Steven explicitly approves spend.

```bash
python3 backend/scripts/video_finetuning_harness.py \
  --yes \
  --mode draft \
  --config backend/scripts/video_configs/auto_insurance_mapped_references.json \
  --formats mapped_one_minute_quote,mapped_why_pay_more \
  --cast-count 1 \
  --tts-provider gemini
```

## Creative Guardrails

- Do not copy competitor wording exactly.
- Do not promise fixed savings or guaranteed rates.
- Do not ask Kie to generate readable text in the video.
- Keep phone screens angled away, dark, or blurred.
- Keep US car interiors left-hand-drive.
- Prefer tight chest-up or interior-only framing.
- Avoid visible exterior car doors, side panels, badges, decals, stickers, license plates, and signage; Kie can hallucinate fake text on those surfaces even when the seed image is clean.
- Add CTA/offer text later through overlays, not generated video pixels.

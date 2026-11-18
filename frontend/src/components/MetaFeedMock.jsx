import React, { useState } from 'react';

// How one ad reads in the Facebook feed, for the launcher's per-ad drawer (2026-11-17). It updates as
// the copy fields below it change. Pattern from AdStellar's ad editor; ours also shows the paired
// Stories/Reels file so a wrong 9:16 pairing is visible before launch. Approximate on purpose.
export default function MetaFeedMock({ pageName, body, headline, description, cta, domain, creative }) {
    const isVideo = creative?.mediaType === 'video';
    const feedSrc = isVideo ? (creative?.videoUrl || creative?.previewUrl) : creative?.previewUrl;
    const storiesSrc = creative?.secondaryImageUrl || creative?.secondaryVideoUrl;
    const storiesIsVideo = !creative?.secondaryImageUrl && Boolean(creative?.secondaryVideoUrl);
    const [expanded, setExpanded] = useState(false);
    // Meta cuts primary text at about 125 characters with "See more", so the hook has to land before that.
    const truncated = body && body.length > 125 && !expanded;
    return (
        <section aria-label="Feed preview" className="space-y-2">
            <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
                <div className="flex items-center gap-2 px-3 py-2">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-200 text-xs font-semibold text-gray-500">
                        {(pageName || '?').trim().charAt(0).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                        <div className={`truncate text-sm ${pageName ? 'font-semibold text-gray-900' : 'italic text-gray-400'}`}>{pageName || 'Page not confirmed'}</div>
                        <div className="text-[11px] text-gray-500">Sponsored</div>
                    </div>
                </div>
                <p className={`whitespace-pre-line px-3 pb-2 text-sm ${body ? 'text-gray-800' : 'italic text-amber-700'}`}>
                    {!body ? 'No primary text' : truncated ? `${body.slice(0, 125).trimEnd()}… ` : body}
                    {truncated && <button type="button" onClick={() => setExpanded(true)} className="font-semibold text-gray-500 hover:underline">See more</button>}
                </p>
                <div className="flex max-h-[220px] items-center justify-center overflow-hidden bg-gray-100">
                    {feedSrc && (isVideo
                        ? <video src={feedSrc} aria-label="Feed video preview" className="max-h-[220px] w-full object-contain" muted playsInline controls />
                        : <img src={feedSrc} alt="Feed creative preview" className="max-h-[220px] w-full object-contain" />)}
                </div>
                <div className="flex items-center justify-between gap-2 border-t border-gray-200 bg-gray-50 px-3 py-2">
                    <div className="min-w-0">
                        {domain && <div className="truncate text-[11px] text-gray-400">{domain}</div>}
                        <div className={`truncate text-sm font-semibold ${headline ? 'text-gray-900' : 'italic text-amber-700'}`}>{headline || 'No headline'}</div>
                        {description && <div className="truncate text-[11px] text-gray-500">{description}</div>}
                    </div>
                    <span className={`shrink-0 rounded px-3 py-1.5 text-xs font-medium ${cta ? 'bg-gray-200 text-gray-700' : 'bg-amber-50 italic text-amber-700'}`}>{cta || 'No CTA'}</span>
                </div>
            </div>
            {storiesSrc && (
                <div className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-2">
                    <a href={storiesIsVideo ? undefined : storiesSrc} target="_blank" rel="noreferrer" title="Open the 9:16 file full size" className="aspect-[9/16] w-24 shrink-0 overflow-hidden rounded bg-black">
                        {storiesIsVideo
                            ? <video src={storiesSrc} aria-label="Stories 9:16 video preview" className="h-full w-full object-contain" muted playsInline controls />
                            : <img src={storiesSrc} alt="Stories 9:16 preview" className="h-full w-full object-contain" />}
                    </a>
                    <p className="text-xs text-gray-600">Stories and Reels use this 9:16 file.</p>
                </div>
            )}
            <p className="text-center text-[11px] text-gray-400">Not identical to Meta. Review in Ads Manager before turning ads on.</p>
        </section>
    );
}

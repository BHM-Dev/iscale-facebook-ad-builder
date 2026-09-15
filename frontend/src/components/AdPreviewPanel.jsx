import React from 'react';
import { Image as ImageIcon, MoreHorizontal, ThumbsUp, MessageCircle, Share2 } from 'lucide-react';

function getStyleImage(style) {
  return style?.thumbnail_url || style?.image_url || style?.preview_url || style?.imageUrl || '';
}

export default function AdPreviewPanel({
  headline,
  body,
  cta,
  style,
  overlayEnabled,
  overlayNicheLine,
  overlayOfferLine,
}) {
  const imageUrl = getStyleImage(style);
  const styleName = style?.name || style?.template_category || '';
  const overlayHeadline = overlayNicheLine?.trim() || headline?.trim();

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden" aria-label="Live creative preview">
      <div className="border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-900">Live creative preview</h2>
        <p className="mt-0.5 text-xs text-gray-500">Updates as you build</p>
      </div>

      <div className="p-4">
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-3">
            <div className="h-9 w-9 rounded-full bg-gray-200" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-gray-900">Your Brand</p>
              <p className="text-xs text-gray-500">Sponsored</p>
            </div>
            <MoreHorizontal size={18} className="text-gray-500" aria-hidden="true" />
          </div>

          <div className="relative aspect-square overflow-hidden bg-gray-100">
            {imageUrl ? (
              <img src={imageUrl} alt={styleName ? `${styleName} preview` : 'Selected creative style preview'} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-gray-400">
                <ImageIcon size={30} />
                <p className="text-sm font-medium">{styleName || 'Preview updates as you build'}</p>
                {!styleName && <p className="text-xs">Select a style to see it here.</p>}
              </div>
            )}
            {overlayEnabled && (overlayHeadline || overlayOfferLine?.trim()) && (
              <div className="absolute inset-x-0 bottom-0 bg-black/65 px-4 py-3 text-white">
                {overlayHeadline && <p className="text-lg font-bold leading-tight">{overlayHeadline}</p>}
                {overlayOfferLine?.trim() && <p className="mt-1 text-xs font-medium">{overlayOfferLine}</p>}
              </div>
            )}
          </div>

          <div className="px-3 py-3">
            <p className="text-xs text-gray-500">Your Brand</p>
            <p className="mt-1 text-sm font-semibold leading-snug text-gray-900">{headline?.trim() || 'Your headline will appear here'}</p>
            <p className="mt-1 text-sm leading-relaxed text-gray-600">{body?.trim() || 'Your body copy will appear here as you write.'}</p>
            <button type="button" className="mt-3 w-full rounded-md bg-gray-100 px-3 py-2 text-sm font-semibold text-gray-800">
              {cta?.trim() || 'GET MY QUOTE'}
            </button>
          </div>

          <div className="flex items-center justify-between border-t border-gray-100 px-3 py-2 text-xs text-gray-400">
            <span className="flex items-center gap-1"><ThumbsUp size={13} /> Like</span>
            <span className="flex items-center gap-1"><MessageCircle size={13} /> Comment</span>
            <span className="flex items-center gap-1"><Share2 size={13} /> Share</span>
          </div>
        </div>
        <p className="mt-3 text-center text-xs leading-relaxed text-gray-500">Not identical to Meta. Review in Ads Manager before turning ads on.</p>
      </div>
    </section>
  );
}

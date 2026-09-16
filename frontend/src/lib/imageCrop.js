import { authFetch } from './authClient';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

// Caps how many crop requests are ever in flight at once. The backend
// threadpools its own blocking work (network fetch + Pillow), but a 50-image
// Drive bulk-add firing 50 requests simultaneously would still queue up that
// many threadpool jobs at once on a single-worker backend — this client-side
// queue is the other half of that fix, spacing bulk triggers out instead of
// firing them all in the same tick.
const MAX_CONCURRENT_CROPS = 4;
let activeCrops = 0;
const cropQueue = [];

function runNextQueued() {
    if (activeCrops >= MAX_CONCURRENT_CROPS || cropQueue.length === 0) return;
    activeCrops += 1;
    const { task, resolve, reject } = cropQueue.shift();
    task().then(resolve, reject).finally(() => {
        activeCrops -= 1;
        runNextQueued();
    });
}

function enqueueCrop(task) {
    return new Promise((resolve, reject) => {
        cropQueue.push({ task, resolve, reject });
        runNextQueued();
    });
}

// Crops (never stretches) an image to Feed (1:1) or Stories (9:16) server-side
// — see backend/app/services/image_crop_service.py. Always returns a real
// hosted URL (uploaded to R2/local same as any other upload), never a client
// object URL, so the result can be treated exactly like any other creative
// image from here on.
//
// Fetching source_url happens on the BACKEND, not via a client-side canvas —
// a canvas read-back would silently fail (a "tainted canvas" security error)
// unless the source host sets CORS headers permissive enough for pixel
// access, which isn't guaranteed for Drive-synced R2 assets. Server-to-server
// fetch (the same pattern facebook_service.py already uses to download a
// remote image before uploading it to Meta) has no such restriction.
export async function cropImageToAspect({ file, sourceUrl, targetRatio, anchor = 'center' }) {
    if (!file && !sourceUrl) {
        throw new Error('cropImageToAspect requires either a file or a sourceUrl');
    }
    return enqueueCrop(async () => {
        const formData = new FormData();
        formData.append('target_ratio', targetRatio);
        formData.append('anchor', anchor);
        if (file) {
            formData.append('file', file, file.name || 'upload.jpg');
        } else {
            formData.append('source_url', sourceUrl);
        }

        const response = await authFetch(`${API_URL}/uploads/crop-to-aspect`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || 'Failed to crop image');
        }
        return response.json(); // { url, media_type, crop_axis }
    });
}

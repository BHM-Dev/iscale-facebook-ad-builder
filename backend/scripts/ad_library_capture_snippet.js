/*
Paste this into Chrome DevTools Console while viewing Facebook Ad Library.
It downloads a JSON capture that can be pasted into Research > Import Intel.

Required page setup:
- Country: United States
- Status: Active ads
- Sort: Most impressions
- Query: "cheap auto insurance" or "auto insurance"
*/
(() => {
  const markers = Array.from(document.querySelectorAll("*")).filter(element => {
    const text = element.textContent && element.textContent.trim();
    return text && text.startsWith("Library ID:") && element.children.length < 3 && text.length < 60;
  });

  const cardRoots = new Set();
  for (const marker of markers) {
    let node = marker;
    for (let index = 0; index < 4 && node.parentElement; index += 1) {
      node = node.parentElement;
    }
    cardRoots.add(node);
  }

  const seen = new Set();
  const ads = [];
  const cardEntries = []; // { root, libraryId } — reused below to map videos to their owning ad
  for (const root of cardRoots) {
    const lines = root.innerText
      .split("\n")
      .map(line => line.trim())
      .filter(Boolean);
    const idLine = lines.find(line => line.startsWith("Library ID:"));
    if (!idLine) continue;
    const libraryId = idLine.replace("Library ID:", "").trim().split(/\s+/)[0];
    if (!libraryId || seen.has(libraryId)) continue;
    seen.add(libraryId);

    const startedLine = lines.find(line => /^Started running on /i.test(line));
    const started = startedLine ? startedLine.replace(/^Started running on /i, "").trim() : "";
    const sponsoredIndex = lines.findIndex(line => line === "Sponsored");
    const page = sponsoredIndex > 0 ? lines[sponsoredIndex - 1] : "";
    const multipleVersions = lines.some(line => /this ad has multiple versions/i.test(line));
    const ctaLabels = ["Get Quote", "Get quote", "Get offer", "Call Now", "Call now", "Sign Up", "Contact Us", "Learn More", "Shop Now", "Send Message"];
    const ctaIndex = lines.findIndex(line => ctaLabels.includes(line));
    const cta = ctaIndex >= 0 ? lines[ctaIndex] : "";
    const bodyStart = sponsoredIndex >= 0 ? sponsoredIndex + 1 : 0;
    const bodyEnd = ctaIndex >= 0 ? ctaIndex : lines.length;
    const body = lines.slice(bodyStart, bodyEnd).join(" ").slice(0, 5000);
    const domain = lines.find(line => /^[A-Z0-9.-]+\.[A-Z]{2,}(\/[A-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?$/i.test(line)) || "";

    // Videos physically inside this card's own DOM subtree — a reliable per-ad
    // mapping, unlike the old page-wide innerText regex, which missed real
    // video ads whose card text didn't contain "Video player"/"Play video".
    const cardVideoEls = Array.from(root.querySelectorAll("video"));
    const cardVideoUrls = cardVideoEls.map(video => video.currentSrc || video.src || "").filter(Boolean);
    const cardPoster = cardVideoEls.map(video => video.poster).find(Boolean) || "";

    ads.push({
      library_id: libraryId,
      page,
      body_preview: body,
      cta,
      domain,
      started_running: started,
      multiple_versions: multipleVersions,
      rank_position: ads.length + 1,
      media_type: cardVideoUrls.length ? "video" : "image",
      video_urls: cardVideoUrls,
      thumbnail_url: cardPoster,
    });
    cardEntries.push({ root, libraryId });
  }

  // Flat video inventory, each tagged with the library_id of its containing
  // card (or null if it isn't inside any detected card) — kept for the
  // capture-quality "unmapped video" stat downstream.
  const videos = Array.from(document.querySelectorAll("video")).map((video, index) => {
    const owner = cardEntries.find(entry => entry.root.contains(video));
    return {
      index,
      url: video.currentSrc || video.src || "",
      poster: video.poster || "",
      width: video.videoWidth || null,
      height: video.videoHeight || null,
      ad_library_id: owner ? owner.libraryId : null,
    };
  }).filter(video => video.url || video.poster);

  const payload = {
    captured_at: new Date().toISOString(),
    page_url: location.href,
    query: new URLSearchParams(location.search).get("q") || "",
    country: new URLSearchParams(location.search).get("country") || "US",
    sort_mode: "total_impressions_desc",
    visible_ads: ads,
    videos,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `ad-library-capture-${Date.now()}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  const mappedVideoCount = videos.filter(video => video.ad_library_id).length;
  console.log(`Captured ${ads.length} unique ad cards and ${videos.length} video elements (${mappedVideoCount} mapped to a specific ad). Paste the downloaded JSON into Ad Builder > Research > Import Intel.`);
})();

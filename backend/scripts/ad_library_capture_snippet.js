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
  const text = document.body.innerText || "";
  const cardChunks = text
    .split(/Library ID:\s*/g)
    .slice(1)
    .map(chunk => `Library ID: ${chunk}`);

  const getLineAfter = (lines, label) => {
    const index = lines.findIndex(line => line.trim().toLowerCase() === label.toLowerCase());
    return index >= 0 ? (lines[index + 1] || "").trim() : "";
  };

  const getDomain = lines => (
    lines.find(line => /^[A-Z0-9.-]+\.[A-Z]{2,}(\/[A-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?$/i.test(line.trim())) || ""
  ).trim();

  const ads = cardChunks.map((chunk, index) => {
    const lines = chunk
      .split("\n")
      .map(line => line.trim())
      .filter(Boolean);
    const libraryId = (lines[0] || "").replace("Library ID:", "").trim().split(/\s+/)[0];
    const startedLine = lines.find(line => /^Started running on /i.test(line));
    const started = startedLine ? startedLine.replace(/^Started running on /i, "").trim() : "";
    const multipleVersions = /This ad has multiple versions/i.test(chunk);
    const cta = ["Get Quote", "Get quote", "Get offer", "Call Now", "Sign Up", "Contact Us", "Learn More"]
      .find(label => lines.includes(label)) || "";
    const domain = getDomain(lines);
    const page = getLineAfter(lines, "Page ID") || lines.find(line => !/^Library ID:/.test(line) && !/^Started running/.test(line)) || "";
    return {
      library_id: libraryId,
      page,
      body_preview: lines.slice(1, 40).join(" ").slice(0, 5000),
      cta,
      domain,
      started_running: started,
      multiple_versions: multipleVersions,
      rank_position: index + 1,
      media_type: /Video player|Play video/i.test(chunk) ? "video" : "image",
    };
  }).filter(ad => ad.library_id);

  const videos = Array.from(document.querySelectorAll("video")).map((video, index) => ({
    index,
    url: video.currentSrc || video.src || "",
    poster: video.poster || "",
    width: video.videoWidth || null,
    height: video.videoHeight || null,
  })).filter(video => video.url || video.poster);

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
  console.log(`Captured ${ads.length} visible ads and ${videos.length} video elements. Paste the downloaded JSON into Ad Builder > Research > Import Intel.`);
})();

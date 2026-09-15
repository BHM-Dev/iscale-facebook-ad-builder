# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

# Build-time API URL: use /api/v1 so nginx proxies to backend (same origin)
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=$VITE_API_URL

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Cache-buster: forces every layer below to invalidate on every deploy,
# regardless of any content-hash caching quirk that let a stale build survive
# a "successful" deploy on 2026-08-09 (frontend served identical bytes across
# two separate deploys of different commits). Passed as a build arg from
# docker-compose.prod.yml, which reads it from the GIT_COMMIT env var the
# deploy script already exports. Value changing on every commit is the whole
# point — a RUN step referencing it can never be served from a prior layer.
ARG CACHE_BUST=unknown
RUN echo "Building commit ${CACHE_BUST}"

COPY frontend/ .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# SPA fallback: serve index.html for client-side routes.
#
# index.html gets explicit no-cache headers — without this, browsers can keep
# serving an old cached copy of the page shell after a deploy, which still
# references JS/CSS asset filenames from that old build. Since Vite hashes
# every asset filename by content, a new deploy DELETES the old hashed files
# outright (this Docker stage is a fresh `nginx:alpine` copying only the
# current build's dist/ — nothing carries over) rather than leaving them
# around, so a stale index.html means the browser requests a JS file that no
# longer exists at all. nginx's SPA fallback (`try_files ... /index.html`)
# then serves index.html's bytes back with a 200 and a `text/html` body in
# place of the missing JS/CSS file, which is a same-origin response that the
# browser can't tell apart from a real file at that URL until it actually
# tries to parse/execute it as a JS module and fails — silently, with no
# console error surfacing on some builds, and a blank white page with a
# working HTTP 200 on every network request. Reproduced live 2026-09-15: a
# push landed, the user still saw pre-fix behavior after logging out and back
# in (an app-level action that does nothing to browser HTTP caching), and a
# manual hard-reload was needed to recover — this must not require that.
# The hashed asset files themselves (/assets/*) are safe to cache
# aggressively — a content change always produces a new filename, so a stale
# cached copy of one of those is simply never requested again.
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    index index.html; \
    location = /index.html { \
        add_header Cache-Control "no-cache, no-store, must-revalidate"; \
        add_header Pragma "no-cache"; \
        expires 0; \
    } \
    location /assets/ { \
        add_header Cache-Control "public, max-age=31536000, immutable"; \
    } \
    location / { \
        add_header Cache-Control "no-cache, no-store, must-revalidate"; \
        try_files $uri $uri/ /index.html; \
    } \
    location /uploads { \
        proxy_pass http://backend:8000; \
        proxy_http_version 1.1; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; \
        proxy_set_header X-Forwarded-Proto $scheme; \
    } \
    location /api { \
        proxy_pass http://backend:8000; \
        proxy_http_version 1.1; \
        proxy_set_header Host $host; \
        proxy_set_header X-Real-IP $remote_addr; \
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; \
        proxy_set_header X-Forwarded-Proto $scheme; \
    } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

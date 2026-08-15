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

# SPA fallback: serve index.html for client-side routes
RUN echo 'server { \
    listen 80; \
    root /usr/share/nginx/html; \
    index index.html; \
    location / { \
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

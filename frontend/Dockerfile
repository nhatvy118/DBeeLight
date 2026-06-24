# Multi-stage build for Vite SPA → static assets served by nginx.
#
# Build:
#   docker build -t dbeelight-frontend ./frontend
# With API URL baked in (when not using nginx proxy on same origin):
#   docker build --build-arg VITE_API_URL=https://api.example.com -t dbeelight-frontend ./frontend

# ============ Builder ============
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Empty default = same-origin (nginx proxies /api → backend).
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ============ Runtime ============
FROM nginx:1.27-alpine AS runtime

# Remove the default site so our config takes over.
RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1

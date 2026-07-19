# syntax=docker/dockerfile:1.7
#
# Frontend: Vue SPA built with Vite, served by nginx.
#
# This nginx serves static files only. TLS termination, Let's Encrypt, and the
# /api + /internal reverse proxying all live on the host nginx that Ansible
# configures — this container never needs to know the backend exists.

FROM node:22-alpine AS builder

WORKDIR /app

# npm ci needs a lockfile; fall back so a fresh checkout still builds.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/spa.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

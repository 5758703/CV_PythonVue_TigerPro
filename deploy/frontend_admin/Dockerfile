# 构建上下文：仓库根目录
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_PORTAL_URL=/
ARG VITE_BASE=/console/
COPY frontend/frontend_admin/package.json frontend/frontend_admin/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/frontend_admin/ ./
ENV VITE_PORTAL_URL=$VITE_PORTAL_URL \
    VITE_BASE=$VITE_BASE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/frontend_admin/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

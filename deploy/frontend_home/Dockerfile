# 构建上下文：仓库根目录
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_ADMIN_URL=/console/
COPY frontend/frontend_home/package.json frontend/frontend_home/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/frontend_home/ ./
ENV VITE_ADMIN_URL=$VITE_ADMIN_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/frontend_home/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

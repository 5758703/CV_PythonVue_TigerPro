# Build one of the two Vite frontends and serve it read-only.
#   frontend_admin  -> VITE_BASE=/console/ default port 5173
#   frontend_home   -> default port 5174
# The app name is chosen at build time (compose passes it as FRONTEND_APP),
# so both services share this single Dockerfile.
FROM node:20-alpine AS build
ARG FRONTEND_APP=frontend_admin
WORKDIR /build
# Copy just this app so the two builds do not drag in each other's lockfiles.
COPY frontend/$FRONTEND_APP/ ./
RUN npm install --no-audit --no-fund && npm run build

FROM node:20-alpine
ARG FRONTEND_APP=frontend_admin
WORKDIR /app
COPY --from=build /build/dist ./dist
# vite preview serves the built bundle; the port is fixed per app and the
# SPA base path is configurable via VITE_BASE at build time.
EXPOSE 5173 5174
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]

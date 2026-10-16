# Mimir frontend production image (multi-stage). Build context: ./frontend.

# Stage 1: build the static Vite bundle. This node stage is discarded and never
# ships in the final image.
FROM node:22-alpine AS build
WORKDIR /app
# Install deps first for layer caching; npm ci for reproducible installs.
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve the static build with nginx. Only the compiled assets and the
# nginx config are copied in -- no node, no source, no node_modules.
FROM nginx:1.30-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

# ============================================================================
# FILE: nginx/Dockerfile
# PURPOSE: Build a custom nginx image with configuration baked in.
#          SSL certificates are mounted at runtime (not baked in).
# ARCHITECTURE REF: §6 — Nginx Configuration
# DEPENDENCIES: nginx:1.27-alpine base image
# ============================================================================

FROM nginx:1.27-alpine

# Install curl for the Docker HEALTHCHECK
# Using --no-cache to avoid creating a cache layer (keeps image small)
RUN apk add --no-cache curl

# Copy the nginx configuration into the image
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Copy the frontend chat UI into the image
RUN mkdir -p /usr/share/nginx/html/static
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/styles.css /usr/share/nginx/html/static/styles.css
COPY frontend/app.js     /usr/share/nginx/html/static/app.js

# Create the directory for SSL certificates (mounted at runtime via volume)
RUN mkdir -p /etc/nginx/ssl

# Expose both HTTP (for redirect to HTTPS) and HTTPS
EXPOSE 80 443

# Health check verifies nginx process is running and config is valid
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD nginx -t && curl -sf http://localhost/health || exit 1

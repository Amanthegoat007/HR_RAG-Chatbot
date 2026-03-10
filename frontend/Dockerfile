# Stage 1: Build the React application
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies and build
COPY package*.json ./
RUN npm config set fetch-retry-maxtimeout 1200000 && \
    npm config set fetch-retry-mintimeout 100000 && \
    npm config set fetch-timeout 3000000 && \
    npm ci

COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Copy Nginx config
COPY nginx.conf /etc/nginx/nginx.conf

# Expose port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

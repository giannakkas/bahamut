FROM node:20-slim

WORKDIR /app

# Copy from admin-panel subdirectory (build context is repo root)
COPY admin-panel/package.json admin-panel/package-lock.json* ./
RUN npm ci

COPY admin-panel/ .

# Build-time env vars (baked into client JS)
ARG NEXT_PUBLIC_API_URL=https://your-api-domain.railway.app
ARG NEXT_PUBLIC_MOCK_MODE=false
ARG NEXT_PUBLIC_REFRESH_INTERVAL=5000

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_MOCK_MODE=$NEXT_PUBLIC_MOCK_MODE
ENV NEXT_PUBLIC_REFRESH_INTERVAL=$NEXT_PUBLIC_REFRESH_INTERVAL

RUN npm run build

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

EXPOSE 3000

CMD ["npm", "start"]

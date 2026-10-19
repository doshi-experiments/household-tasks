FROM node:24-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/vendor ./vendor
RUN npm ci
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY tests ./tests
COPY --from=frontend /build/dist ./frontend/dist
RUN useradd --uid 1000 --create-home tasks && mkdir -p /data && chown tasks /data
USER tasks
VOLUME ["/data"]
EXPOSE 8040
CMD ["uvicorn", "app.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8040"]

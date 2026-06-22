FROM python:3.13-alpine

ARG BUILD_VERSION=dev
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

WORKDIR /app

COPY requirements.txt ./
RUN apk add --no-cache git \
    && pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY static ./static

RUN chmod 0755 /app/git_askpass.py

ENV PYTHONUNBUFFERED=1 \
    PORT=8099 \
    PACKAGES_PATH=/homeassistant/packages \
    DATA_PATH=/data

EXPOSE 8099

CMD ["python", "app.py"]

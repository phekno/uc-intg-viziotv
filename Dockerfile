FROM python:3.13-slim-bookworm AS base

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip setuptools && \
    pip3 install --no-cache-dir -r requirements.txt

COPY intg-viziotv/ intg-viziotv/
COPY driver.json .

ENV UC_DISABLE_MDNS_PUBLISH="false"
ENV UC_INTEGRATION_INTERFACE="0.0.0.0"
ENV UC_INTEGRATION_HTTP_PORT="9090"
ENV UC_CONFIG_HOME="/config"

VOLUME /config

EXPOSE 9090

LABEL org.opencontainers.image.source=https://github.com/phekno/uc-intg-viziotv
LABEL org.opencontainers.image.description="Vizio TV integration for Unfolded Circle Remote Two/3"

CMD ["python3", "-u", "intg-viziotv/driver.py"]

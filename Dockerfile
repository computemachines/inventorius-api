
FROM python:3.13-slim AS dependencies

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install gunicorn


FROM python:3.13-slim AS runtime

WORKDIR /app

# Wand needs the ImageMagick shared library at runtime, not its headers or
# compilation toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagickwand-7.q16-10 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=dependencies /install /usr/local

# copy source
COPY src /app/src

# Build ID for tracking deployments (passed at build time)
ARG BUILD_ID=dev
ENV BUILD_ID=${BUILD_ID}

# env for module discovery
ENV PYTHONPATH=/app/src

# gunicorn will import inventorius:app
EXPOSE 8000
CMD ["gunicorn","-w","2","-k","gthread","-t","60","-b","0.0.0.0:8000","--access-logfile","-","inventorius:app"]

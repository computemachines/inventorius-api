
FROM python:3.13-slim

WORKDIR /app

# system deps for Wand/ImageMagick if used at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagickwand-7.q16-10 libmagickwand-7.q16-dev \
  && rm -rf /var/lib/apt/lists/*

# copy and install python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir gunicorn

# copy source
COPY src /app/src

# env for module discovery
ENV PYTHONPATH=/app/src

# gunicorn will import inventorius:app
EXPOSE 8000
CMD ["gunicorn","-w","4","-k","gthread","-t","60","-b","0.0.0.0:8000","--access-logfile","-","inventorius:app"]
#CMD ["gunicorn", "-w", "4", "-k", "gthread", "-t", "60", "-b", "0.0.0.0:8000", "inventorius:app"]

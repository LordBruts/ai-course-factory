# GymRamp course-media worker.
#
# Built FROM the YT autopilot worker image on purpose: that image already holds
# ffmpeg, the Montserrat fonts, fastapi/uvicorn/httpx and edge-tts 7.2.8. Its
# apt layer costs 40+ minutes to rebuild from this machine's Debian mirror, so
# reusing it turns this build into a single fast pip layer.
#
# Prerequisite: the base image must exist locally --
#   (cd ../../yt-cross-domain-autopilot/worker && docker compose build)
FROM worker-yt-media-worker:latest

WORKDIR /course
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY tests/ ./tests/

ENV JOBS_ROOT=/data/course-jobs \
    PYTHONUNBUFFERED=1

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]

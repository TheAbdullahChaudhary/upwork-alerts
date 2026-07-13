FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app
COPY monitor.py .

RUN pip install --no-cache-dir playwright && \
    playwright install chromium

VOLUME ["/data"]
CMD ["python", "-u", "monitor.py"]

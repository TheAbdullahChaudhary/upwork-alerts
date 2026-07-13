FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app
COPY app.py .

RUN pip install --no-cache-dir flask playwright && \
    playwright install chromium

VOLUME ["/data"]
EXPOSE 5000
CMD ["python", "-u", "app.py"]

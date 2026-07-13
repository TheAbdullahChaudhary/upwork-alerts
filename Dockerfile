FROM python:3.11-slim

WORKDIR /app
COPY app.py .

RUN pip install --no-cache-dir flask requests

VOLUME ["/data"]
EXPOSE 5000
CMD ["python", "-u", "app.py"]

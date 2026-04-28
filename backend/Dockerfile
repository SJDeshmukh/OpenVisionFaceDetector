FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1
ENV OPENCV_NUM_THREADS=1
ENV KMP_DUPLICATE_LIB_OK=TRUE
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 gcc g++ git curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend /app/backend
WORKDIR /app/backend
EXPOSE 5001
ENV PORT=5001
CMD ["gunicorn", "--worker-class", "gthread", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5001", "app:app"]

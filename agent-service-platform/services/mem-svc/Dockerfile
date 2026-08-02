FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH=/app/shared:/app

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    pydantic==2.9.2 \
    pydantic-settings==2.5.2 \
    sqlalchemy==2.0.35 \
    aiomysql==0.2.0 \
    redis==5.0.8 \
    cryptography==43.0.1 \
    python-multipart==0.0.12

COPY shared /app/shared

COPY mem-svc /app/

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]

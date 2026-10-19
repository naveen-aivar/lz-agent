# AgentCore Runtime requires linux/arm64. Build from the repo root:
#   docker buildx build --platform linux/arm64 -f agent/Dockerfile -t <ecr-uri>:<tag> --push .
FROM --platform=linux/arm64 python:3.12-slim
WORKDIR /app
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/*.py ./
COPY lzcore ./lzcore
RUN useradd -m agent && chown -R agent /app
USER agent
EXPOSE 8080
CMD ["python", "app.py"]

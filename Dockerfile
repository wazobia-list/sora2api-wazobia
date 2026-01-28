FROM python:3.11-slim

# Set timezone to Asia/Shanghai (UTC+8) by default
# Can be overridden with -e TZ=<timezone> when running container
ENV TZ=Asia/Shanghai \
    TIMEZONE_OFFSET=8
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]

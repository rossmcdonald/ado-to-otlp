from python:3-slim

run apt-get update && \
    apt-get upgrade -y

run mkdir -p /app
workdir /app

copy ./requirements.txt ./
run pip install -r requirements.txt

copy ./main.py ./

cmd ["./main.py"]
entrypoint ["./main.py"]
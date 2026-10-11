FROM ubuntu:24.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jdk-headless g++ make libboost-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/src server/src
COPY client client
RUN mkdir -p server/target/classes && find server/src/main/java -name '*.java' > /tmp/sources && javac --release 17 -d server/target/classes @/tmp/sources && make -C client

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless python3 ca-certificates && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m stomp
WORKDIR /app
COPY --from=build /app/server/target/classes server/target/classes
COPY --from=build /app/client/bin/StompEMIClient client/bin/StompEMIClient
COPY dashboard dashboard
COPY scripts/run_dashboard.py scripts/manage_users.py scripts/
RUN mkdir -p data logs && chown -R stomp:stomp /app
USER stomp
ENV STOMP_WEB_HOST=0.0.0.0 STOMP_DATA_DIR=/app/data PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python3", "scripts/run_dashboard.py", "--mode", "reactor"]

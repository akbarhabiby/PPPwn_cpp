FROM debian:bookworm-slim AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git libpcap-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DUSE_SYSTEM_PCAP=ON -DBUILD_CLI=ON \
    && cmake --build build --target pppwn --parallel

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends libpcap0.8 python3 python3-pip ca-certificates libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home pppwn
COPY --from=build /src/build/pppwn /usr/local/bin/pppwn
RUN setcap cap_net_raw,cap_net_admin+ep /usr/local/bin/pppwn
COPY webapp /opt/pppwn-web
COPY requirements.txt /opt/pppwn-web/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /opt/pppwn-web/requirements.txt
ENV PPPWN_BINARY=/usr/local/bin/pppwn \
    PPPWN_INTERFACE=eth0 \
    PPPWN_FIRMWARE=1100 \
    PPPWN_STAGE1=/payloads/stage1.bin \
    PPPWN_STAGE2=/payloads/stage2.bin \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080
EXPOSE 8080
USER pppwn
WORKDIR /
ENTRYPOINT ["python3", "/opt/pppwn-web/server.py"]

# Photon geocoder (https://github.com/komoot/photon); no official image upstream.
FROM eclipse-temurin:21-jre
ARG PHOTON_VERSION=1.3.0
ADD https://github.com/komoot/photon/releases/download/${PHOTON_VERSION}/photon-${PHOTON_VERSION}.jar /photon/photon.jar
WORKDIR /photon
EXPOSE 2322
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /photon/photon.jar serve -data-dir /data -listen-ip 0.0.0.0 -listen-port 2322"]

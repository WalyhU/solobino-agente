# Jenkins con todo lo que necesita el pipeline de Solobino:
# Python (pruebas + cobertura), Node (Newman), Chromium (Selenium)
# y el cliente de Docker (para levantar el sandbox con el Docker de tu PC).
FROM jenkins/jenkins:lts-jdk21

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip \
      chromium chromium-driver \
      curl ca-certificates gnupg \
  && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y nodejs \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
  && echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
       > /etc/apt/sources.list.d/docker.list \
  && apt-get update && apt-get install -y docker-ce-cli docker-compose-plugin \
  && npm install -g newman newman-reporter-htmlextra \
  && rm -rf /var/lib/apt/lists/*

# Chromium y su driver vienen del mismo paquete de Debian: versiones compatibles.
ENV CHROME_BINARY=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

RUN jenkins-plugin-cli --plugins \
      workflow-aggregator git github junit htmlpublisher \
      credentials-binding timestamper ws-cleanup pipeline-stage-view

# Sin asistente de instalación: el job se crea con init.groovy.d.
ENV JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
COPY init.groovy.d/ /usr/share/jenkins/ref/init.groovy.d/

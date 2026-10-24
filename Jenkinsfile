// Pipeline de calidad de Solobino:
// pruebas unitarias + cobertura -> SonarCloud -> sandbox Docker -> Postman/Newman
// -> integración WebSocket -> Selenium. Pensado para jenkins/docker-compose.yml.
pipeline {
  agent any

  options {
    timestamps()
    timeout(time: 45, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '15'))
  }

  parameters {
    booleanParam(name: 'RUN_SONAR', defaultValue: true, description: 'Enviar análisis a SonarCloud (requiere la credencial SONAR_TOKEN)')
  }

  environment {
    VENV = "${WORKSPACE}/.venv"
    SANDBOX_HOST = 'host.docker.internal'
    COMPOSE_PROJECT_NAME = 'solobino-ci'
  }

  stages {
    stage('Checkout') {
      steps { checkout scm }
    }

    stage('Preparar entorno') {
      steps {
        sh '''
          python3 -m venv "$VENV"
          . "$VENV/bin/activate"
          pip install -q --upgrade pip
          pip install -q -r voice-backend/requirements.txt pytest pytest-cov selenium
          mkdir -p reports
        '''
      }
    }

    stage('Pruebas unitarias + cobertura') {
      steps {
        sh '''
          . "$VENV/bin/activate"
          python -m pytest tests --ignore=tests/selenium --ignore=tests/integration \
            --junitxml=reports/unit-tests.xml --cov --cov-report=xml:coverage.xml --cov-report=term
        '''
      }
    }

    stage('SonarCloud') {
      when { expression { params.RUN_SONAR } }
      steps {
        script {
          try {
            withCredentials([string(credentialsId: 'SONAR_TOKEN', variable: 'SONAR_TOKEN')]) {
              sh 'sonar -Dsonar.host.url=https://sonarcloud.io -Dsonar.token="$SONAR_TOKEN" -Dsonar.qualitygate.wait=true'
            }
          } catch (org.jenkinsci.plugins.credentialsbinding.impl.CredentialNotFoundException e) {
            echo 'No existe la credencial SONAR_TOKEN: se omite SonarCloud (ver CALIDAD.md, paso 3).'
          }
        }
      }
    }

    stage('Levantar sandbox') {
      steps {
        sh '''
          docker compose up -d --build --wait --wait-timeout 300
          curl -fsS "http://$SANDBOX_HOST:8000/health"
        '''
      }
    }

    stage('API - Postman/Newman') {
      steps {
        sh '''
          newman run tests/postman/solobino.postman_collection.json \
            --env-var "baseUrl=http://$SANDBOX_HOST:8000" \
            -r cli,junit,htmlextra \
            --reporter-junit-export reports/newman.xml \
            --reporter-htmlextra-export reports/newman/index.html
        '''
      }
    }

    stage('Integración WebSocket') {
      steps {
        sh '''
          . "$VENV/bin/activate"
          set -a; . ./.env.sandbox; set +a
          SANDBOX_WS_URL="ws://$SANDBOX_HOST:8000/ws" \
            python -m pytest tests/integration -v --junitxml=reports/integration.xml
        '''
      }
    }

    stage('UI - Selenium') {
      steps {
        sh '''
          . "$VENV/bin/activate"
          python -m pytest tests/selenium -v --junitxml=reports/selenium.xml
        '''
      }
    }
  }

  post {
    always {
      sh 'mkdir -p reports && docker compose logs --no-color backend > reports/sandbox.log 2>&1 || true'
      junit allowEmptyResults: true, testResults: 'reports/*.xml'
      publishHTML(target: [reportName: 'Reporte Postman', reportDir: 'reports/newman',
                           reportFiles: 'index.html', keepAll: true, allowMissing: true,
                           alwaysLinkToLastBuild: true])
      archiveArtifacts allowEmptyArchive: true, artifacts: 'reports/**, coverage.xml'
      sh 'docker compose down || true'
    }
  }
}

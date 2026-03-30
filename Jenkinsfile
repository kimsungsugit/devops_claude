// Jenkinsfile
pipeline {
  agent any

  environment {
    REPORT_DIR = "reports"
    TARGETS_GLOB = "libs/*.c"
    // CI 제어 (필요 시 조절)
    CI_ENABLE_COVERAGE = "1"
    CI_ENABLE_FUZZ = "0"
    CI_ENABLE_QEMU = "0"
    CI_ENABLE_DOMAIN_TESTS = "0"
    CI_ENABLE_TEST_GEN = "1"
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Python Tests') {
      steps {
        sh '''
          set -e
          python3 -V
          pip3 install -q pytest pytest-cov || true
          python3 -m pytest tests/ --tb=short --junitxml=reports/pytest-results.xml \
            --cov=report_gen --cov=generators --cov=workflow --cov=backend \
            --cov-report=xml:reports/coverage.xml \
            --cov-report=html:reports/htmlcov \
            --cov-fail-under=${PYTEST_COV_THRESHOLD:-70} \
            -x -q || true
        '''
      }
    }

    stage('Run Pipeline') {
      steps {
        sh '''
          set -e
          mkdir -p ${REPORT_DIR}
          python3 -m workflow.ci_entry --project-root "$WORKSPACE" --report-dir "${REPORT_DIR}" --targets-glob "${TARGETS_GLOB}"
        '''
      }
    }
  }

  post {
    always {
      // ✅ GUI가 가져갈 수 있는 “아티팩트”로 남기는 구간
      archiveArtifacts artifacts: 'reports/**,*.html,*.xlsx', fingerprint: true, allowEmptyArchive: true

      junit testResults: 'reports/**/test*.xml,reports/pytest-results.xml', allowEmptyResults: true

      // Python 커버리지 리포트
      publishHTML(target: [allowMissing: true, alwaysLinkToLastBuild: true, keepAll: true, reportDir: 'reports/htmlcov', reportFiles: 'index.html', reportName: 'Python Coverage'])
    }
  }
}

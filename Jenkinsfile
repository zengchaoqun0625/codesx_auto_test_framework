// ============================================================
// Jenkinsfile — API 自动化测试流水线模板
//
// 使用方式：
//   1. 在 Jenkins 新建 Pipeline 任务，将本文件放到项目根目录
//   2. 在 Jenkins 中配置凭据（Credentials）：
//      - SMTP_PASSWORD / FEISHU_TOKEN 等敏感项用 "Secret text" 类型凭据
//      - 或在 Jenkins 全局环境变量中配置
//   3. 流水线会在每次构建时：装依赖 → 跑测试 → 归档报告
// ============================================================

pipeline {
    agent any

    environment {
        // 敏感配置从 Jenkins 凭据/环境变量注入，勿硬编码
        SEND_EMAIL       = 'only_failed'
        SMTP_USERNAME    = credentials('SMTP_USERNAME')
        SMTP_PASSWORD    = credentials('SMTP_PASSWORD')
        FEISHU_TOKEN     = credentials('FEISHU_TOKEN')
        DINGDING_TOKEN   = credentials('DINGDING_TOKEN')
        DINGDING_SECRET  = credentials('DINGDING_SECRET')
        WEIXIN_TOKEN     = credentials('WEIXIN_TOKEN')
        EMERGENCY_PHONE  = credentials('EMERGENCY_PHONE')
        TEST_EXECUTOR    = 'Jenkins'
        // 失败重试 2 次（网络抖动容错）
        PYTEST_ADDOPTS   = '--reruns 2 --reruns-delay 1'
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()       // 同一项目不并发执行，避免 token 冲突
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    python -m pip install --upgrade pip
                    pip install -r requirements.txt
                    pip install pytest-rerunfailures pytest-xdist
                '''
            }
        }

        stage('Prepare Environment') {
            // 将凭据写入 api_project/.env（框架 ENV.load() 会读取）
            steps {
                writeFile file: 'api_project/.env', text: """
                    SEND_EMAIL=${env.SEND_EMAIL}
                    SMTP_USERNAME=${env.SMTP_USERNAME}
                    SMTP_PASSWORD=${env.SMTP_PASSWORD}
                    FEISHU_TOKEN=${env.FEISHU_TOKEN}
                    DINGDING_TOKEN=${env.DINGDING_TOKEN}
                    DINGDING_SECRET=${env.DINGDING_SECRET}
                    WEIXIN_TOKEN=${env.WEIXIN_TOKEN}
                    EMERGENCY_CONTACT=${env.EMERGENCY_CONTACT ?: ''}
                    EMERGENCY_PHONE=${env.EMERGENCY_PHONE ?: ''}
                """.stripIndent()
            }
        }

        stage('Run API Tests') {
            steps {
                sh 'python run_testcases.py'
            }
        }
    }

    post {
        always {
            // 归档测试产物（成功/失败都保留）
            archiveArtifacts artifacts: 'api_project/data/**', allowEmptyArchive: true
            archiveArtifacts artifacts: 'api_project/history/trend_report.html', allowEmptyArchive: true
            archiveArtifacts artifacts: 'api_project/report/report.html', allowEmptyArchive: true

            // 邮件通知交给框架自身（SEND_EMAIL 控制），Jenkins 不再重复发送
        }
        success {
            echo '✅ API 测试全部通过'
        }
        failure {
            echo '❌ API 测试存在失败用例'
        }
    }
}

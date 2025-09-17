#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
N8N дополнительный экспортер метрик для Prometheus.
Этот скрипт собирает метрики из N8N API и экспортирует их в формате Prometheus.

Требуемые библиотеки:
- jsonformatter
- prometheus_client
- python-dateutil
- python-json-logger
- requests
- schedule
- urllib3

Запуск:
python n8n_metrics_exporter.py
"""
import datetime
import time
import os
import logging
import requests
import schedule
from dateutil import parser
from prometheus_client import start_http_server, Gauge, Histogram, Counter
from pythonjsonlogger.json import JsonFormatter


# Настройка логирования
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging_level = getattr(logging, LOG_LEVEL, logging.INFO)
logger = logging.getLogger('n8n_metrics_exporter')
logger.setLevel(logging_level)

logHandler = logging.StreamHandler()
formatter = JsonFormatter(
    '%(asctime)s %(name)s %(levelname)s %(message)s',
    rename_fields={'asctime': 'timestamp', 'levelname': 'level'},
    json_ensure_ascii=False
)
logHandler.setFormatter(formatter)
logger.handlers = []  # Очистить предыдущие хендлеры
logger.addHandler(logHandler)
logger.info(f"Установлен уровень логирования: {LOG_LEVEL}")

# Конфигурация из переменных среды
N8N_API_URL = os.environ.get('N8N_API_URL', 'http://localhost:5678')
N8N_API_KEY = os.environ.get('N8N_API_KEY', '')
N8N_API_SCRAPE_INTERVAL = int(
    os.environ.get('N8N_API_SCRAPE_INTERVAL', 15)
)  # секунды
N8N_API_EXECUTIONS_LIMIT = int(
    os.environ.get('N8N_API_EXECUTIONS_LIMIT', 50)
)  # лимит на количество получаемых выполнений
METRICS_PORT = int(os.environ.get('METRICS_PORT', 9100))
# Глобальный словарь для хранения id и name WORKFLOWS
WORKFLOWS = {}

# Метрики Prometheus
ACTIVE_WORKFLOWS = Gauge(
    'n8n_workflow_active',
    'Number of currently active workflows'
)
WORKFLOW_EXECUTION_DURATION = Histogram(
    'n8n_workflow_execution_duration_milliseconds',
    'Duration of workflow executions in milliseconds',
    ['owner', 'status'],
    buckets=(10, 100, 500, 1000, 10000, 30000, 60000, 120000)
)
WORKFLOW_EXECUTION_COUNT = Counter(
    'n8n_workflow_execution_count',
    'Total number of workflow executions',
    ['status'])  # Добавляем метку для статуса (success/error)
WORKFLOW_ERROR_COUNT = Counter(
    'n8n_workflow_error_count',
    'Total number of workflow errors'
)


class N8NMetricsCollector:
    def __init__(self, api_url, api_key):
        """Инициализация коллектора метрик N8N."""
        self.api_url = api_url
        self.headers = {
            'X-N8N-API-KEY': api_key,
            'Content-Type': 'application/json'
        }
        logger.info(f"Настроен сбор метрик с API: {api_url}")

    def _make_request(self, endpoint):
        """Выполнение запроса к API N8N."""
        try:
            url = f"{self.api_url}/api/v1/{endpoint}"
            logger.debug(f"Запрос к API: {url}")
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"Ошибка получения данных из API: {e}. URL: {url}")
            # Дополнительная информация для отладки
            if hasattr(e.response, 'text'):
                logger.error(f"Ответ: {e.response.text[:200]}...")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка соединения с API: {str(e)}")
            return None

    def collect_workflows(self):
        """Сбор информации о всех рабочих процессах."""
        # global WORKFLOWS
        WORKFLOWS.clear()
        workflows = self._make_request('workflows?active=true')
        if workflows and 'data' in workflows:
            for wf in workflows['data']:
                wf_id = str(wf.get('id', ''))
                wf_owner = self.get_workflow_owner(wf_id)
                if wf_id and wf_owner:
                    WORKFLOWS[wf_id] = wf_owner
        logger.debug(f"WORKFLOWS обновлен: {WORKFLOWS}")

    def get_workflow_owner(self, workflow_id):
        """Получение владельца workflow."""
        wf_info = self._make_request('workflows/' + workflow_id)
        if wf_info and 'shared' in wf_info:
            for shared_item in wf_info['shared']:
                project = shared_item.get('project')
                if project and 'name' in project:
                    owner = project['name']
                    return owner
                return None
            return None
        return None

    def collect_active_workflows(self):
        """Сбор информации об активных рабочих процессах."""
        active_workflows = self._make_request('executions')

        if active_workflows and 'data' in active_workflows:
            # Считаем только активные
            active_count = sum(
                1 for wf in active_workflows['data']
                if wf.get('status') == 'running'
            )
            ACTIVE_WORKFLOWS.set(active_count)
            logger.debug(f"Обновлено количество активных workflow: {active_count}")

    def collect_workflow_executions(self):
        """Сбор информации о последних выполненных рабочих процессах и их длительности по каждому owner."""
        for wf_id, wf_owner in WORKFLOWS.items():
            # Последнее успешное выполнение для owner
            successful_executions = self._make_request(
                f'executions?status=success&limit={N8N_API_EXECUTIONS_LIMIT}&workflowId={wf_id}'
            )
            self._process_executions(successful_executions, 'success', wf_owner, wf_id)

            # Последнее ошибочное выполнение для owner
            error_executions = self._make_request(
                f'executions?status=error&limit={N8N_API_EXECUTIONS_LIMIT}&workflowId={wf_id}'
            )
            self._process_executions(error_executions, 'error', wf_owner, wf_id)

    def _process_executions(self, executions, status, wf_owner, wf_id):
        """Обработка данных об исполнениях Workflow, считаем среднее время выполнения по Owner."""
        if executions and 'data' in executions and executions['data']:
            for execution in executions['data']:
                start_time = execution.get('startedAt')
                end_time = execution.get('stoppedAt')
                if start_time and end_time:
                    try:
                        start = parser.isoparse(start_time)
                        end = parser.isoparse(end_time)

                        # Учитываем все `executions` попадающие в интервал опроса API.
                        # Будет более сглажено, но не пропустим данные, которые могли быть получены в момент опроса.
                        now = datetime.datetime.now(datetime.UTC)
                        # Двойной интервал, чтобы не пропустить данные, которые могли быть получены в момент опроса
                        # В API не сразу появляется execution, а с задержкой + время самого опроса
                        if not (now - datetime.timedelta(seconds=N8N_API_SCRAPE_INTERVAL*2) < end <= now):
                            logger.debug(f"Execution {execution.get('id')} workflow {wf_id} end_time {end_time} "
                                         f"не попадают в интервал опроса API")
                            continue
                        logger.debug(
                            f"Обработка выполнения Execution {execution.get('id')} Workflow {wf_id} "
                            f"status {status} start_time {start_time} end_time {end_time}")

                        duration = end - start
                        # Получаем ms
                        duration_in_ms = duration.total_seconds() * 1000
                        # Обновление метрик
                        WORKFLOW_EXECUTION_DURATION.labels(owner=wf_owner, status=status).observe(duration_in_ms)
                        WORKFLOW_EXECUTION_COUNT.labels(status=status).inc()
                        if status == 'error':
                            WORKFLOW_ERROR_COUNT.inc()
                        logger.debug(
                            f"Зафиксировано выполнение Workflow {wf_id} "
                            f"(owner: {wf_owner}) со статусом {status} и длительностью {duration_in_ms} ms"
                        )
                    except (ValueError, TypeError) as e:
                        logger.error(
                            f"Ошибка форматирования времени для Execution {execution.get('id')} "
                            f"Workflow {wf_id} owner {wf_owner}: {e}"
                        )
                        logger.error(
                            f"Проблемные значения: start_time={start_time}, end_time={end_time}"
                        )

    def collect_metrics(self):
        """Сбор всех метрик."""
        logger.debug("Начат сбор метрик...")
        self.collect_workflows()
        self.collect_active_workflows()
        self.collect_workflow_executions()
        logger.debug("Сбор метрик завершен")


def main():
    """Основная функция."""
    logger.info(f"Запуск экспортера метрик N8N на порту {METRICS_PORT}")
    start_http_server(METRICS_PORT)

    collector = N8NMetricsCollector(N8N_API_URL, N8N_API_KEY)

    # Первоначальный сбор метрик
    collector.collect_metrics()

    # Расписание периодического сбора метрик
    schedule.every(N8N_API_SCRAPE_INTERVAL).seconds.do(collector.collect_metrics)

    logger.info(
        f"Экспортер метрик запущен и работает с интервалом сбора {N8N_API_SCRAPE_INTERVAL} сек"
    )

    # Бесконечный цикл для выполнения расписания
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()

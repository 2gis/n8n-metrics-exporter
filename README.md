# n8n-metrics-exporter

Экспортер метрик для Prometheus, собирающий статистику о workflow из API n8n.

## Описание

Скрипт подключается к API n8n, собирает информацию о workflow (активные, успешные и ошибочные выполнения, длительность) и экспортирует метрики в формате Prometheus. Подходит для мониторинга процессов n8n.

## Входные параметры (переменные окружения)

- `N8N_API_URL` — URL API n8n (по умолчанию: `http://localhost:5678`)
- `N8N_API_KEY` — API-ключ для доступа к n8n (по умолчанию: пусто)
- `METRICS_PORT` — порт для экспорта метрик Prometheus (по умолчанию: `9100`)
- `N8N_API_SCRAPE_INTERVAL` — интервал опроса API n8n в секундах (по умолчанию: `15`)
- `N8N_API_EXECUTIONS_LIMIT` — лимит на количество получаемых выполнений (по умолчанию: `50`)
- `LOG_LEVEL` — уровень логирования (`DEBUG`, `INFO`, `WARNING`, `ERROR`; по умолчанию: `INFO`)

## Установка

1. Установите зависимости:

```sh
pip install -r src/requirements.txt
```

2. Скачайте скрипт `src/n8n_metrics_exporter.py`.

## Запуск

```sh
export N8N_API_URL=http://localhost:5678
export N8N_API_KEY=your_n8n_api_key
python src/n8n_metrics_exporter.py
```

или

```sh
docker-compose up -d -f script/docker-compose.yml
```

## Экспортируемые метрики

- `n8n_workflow_active` — количество активных workflow (gauge)
- `n8n_workflow_execution_duration_milliseconds{owner, status}` — длительность выполнения workflow (histogram)
- `n8n_workflow_execution_count{status}` — количество выполнений workflow по статусу (counter)
- `n8n_workflow_error_count` — количество ошибок workflow (counter)

## Функционал

- Сбор информации о workflow и их владельцах
- Подсчет активных workflow
- Сбор статистики по успешным и ошибочным выполнениям
- Экспорт метрик для Prometheus

## Разработка

### Структура проекта

```
src/
├── n8n_metrics_exporter.py         # Основной модуль экспортера
├── test_n8n_metrics_exporter.py    # Тесты
└── requirements.txt                # Зависимости
```

### Добавление новых тестов

При добавлении новой функциональности рекомендуется:

1. Написать тесты для новых функций
2. Проверить, что все существующие тесты проходят
3. Убедиться в корректной обработке граничных случаев

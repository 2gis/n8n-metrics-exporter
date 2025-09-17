#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unit тесты для N8N экспортера метрик.
"""

import unittest
import datetime
from unittest.mock import Mock, patch
import requests

# Импортируем модуль для тестирования
import n8n_metrics_exporter


class TestN8NMetricsCollector(unittest.TestCase):
    """Тесты для класса N8NMetricsCollector."""

    def setUp(self):
        """Подготовка для каждого теста."""
        self.api_url = 'http://test-n8n.example.com'
        self.api_key = 'test-api-key'
        self.collector = n8n_metrics_exporter.N8NMetricsCollector(
            self.api_url, self.api_key
        )

    def test_init(self):
        """Тест инициализации коллектора."""
        self.assertEqual(self.collector.api_url, self.api_url)
        self.assertEqual(
            self.collector.headers['X-N8N-API-KEY'], self.api_key
        )
        self.assertEqual(
            self.collector.headers['Content-Type'], 'application/json'
        )

    @patch('n8n_metrics_exporter.requests.get')
    def test_make_request_success(self, mock_get):
        """Тест успешного выполнения запроса к API."""
        mock_response = Mock()
        mock_response.json.return_value = {'data': 'test'}
        mock_get.return_value = mock_response

        result = self.collector._make_request('test-endpoint')

        mock_get.assert_called_once_with(
            f'{self.api_url}/api/v1/test-endpoint',
            headers=self.collector.headers
        )
        self.assertEqual(result, {'data': 'test'})

    @patch('n8n_metrics_exporter.requests.get')
    def test_make_request_http_error(self, mock_get):
        """Тест обработки HTTP ошибки."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        mock_response.text = 'Error details'
        mock_get.return_value = mock_response

        result = self.collector._make_request('test-endpoint')

        self.assertIsNone(result)

    @patch('n8n_metrics_exporter.requests.get')
    def test_make_request_connection_error(self, mock_get):
        """Тест обработки ошибки соединения."""
        mock_get.side_effect = requests.exceptions.ConnectionError()

        result = self.collector._make_request('test-endpoint')

        self.assertIsNone(result)

    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_make_request')
    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, 'get_workflow_owner')
    def test_collect_workflows(self, mock_get_owner, mock_request):
        """Тест сбора информации о workflows."""
        mock_request.return_value = {
            'data': [
                {'id': '1', 'name': 'Workflow 1'},
                {'id': '2', 'name': 'Workflow 2'}
            ]
        }
        mock_get_owner.side_effect = ['owner1', 'owner2']

        self.collector.collect_workflows()

        mock_request.assert_called_once_with('workflows?active=true')
        self.assertEqual(len(n8n_metrics_exporter.WORKFLOWS), 2)
        self.assertEqual(n8n_metrics_exporter.WORKFLOWS['1'], 'owner1')
        self.assertEqual(n8n_metrics_exporter.WORKFLOWS['2'], 'owner2')

    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_make_request')
    def test_get_workflow_owner(self, mock_request):
        """Тест получения владельца workflow."""
        mock_request.return_value = {
            'shared': [
                {'project': {'name': 'test-project'}}
            ]
        }

        result = self.collector.get_workflow_owner('test-id')

        mock_request.assert_called_once_with('workflows/test-id')
        self.assertEqual(result, 'test-project')

    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_make_request')
    def test_get_workflow_owner_no_project(self, mock_request):
        """Тест получения владельца workflow без проекта."""
        mock_request.return_value = {'shared': [{}]}

        result = self.collector.get_workflow_owner('test-id')

        self.assertIsNone(result)

    @patch('n8n_metrics_exporter.ACTIVE_WORKFLOWS')
    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_make_request')
    def test_collect_active_workflows(self, mock_request, mock_gauge):
        """Тест сбора активных workflows."""
        mock_request.return_value = {
            'data': [
                {'status': 'running'},
                {'status': 'success'},
                {'status': 'running'},
                {'status': 'error'}
            ]
        }

        self.collector.collect_active_workflows()

        mock_gauge.set.assert_called_once_with(2)

    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_make_request')
    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, '_process_executions')
    def test_collect_workflow_executions(self, mock_process, mock_request):
        """Тест сбора выполнений workflows."""
        n8n_metrics_exporter.WORKFLOWS = {'1': 'owner1', '2': 'owner2'}

        mock_request.side_effect = [
            {'data': 'success_data_1'}, {'data': 'error_data_1'},
            {'data': 'success_data_2'}, {'data': 'error_data_2'}
        ]

        self.collector.collect_workflow_executions()

        # Проверяем правильные вызовы API
        expected_calls = [
            unittest.mock.call(f'executions?status=success&limit={n8n_metrics_exporter.N8N_API_EXECUTIONS_LIMIT}&workflowId=1'),
            unittest.mock.call(f'executions?status=error&limit={n8n_metrics_exporter.N8N_API_EXECUTIONS_LIMIT}&workflowId=1'),
            unittest.mock.call(f'executions?status=success&limit={n8n_metrics_exporter.N8N_API_EXECUTIONS_LIMIT}&workflowId=2'),
            unittest.mock.call(f'executions?status=error&limit={n8n_metrics_exporter.N8N_API_EXECUTIONS_LIMIT}&workflowId=2')
        ]
        mock_request.assert_has_calls(expected_calls)

        # Проверяем вызовы обработки
        expected_process_calls = [
            unittest.mock.call({'data': 'success_data_1'}, 'success', 'owner1', '1'),
            unittest.mock.call({'data': 'error_data_1'}, 'error', 'owner1', '1'),
            unittest.mock.call({'data': 'success_data_2'}, 'success', 'owner2', '2'),
            unittest.mock.call({'data': 'error_data_2'}, 'error', 'owner2', '2')
        ]
        mock_process.assert_has_calls(expected_process_calls)

    def test_process_executions_valid_data(self):
        """Тест обработки валидных данных выполнений."""
        current_time = datetime.datetime.now(datetime.timezone.utc)
        start_time = current_time - datetime.timedelta(seconds=10)
        end_time = current_time - datetime.timedelta(seconds=3)

        executions = {'data': [{
            'id': 'exec-123',
            'startedAt': start_time.isoformat(),
            'stoppedAt': end_time.isoformat()
        }]}

        with patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION') as mock_duration, \
             patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT') as mock_count, \
             patch('n8n_metrics_exporter.WORKFLOW_ERROR_COUNT') as mock_error, \
             patch('n8n_metrics_exporter.N8N_API_SCRAPE_INTERVAL', 15), \
             patch('n8n_metrics_exporter.datetime') as mock_datetime, \
             patch('n8n_metrics_exporter.logger'):

            # Настраиваем мок datetime
            mock_datetime.datetime.now.return_value = current_time
            mock_datetime.UTC = datetime.timezone.utc
            mock_datetime.timedelta = datetime.timedelta

            self.collector._process_executions(executions, 'success', 'test_owner', 'wf_id')

            # Проверяем обновление метрик
            mock_duration.labels.assert_called_with(owner='test_owner', status='success')
            mock_duration.labels().observe.assert_called_once()
            mock_count.labels.assert_called_with(status='success')
            mock_count.labels().inc.assert_called_once()
            mock_error.inc.assert_not_called()

    def test_process_executions_error_status(self):
        """Тест обработки выполнений со статусом error."""
        current_time = datetime.datetime.now(datetime.timezone.utc)
        start_time = current_time - datetime.timedelta(seconds=10)
        end_time = current_time - datetime.timedelta(seconds=3)

        executions = {'data': [{
            'id': 'exec-error',
            'startedAt': start_time.isoformat(),
            'stoppedAt': end_time.isoformat()
        }]}

        with patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION') as mock_duration, \
             patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT') as mock_count, \
             patch('n8n_metrics_exporter.WORKFLOW_ERROR_COUNT') as mock_error, \
             patch('n8n_metrics_exporter.N8N_API_SCRAPE_INTERVAL', 15), \
             patch('n8n_metrics_exporter.datetime') as mock_datetime, \
             patch('n8n_metrics_exporter.logger'):

            mock_datetime.datetime.now.return_value = current_time
            mock_datetime.UTC = datetime.timezone.utc
            mock_datetime.timedelta = datetime.timedelta

            self.collector._process_executions(executions, 'error', 'test_owner', 'wf_id')

            # Проверяем обновление метрик для ошибок
            mock_duration.labels.assert_called_with(owner='test_owner', status='error')
            mock_count.labels.assert_called_with(status='error')
            mock_error.inc.assert_called_once()

    def test_process_executions_outside_time_window(self):
        """Тест игнорирования выполнений вне временного окна."""
        current_time = datetime.datetime.now(datetime.timezone.utc)
        # Старое выполнение (более чем двойной интервал назад)
        start_time = current_time - datetime.timedelta(seconds=100)
        end_time = current_time - datetime.timedelta(seconds=90)

        executions = {'data': [{
            'id': 'exec-old',
            'startedAt': start_time.isoformat(),
            'stoppedAt': end_time.isoformat()
        }]}

        with patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION') as mock_duration, \
             patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT') as mock_count, \
             patch('n8n_metrics_exporter.N8N_API_SCRAPE_INTERVAL', 15), \
             patch('n8n_metrics_exporter.datetime') as mock_datetime, \
             patch('n8n_metrics_exporter.logger'):

            mock_datetime.datetime.now.return_value = current_time
            mock_datetime.UTC = datetime.timezone.utc
            mock_datetime.timedelta = datetime.timedelta

            self.collector._process_executions(executions, 'success', 'test_owner', 'wf_id')

            # Метрики не должны обновляться
            mock_duration.labels.assert_not_called()
            mock_count.labels.assert_not_called()

    def test_process_executions_invalid_time_format(self):
        """Тест обработки невалидного формата времени."""
        executions = {'data': [{
            'id': 'exec-invalid',
            'startedAt': 'invalid-time',
            'stoppedAt': 'invalid-time'
        }]}

        with patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION') as mock_duration, \
             patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT') as mock_count, \
             patch('n8n_metrics_exporter.logger'):

            self.collector._process_executions(executions, 'success', 'test_owner', 'wf_id')

            # Метрики не должны обновляться при ошибке парсинга
            mock_duration.labels.assert_not_called()
            mock_count.labels.assert_not_called()

    def test_process_executions_missing_times(self):
        """Тест обработки выполнений без времен start/stop."""
        executions = {'data': [{
            'id': 'exec-no-times'
            # Отсутствуют startedAt и stoppedAt
        }]}

        with patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION') as mock_duration, \
             patch('n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT') as mock_count, \
             patch('n8n_metrics_exporter.logger'):

            self.collector._process_executions(executions, 'success', 'test_owner', 'wf_id')

            # Метрики не должны обновляться
            mock_duration.labels.assert_not_called()
            mock_count.labels.assert_not_called()

    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, 'collect_workflows')
    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, 'collect_active_workflows')
    @patch.object(n8n_metrics_exporter.N8NMetricsCollector, 'collect_workflow_executions')
    def test_collect_metrics(self, mock_executions, mock_active, mock_workflows):
        """Тест главного метода сбора метрик."""
        self.collector.collect_metrics()

        mock_workflows.assert_called_once()
        mock_active.assert_called_once()
        mock_executions.assert_called_once()


class TestEnvironmentVariables(unittest.TestCase):
    """Тесты для переменных окружения."""

    def test_environment_variables_default_values(self):
        """Тест значений переменных окружения по умолчанию."""
        # Проверяем, что переменные имеют ожидаемые значения по умолчанию
        self.assertEqual(n8n_metrics_exporter.N8N_API_URL, 'http://localhost:5678')
        self.assertEqual(n8n_metrics_exporter.N8N_API_KEY, '')
        self.assertEqual(n8n_metrics_exporter.N8N_API_SCRAPE_INTERVAL, 15)
        self.assertEqual(n8n_metrics_exporter.N8N_API_EXECUTIONS_LIMIT, 50)
        self.assertEqual(n8n_metrics_exporter.METRICS_PORT, 9100)

    @patch.dict('os.environ', {
        'N8N_API_URL': 'http://custom-n8n.example.com',
        'N8N_API_KEY': 'custom-key',
        'N8N_API_SCRAPE_INTERVAL': '30',
        'N8N_API_EXECUTIONS_LIMIT': '100',
        'METRICS_PORT': '9200',
        'LOG_LEVEL': 'DEBUG'
    })
    @patch('n8n_metrics_exporter.os.environ')
    def test_environment_variables_custom_values(self, mock_environ):
        """Тест получения пользовательских значений переменных окружения."""
        mock_environ.get.side_effect = lambda key, default=None: {
            'N8N_API_URL': 'http://custom-n8n.example.com',
            'N8N_API_KEY': 'custom-key',
            'N8N_API_SCRAPE_INTERVAL': '30',
            'N8N_API_EXECUTIONS_LIMIT': '100',
            'METRICS_PORT': '9200',
            'LOG_LEVEL': 'DEBUG'
        }.get(key, default)

        # Тестируем функции получения переменных окружения
        import os
        url = os.environ.get('N8N_API_URL', 'http://localhost:5678')
        api_key = os.environ.get('N8N_API_KEY', '')
        scrape_interval = int(os.environ.get('N8N_API_SCRAPE_INTERVAL', 15))
        executions_limit = int(os.environ.get('N8N_API_EXECUTIONS_LIMIT', 50))
        metrics_port = int(os.environ.get('METRICS_PORT', 9100))

        self.assertEqual(url, 'http://custom-n8n.example.com')
        self.assertEqual(api_key, 'custom-key')
        self.assertEqual(scrape_interval, 30)
        self.assertEqual(executions_limit, 100)
        self.assertEqual(metrics_port, 9200)


class TestMetricsInitialization(unittest.TestCase):
    """Тесты для инициализации метрик Prometheus."""

    def test_metrics_objects_created(self):
        """Тест создания объектов метрик."""
        self.assertIsNotNone(n8n_metrics_exporter.ACTIVE_WORKFLOWS)
        self.assertIsNotNone(n8n_metrics_exporter.WORKFLOW_EXECUTION_DURATION)
        self.assertIsNotNone(n8n_metrics_exporter.WORKFLOW_EXECUTION_COUNT)
        self.assertIsNotNone(n8n_metrics_exporter.WORKFLOW_ERROR_COUNT)

    def test_workflows_global_dict(self):
        """Тест глобального словаря WORKFLOWS."""
        self.assertIsInstance(n8n_metrics_exporter.WORKFLOWS, dict)


if __name__ == '__main__':
    unittest.main()

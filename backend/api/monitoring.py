"""Small process-local Prometheus text exporter and privacy-safe request logging."""
from collections import Counter
from datetime import datetime, timezone
import json
import logging
import sys
import threading
import time

APPROACHES = {'metadata_preference', 'pakistan_tfidf_content', 'hawaii_personalized_hybrid'}
AGGREGATIONS = {'individual', 'average', 'least_misery', 'adaptive_consensus'}
RECOMMENDATION_ROUTES = {
    '/groups/{group_id}/recommendations': 'group',
    '/groups/{group_id}/recommendations/individual': 'individual',
}
METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}
BUCKETS = (.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10)


class SafeJSONFormatter(logging.Formatter):
    """Never serialize log messages, exception text, request objects or tracebacks."""
    def format(self, record):
        event = {'timestamp': datetime.now(timezone.utc).isoformat(), 'level': record.levelname}
        if record.name == 'humsafar.requests' and hasattr(record, 'monitoring'):
            event['event'] = 'http_request'
            for key in ('method', 'route', 'status', 'duration_ms', 'recommendation_kind', 'approaches', 'aggregation'):
                if key in record.monitoring:
                    event[key] = record.monitoring[key]
        else:
            event['event'] = 'server_error' if record.levelno >= logging.ERROR else 'server_event'
        return json.dumps(event, separators=(',', ':'))


def request_logger():
    logger = logging.getLogger('humsafar.requests')
    if not any(getattr(handler, 'humsafar_safe', False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.humsafar_safe = True
        handler.setFormatter(SafeJSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def approaches_from_payload(payload):
    # Read only existing mode identifiers, never member IDs, scores or preferences.
    values = [payload.get('mode')] if 'mode' in payload else payload.get('member_modes', {}).values()
    return sorted({mode if mode in APPROACHES else 'other' for mode in values})


def labels(**values):
    return '{'+','.join(key+'='+json.dumps(str(value)) for key, value in values.items())+'}'


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = Counter()
        self.errors = Counter()
        self.durations = {}
        self.recommendations = Counter()
        self.approach_requests = Counter()
        self.active_approaches = ['not_observed']
        self.active_aggregation = 'not_observed'

    def observe(self, method, route, status, duration, approaches=(), aggregation='other'):
        key = (method, route, status)
        duration = max(0., duration)
        kind = RECOMMENDATION_ROUTES.get(route) if method == 'POST' else None
        approaches = sorted({a if a in APPROACHES else 'other' for a in approaches})
        aggregation = aggregation if aggregation in AGGREGATIONS else 'other'
        with self.lock:
            self.requests[key] += 1
            if status >= 400:
                self.errors[key] += 1
            timing = self.durations.setdefault((method, route), [0, 0., [0]*len(BUCKETS)])
            timing[0] += 1
            timing[1] += duration
            for i, bound in enumerate(BUCKETS):
                timing[2][i] += int(duration <= bound)
            if kind:
                self.recommendations[(kind, status)] += 1
                if status < 400 and approaches:
                    self.active_approaches = approaches
                    self.active_aggregation = aggregation
                    for approach in approaches:
                        self.approach_requests[(approach, aggregation)] += 1

    def render(self):
        lines = []
        def declare(name, kind, help_text):
            lines.extend(['# HELP '+name+' '+help_text, '# TYPE '+name+' '+kind])
        with self.lock:
            for source, name, help_text in [
                (self.requests, 'humsafar_http_requests_total', 'Completed API requests by route template.'),
                (self.errors, 'humsafar_http_errors_total', 'Completed HTTP 4xx and 5xx responses.'),
            ]:
                declare(name, 'counter', help_text)
                for (method, route, status), count in sorted(source.items()):
                    lines.append(name+labels(method=method, route=route, status=status)+' '+str(count))
            name = 'humsafar_http_request_duration_seconds'
            declare(name, 'histogram', 'ASGI request duration including response generation and sending.')
            for (method, route), (count, total, buckets) in sorted(self.durations.items()):
                for bound, value in zip(BUCKETS, buckets):
                    lines.append(name+'_bucket'+labels(method=method, route=route, le=bound)+' '+str(value))
                lines.append(name+'_bucket'+labels(method=method, route=route, le='+Inf')+' '+str(count))
                lines.append(name+'_count'+labels(method=method, route=route)+' '+str(count))
                lines.append(name+'_sum'+labels(method=method, route=route)+' '+repr(total))
            for name, failures_only, help_text in [
                ('humsafar_recommendation_requests_total', False, 'Recommendation POST attempts, including denied/invalid requests.'),
                ('humsafar_recommendation_failures_total', True, 'Recommendation POST responses with HTTP status at least 400.'),
            ]:
                declare(name, 'counter', help_text)
                for kind in ('group', 'individual'):
                    count = sum(v for (k, status), v in self.recommendations.items()
                                if k == kind and (not failures_only or status >= 400))
                    lines.append(name+labels(kind=kind)+' '+str(count))
            declare('humsafar_recommendation_approach_requests_total', 'counter', 'Successful requests using each distinct approach, once per request.')
            for (approach, aggregation), count in sorted(self.approach_requests.items()):
                lines.append('humsafar_recommendation_approach_requests_total'+labels(approach=approach, aggregation=aggregation)+' '+str(count))
            declare('humsafar_recommendation_approach_info', 'gauge', 'Approaches observed in the most recent successful recommendation, not model readiness.')
            for approach in self.active_approaches:
                lines.append('humsafar_recommendation_approach_info'+labels(approach=approach)+' 1')
            declare('humsafar_recommendation_aggregation_info', 'gauge', 'Aggregation of most recent successful recommendation.')
            lines.append('humsafar_recommendation_aggregation_info'+labels(aggregation=self.active_aggregation)+' 1')
            declare('humsafar_monitoring_start_time_seconds', 'gauge', 'Unix time when this process-local metrics registry was created.')
            lines.append('humsafar_monitoring_start_time_seconds '+repr(self.started))
        return '\n'.join(lines)+'\n'


class MonitoringMiddleware:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics
        self.logger = request_logger()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500

        async def capture(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            duration = time.perf_counter()-started
            # Only framework route templates. Never request.url, query, body,
            # headers, client address, path parameters or exception messages.
            route = getattr(scope.get('route'), 'path', '__unmatched__')
            method = scope['method'] if scope['method'] in METHODS else 'OTHER'
            state = scope.get('state', {})
            approaches = state.get('monitoring_approaches', ()) if status < 400 else ()
            approaches = sorted({a if a in APPROACHES else 'other' for a in approaches})
            aggregation = state.get('monitoring_aggregation', 'other')
            aggregation = aggregation if aggregation in AGGREGATIONS else 'other'
            self.metrics.observe(method, route, status, duration, approaches, aggregation)
            event = {'method': method, 'route': route, 'status': status, 'duration_ms': round(duration*1000, 3)}
            if method == 'POST' and route in RECOMMENDATION_ROUTES:
                event.update(recommendation_kind=RECOMMENDATION_ROUTES[route], approaches=approaches, aggregation=aggregation)
            self.logger.info('http_request', extra={'monitoring': event})

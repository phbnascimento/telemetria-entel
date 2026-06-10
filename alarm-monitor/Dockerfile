FROM python:3.12-slim
WORKDIR /app

COPY alarm-monitor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alarm-monitor/monitor.py .
# módulos compartilhados com o dashboard
COPY entel-dashboard/auth.py .
COPY entel-dashboard/config_store.py .

CMD ["python", "-u", "monitor.py"]

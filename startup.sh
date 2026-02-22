#!/bin/bash
set -e
pip install -r requirements.txt
exec gunicorn --bind 0.0.0.0:8000 --worker-class aiohttp.GunicornWebWorker --access-logfile - --error-logfile - src.interfaces.teams_bot:app

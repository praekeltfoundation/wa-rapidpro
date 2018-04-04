FROM praekeltfoundation/rapidpro:v3.0.136p18

COPY requirements-engage.txt /app/requirements-engage.txt
RUN /venv/bin/pip install -r /app/requirements-engage.txt

RUN cp /rapidpro/temba/settings.py /rapidpro/temba/settings_original.py
COPY settings.py /rapidpro/temba/settings.py

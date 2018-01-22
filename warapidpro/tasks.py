import requests
import json
from datetime import datetime, timedelta
from temba import celery_app
from dateutil import parser
from django.conf import settings
from django.db.models import Q
from warapidpro.types import WhatsAppDirectType, WhatsAppGroupType
from warapidpro.views import DEFAULT_AUTH_URL


@celery_app.task
def refresh_channel_auth_token(channel_pk):
    from temba.channels.models import Channel

    channel = Channel.objects.get(pk=channel_pk)
    config = channel.config_json()
    authorization = config['authorization']

    wassup_url = getattr(
        settings, 'WASSUP_AUTH_URL', DEFAULT_AUTH_URL)
    client_id = getattr(
        settings, 'WASSUP_AUTH_CLIENT_ID', None)
    client_secret = getattr(
        settings, 'WASSUP_AUTH_CLIENT_SECRET', None)

    response = requests.post(
        '%s/oauth/token/' % (wassup_url,),
        {
            "grant_type": "refresh_token",
            "refresh_token": authorization['refresh_token'],
            "client_id": client_id,
            "client_secret": client_secret,
        },
        {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
        })
    response.raise_for_status()
    new_authorization = response.json()

    config.update({
        'authorization': new_authorization,
        'expires_at': (
            datetime.now() + timedelta(
                seconds=new_authorization['expires_in'])).isoformat(),
    })

    channel.config = json.dumps(config)
    channel.save()


@celery_app.task
def refresh_channel_auth_tokens(delta=timedelta(minutes=5)):
    from temba.channels.models import Channel
    channels = Channel.objects.filter(
        Q(channel_type=WhatsAppDirectType.code) |
        Q(channel_type=WhatsAppGroupType.code))
    for channel in channels:
        config = channel.config_json()
        # This is for integrations that are pre-oauth
        # and which use an api_token which doesn't expire
        if 'expires_at' not in config:
            continue
        expires_at = parser.parse(config['expires_at'])
        marker = datetime.now() + delta
        if marker > expires_at:
            refresh_channel_auth_token.delay(channel.pk)

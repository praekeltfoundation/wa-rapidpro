import responses
import json
import urlparse
from mock import patch

from temba.tests import TembaTest
from datetime import datetime, timedelta

from temba.channels.models import Channel
from warapidpro.types import WhatsAppDirectType
from warapidpro.tasks import (
    refresh_channel_auth_token,
    refresh_channel_auth_tokens)


class TaskTestCase(TembaTest):

    @responses.activate
    @patch.object(refresh_channel_auth_token, 'delay')
    def test_refresh_channel_auth_tokens(self, patched_delay):

        # channel set for refreshing
        refresh_channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config={
                "authorization": {
                    "access_token": "a",
                    "refresh_token": "b",
                },
                "expires_at": datetime.now().isoformat(),
            },
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

        # channel still ok
        Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config={
                "authorization": {
                    "access_token": "a",
                    "refresh_token": "b",
                },
                "expires_at": (
                    datetime.now() + timedelta(days=5)).isoformat(),
            },
            uuid='00000000-0000-0000-0000-000000005678',
            role=Channel.DEFAULT_ROLE)

        refresh_channel_auth_tokens()
        patched_delay.assert_called_with(refresh_channel.pk)

    @responses.activate
    def test_refresh_token(self):

        def cb(request):
            data = urlparse.parse_qs(request.body)
            self.assertEquals(data['grant_type'], ['refresh_token'])
            self.assertEquals(data['refresh_token'], ['b'])
            return (200, {}, json.dumps({
                'access_token': 'foo',
                'refresh_token': 'bar',
                'expires_in': 3600,
            }))

        responses.add_callback(
            responses.POST,
            'https://wassup.p16n.org/oauth/token/',
            callback=cb, content_type='application/json')

        channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config={
                "authorization": {
                    "access_token": "a",
                    "refresh_token": "b",
                },
                "expires_at": datetime.now().isoformat(),
            },
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

        refresh_channel_auth_token(channel.pk)

        old_config = channel.config_json()
        channel.refresh_from_db()
        new_config = channel.config_json()
        new_authorization = new_config['authorization']
        self.assertEqual(new_authorization['access_token'], 'foo')
        self.assertEqual(new_authorization['refresh_token'], 'bar')
        self.assertEqual(new_authorization['expires_in'], 3600)
        self.assertTrue(
            new_config['expires_at'] > old_config['expires_at'])

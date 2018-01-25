import responses
import json
import urlparse
from mock import patch

from temba.tests import TembaTest
from datetime import datetime, timedelta

from django.utils import timezone

from temba.channels.models import Channel
from warapidpro.types import WhatsAppDirectType
from warapidpro.models import (
    has_whatsapp_contactfield,
    has_whatsapp_timestamp_contactfield)
from warapidpro.tasks import (
    refresh_channel_auth_token,
    refresh_channel_auth_tokens,
    check_contact_whatsappable,
    check_org_whatsappable,
    refresh_org_whatsappable)


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


class ContactRefreshTaskTestCase(TembaTest):

    def setUp(self):
        super(ContactRefreshTaskTestCase, self).setUp()
        self.old_style_channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config=dict(api_token='api-token', secret='secret'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

        self.new_style_channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config={
                'authorization': {
                    'token_type': 'Bearer',
                    'access_token': 'foo',
                }
            },
            uuid='00000000-0000-0000-0000-000000005678',
            role=Channel.DEFAULT_ROLE)

    @responses.activate
    def test_check_contact_whatsappable_old_channel_config(self):

        def cb(request):
            self.assertEqual(
                request.headers['Authorization'], 'Token api-token')
            return (200, {}, json.dumps({
                self.old_style_channel.address: {
                    "exists": True
                }
            }))

        responses.add_callback(
            responses.GET,
            ("https://wassup.p16n.org/api/v1/numbers/check/"
             "?wait=true&number=%2B27000000000&address=%2B254788383383"),
            callback=cb, content_type='application/json',
            match_querystring=True)

        joe = self.create_contact("Joe Biden", "+254788383383")
        check_contact_whatsappable(joe.pk, self.old_style_channel.pk)

        has_whatsapp = joe.values.get(contact_field__key='has_whatsapp')
        self.assertEqual(has_whatsapp.string_value, 'yes')

        one_minute_ago = timezone.now() - timedelta(minutes=1)
        has_whatsapp_timestamp = joe.values.get(
            contact_field__key='has_whatsapp_timestamp')
        self.assertTrue(has_whatsapp_timestamp.datetime_value > one_minute_ago)

    @responses.activate
    def test_check_contact_whatsappable_new_channel_config(self):

        def cb(request):
            self.assertEqual(request.headers['Authorization'], 'Bearer foo')
            return (200, {}, json.dumps({
                self.new_style_channel.address: {
                    "exists": True
                }
            }))

        responses.add_callback(
            responses.GET,
            ("https://wassup.p16n.org/api/v1/numbers/check/"
             "?wait=true&number=%2B27000000000&address=%2B254788383383"),
            callback=cb, content_type='application/json',
            match_querystring=True)

        joe = self.create_contact("Joe Biden", "+254788383383")
        check_contact_whatsappable(joe.pk, self.new_style_channel.pk)

        has_whatsapp = joe.values.get(contact_field__key='has_whatsapp')
        self.assertEqual(has_whatsapp.string_value, 'yes')

        one_minute_ago = timezone.now() - timedelta(minutes=1)
        has_whatsapp_timestamp = joe.values.get(
            contact_field__key='has_whatsapp_timestamp')
        self.assertTrue(has_whatsapp_timestamp.datetime_value > one_minute_ago)

    @responses.activate
    def test_check_contact_not_whatsappable(self):

        def cb(request):
            self.assertEqual(request.headers['Authorization'], 'Bearer foo')
            return (200, {}, json.dumps({
                self.new_style_channel.address: {
                    "exists": "something not true"
                }
            }))

        responses.add_callback(
            responses.GET,
            ("https://wassup.p16n.org/api/v1/numbers/check/"
             "?wait=true&number=%2B27000000000&address=%2B254788383383"),
            callback=cb, content_type='application/json',
            match_querystring=True)

        joe = self.create_contact("Joe Biden", "+254788383383")
        check_contact_whatsappable(joe.pk, self.new_style_channel.pk)

        has_whatsapp = joe.values.get(contact_field__key='has_whatsapp')
        self.assertEqual(has_whatsapp.string_value, 'no')

        one_minute_ago = timezone.now() - timedelta(minutes=1)
        has_whatsapp_timestamp = joe.values.get(
            contact_field__key='has_whatsapp_timestamp')
        self.assertTrue(has_whatsapp_timestamp.datetime_value > one_minute_ago)

    @responses.activate
    @patch.object(check_contact_whatsappable, 'delay')
    def test_check_org_whatsappable(self, mock_check):
        joe = self.create_contact("Joe Biden", "+254788383383")
        check_org_whatsappable(joe.org)
        mock_check.assert_called_with(joe.pk, self.new_style_channel.pk)

    @responses.activate
    @patch.object(check_contact_whatsappable, 'delay')
    def test_refresh_org_whatsappable(self, mock_check):
        joe = self.create_contact("Joe Biden", "+254788383383")

        has_whatsapp = has_whatsapp_contactfield(joe.org)
        has_whatsapp_timestamp = has_whatsapp_timestamp_contactfield(joe.org)

        joe.set_field(
            self.admin, key=has_whatsapp.key, value='yes')
        joe.set_field(
            self.admin, key=has_whatsapp_timestamp.key,
            value=(timezone.now() - timedelta(days=7)))
        refresh_org_whatsappable(joe.org, delta=timedelta(days=6))
        mock_check.assert_called_with(joe.pk, self.new_style_channel.pk)

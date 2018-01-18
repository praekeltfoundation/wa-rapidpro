import responses
import pkg_resources
import json
from django.test import override_settings
from mock import Mock, patch

from temba.tests import TembaTest

from temba.channels.models import Channel
from warapidpro.types import WhatsAppDirectType, WhatsAppGroupType

from temba.utils import dict_to_struct


class WhatsAppTypeTest(TembaTest):

    def test_api_request_headers(self):
        old_style_channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config=dict(api_token='api-token', secret='secret'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)
        new_style_channel = Channel.create(
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

        t = WhatsAppDirectType()
        self.assertEqual(
            t.api_request_headers(old_style_channel)['Authorization'],
            'Token api-token')
        self.assertEqual(
            t.api_request_headers(new_style_channel)['Authorization'],
            'Bearer foo')


class WhatsAppDirectTypeTest(TembaTest):
    """
    NOTE: Run these tests from the RapidPro repository / virtualenv
    """

    def setUp(self):
        super(WhatsAppDirectTypeTest, self).setUp()
        self.channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config=dict(api_token='api-token', secret='secret'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_activate(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = 'https://example.org/the/channel/'

        self.type = WhatsAppDirectType()
        self.type.channel_url = patch_channel_url

        self.calls = 0

        def cb(request):
            self.calls += 1
            data = json.loads(request.body)
            self.assertTrue(
                data['event'] in [
                    'message.direct_inbound',
                    'message.direct_outbound.status',
                ])
            self.assertEqual(data['url'], 'https://example.org/the/channel/')
            self.assertEqual(data['number'], '+27000000000')
            return (200, {}, json.dumps({
                'id': self.calls,
            }))

        responses.add_callback(
            responses.POST,
            'https://wassup.p16n.org/api/v1/webhooks/',
            callback=cb, content_type='application/json')

        self.type.activate(self.channel)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.config_json(), {
            'api_token': 'api-token',
            'secret': 'secret',
            'wassup_webhook_ids': [1, 2]
        })

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_deactivate(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = '/the/channel/'

        self.type = WhatsAppDirectType()
        self.type.channel_url = patch_channel_url

        responses.add(
            responses.DELETE,
            'https://wassup.p16n.org/api/v1/webhooks/1/',
            json={})
        responses.add(
            responses.DELETE,
            'https://wassup.p16n.org/api/v1/webhooks/2/',
            json={})

        self.channel.config = json.dumps({
            'api_token': 'api-token',
            'secret': 'secret',
            'wassup_webhook_ids': [1, 2],
        })
        self.channel.save()
        self.type.deactivate(self.channel)
        self.assertEqual(len(responses.calls), 2)

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_send(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = '/the/channel/'

        self.type = WhatsAppDirectType()

        responses.add(
            responses.POST,
            'https://wassup.p16n.org/api/v1/messages/',
            json={
                'uuid': 'the-uuid',
            })

        joe = self.create_contact("Joe Biden", "+254788383383")
        msg = joe.send("Hey Joe, it's Obama, pick up!", self.admin)[0]
        msg_struct = dict_to_struct(
            'MsgStruct', msg.as_task_json())
        channel_struct = dict_to_struct(
            'ChannelStruct', self.channel.as_cached_json())

        with patch('temba.channels.models.Channel.success') as patch_success:
            self.type.send(channel_struct, msg_struct, 'hello world')

        [(args, kwargs)] = patch_success.call_args_list
        self.assertEqual(args[0], channel_struct)
        self.assertEqual(args[1], msg_struct)
        self.assertEqual(kwargs['external_id'], 'the-uuid')

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_send_with_attachment(self):

        def cb(request):
            self.assertTrue('image_attachment' in request.body)
            return (
                201,
                {'Content-Type': 'application/json'},
                json.dumps({'uuid': 'the-uuid'}))

        responses.add_callback(
            responses.POST,
            'https://wassup.p16n.org/api/v1/messages/',
            callback=cb, content_type='application/json')

        fixture = pkg_resources.resource_filename(
            'warapidpro', 'tests/fixtures/placeholder-640x640.jpg')
        with open(fixture, 'rb') as fp:
            responses.add(responses.GET, 'https://example.com/pic.jpg',
                          body=fp.read(), content_type='image/jpg', status=200,
                          adding_headers={'Transfer-Encoding': 'chunked'})

        self.type = WhatsAppDirectType()

        joe = self.create_contact("Joe Biden", "+254788383383")
        msg = joe.send(
            "Hey Joe, it's Obama, pick up!", self.admin,
            attachments=['image/jpeg:https://example.com/pic.jpg'])[0]
        msg_struct = dict_to_struct(
            'MsgStruct', msg.as_task_json())
        channel_struct = dict_to_struct(
            'ChannelStruct', self.channel.as_cached_json())

        with patch('temba.channels.models.Channel.success') as patch_success:
            self.type.send(channel_struct, msg_struct, 'hello world')

        [(args, kwargs)] = patch_success.call_args_list
        self.assertEqual(args[0], channel_struct)
        self.assertEqual(args[1], msg_struct)
        self.assertEqual(kwargs['external_id'], 'the-uuid')


class WhatsAppGroupTypeTest(TembaTest):
    """
    NOTE: Run these tests from the RapidPro repository / virtualenv
    """

    def setUp(self):
        super(WhatsAppGroupTypeTest, self).setUp()
        self.channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppGroupType.code,
            None, '+27000000000',
            config=dict(api_token='api-token',
                        secret='secret',
                        group_uuid='group-uuid'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_activate(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = 'https://example.org/the/channel/'

        self.type = WhatsAppGroupType()
        self.type.channel_url = patch_channel_url

        self.calls = 0

        def cb(request):
            self.calls += 1
            data = json.loads(request.body)
            self.assertTrue(
                data['event'] in [
                    'message.group_inbound',
                    'message.group_outbound.status',
                ])
            self.assertEqual(data['url'], 'https://example.org/the/channel/')
            self.assertEqual(data['number'], '+27000000000')
            return (200, {}, json.dumps({
                'id': self.calls,
            }))

        responses.add_callback(
            responses.POST,
            'https://wassup.p16n.org/api/v1/webhooks/',
            callback=cb, content_type='application/json')

        self.type.activate(self.channel)
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.config_json(), {
            'api_token': 'api-token',
            'group_uuid': 'group-uuid',
            'secret': 'secret',
            'wassup_webhook_ids': [1, 2]
        })

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_deactivate(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = '/the/channel/'

        self.type = WhatsAppGroupType()
        self.type.channel_url = patch_channel_url

        responses.add(
            responses.DELETE,
            'https://wassup.p16n.org/api/v1/webhooks/1/',
            json={})
        responses.add(
            responses.DELETE,
            'https://wassup.p16n.org/api/v1/webhooks/2/',
            json={})

        self.channel.config = json.dumps({
            'api_token': 'api-token',
            'group_uuid': 'group-uuid',
            'secret': 'secret',
            'wassup_webhook_ids': [1, 2],
        })
        self.channel.save()
        self.type.deactivate(self.channel)
        self.assertEqual(len(responses.calls), 2)

    @responses.activate
    @override_settings(WASSUP_API_URL='https://wassup.p16n.org/api/v1')
    def test_send(self):
        patch_channel_url = Mock()
        patch_channel_url.return_value = '/the/channel/'

        self.type = WhatsAppGroupType()

        def cb(request):
            data = json.loads(request.body)
            self.assertEqual(data, {
                'to_addr': '+254788383383',
                'number': '+27000000000',
                'content': 'the text to send',
                'group': 'group-uuid',
                'in_reply_to': '',
            })
            return (201, {}, json.dumps({
                'uuid': 'the-uuid'
            }))

        responses.add_callback(
            responses.POST,
            'https://wassup.p16n.org/api/v1/messages/',
            callback=cb, content_type='application/json')

        joe = self.create_contact("Joe Biden", "+254788383383")
        msg = joe.send("Hey Joe, it's Obama, pick up!", self.admin)[0]
        msg_struct = dict_to_struct(
            'MsgStruct', msg.as_task_json())
        channel_struct = dict_to_struct(
            'ChannelStruct', self.channel.as_cached_json())
        text = 'the text to send'

        with patch('temba.channels.models.Channel.success') as patch_success:
            self.type.send(channel_struct, msg_struct, text)

        [(args, kwargs)] = patch_success.call_args_list
        self.assertEqual(args[0], channel_struct)
        self.assertEqual(args[1], msg_struct)
        self.assertEqual(kwargs['external_id'], 'the-uuid')

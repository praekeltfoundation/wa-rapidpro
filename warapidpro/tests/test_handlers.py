import pytest
import json
from django.test import RequestFactory

tests = pytest.importorskip('temba.tests')

org_models = pytest.importorskip('temba.orgs.models')
Org = org_models.Org

msg_models = pytest.importorskip('temba.msgs.models')
Msg = msg_models.Msg

channel_models = pytest.importorskip('temba.channels.models')
Channel = channel_models.Channel

handlers = pytest.importorskip("warapidpro.handlers")
WhatsAppHandler = handlers.WhatsAppHandler

types = pytest.importorskip("warapidpro.types")
WhatsAppDirectType = types.WhatsAppDirectType
WhatsAppGroupType = types.WhatsAppGroupType


class DirectHandlerTest(tests.TembaTest):

    def setUp(self):
        super(DirectHandlerTest, self).setUp()
        self.factory = RequestFactory()
        self.handler = WhatsAppHandler()
        self.channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppDirectType.code,
            None, '+27000000000',
            config=dict(api_token='api-token', secret='secret'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

    def test_message_direct_inbound(self):
        request = self.factory.post('/', data=json.dumps({
            'hook': {
                'event': 'message.direct_inbound'
            },
            'data': {
                'uuid': 'the-uuid',
                'from_addr': '+31000000000',
                'to_addr': '+27000000000',
                'content': 'hello world',
            }
        }), content_type='application/json')

        response = self.handler.dispatch(request, uuid=self.channel.uuid)
        message_id = json.loads(response.content)['message_id']
        msg = Msg.objects.get(pk=message_id)
        self.assertEqual(msg.text, 'hello world')
        self.assertEqual(msg.channel, self.channel)

    def test_message_direct_outbound_status(self):
        joe = self.create_contact("Joe Biden", "+254788383383")
        msg = joe.send("Hey Joe, it's Obama, pick up!", self.admin)[0]
        msg.external_id = 'the-uuid'
        msg.channel = self.channel
        msg.save(update_fields=('channel', 'external_id',))

        def assertStatus(sms, event_type, assert_status):
            request = self.factory.post('/', data=json.dumps({
                'hook': {
                    'event': 'message.direct_outbound.status'
                },
                'data': {
                    'message_uuid': 'the-uuid',
                    'status': event_type,
                }
            }), content_type='application/json')

            response = self.handler.dispatch(request, uuid=self.channel.uuid)
            self.assertEquals(201, response.status_code)
            sms = Msg.objects.get(pk=sms.id)
            self.assertEquals(assert_status, sms.status)

        assertStatus(msg, 'delivered', msg_models.DELIVERED)
        assertStatus(msg, 'failed', msg_models.FAILED)


class GroupHandlerTest(tests.TembaTest):

    def setUp(self):
        super(GroupHandlerTest, self).setUp()
        self.factory = RequestFactory()
        self.handler = WhatsAppHandler()
        self.channel = Channel.create(
            self.org, self.user, 'RW', WhatsAppGroupType.code,
            None, '+27000000000',
            config=dict(api_token='api-token',
                        secret='secret',
                        group_uuid='the-group-uuid'),
            uuid='00000000-0000-0000-0000-000000001234',
            role=Channel.DEFAULT_ROLE)

    def test_message_group_inbound(self):
        request = self.factory.post('/', data=json.dumps({
            'hook': {
                'event': 'message.group_inbound'
            },
            'data': {
                'uuid': 'the-uuid',
                'from_addr': '+31000000000',
                'to_addr': '+27000000000',
                'group': 'the-group-uuid',
                'content': 'hello world',
            }
        }), content_type='application/json')

        response = self.handler.dispatch(request, uuid=self.channel.uuid)
        message_id = json.loads(response.content)['message_id']
        msg = Msg.objects.get(pk=message_id)
        self.assertEqual(msg.text, 'hello world')
        self.assertEqual(msg.channel, self.channel)

    def test_message_group_inbound_other_group(self):
        request = self.factory.post('/', data=json.dumps({
            'hook': {
                'event': 'message.group_inbound'
            },
            'data': {
                'uuid': 'the-uuid',
                'from_addr': '+31000000000',
                'to_addr': '+27000000000',
                'group': 'another-groups-uuid',
                'content': 'hello world',
            }
        }), content_type='application/json')

        response = self.handler.dispatch(request, uuid=self.channel.uuid)
        self.assertEqual(response.content, '{}')

    def test_message_group_outbound_status(self):
        joe = self.create_contact("Joe Biden", "+254788383383")
        msg = joe.send("Hey Joe, it's Obama, pick up!", self.admin)[0]
        msg.external_id = 'the-uuid'
        msg.channel = self.channel
        msg.save(update_fields=('channel', 'external_id',))

        def assertStatus(sms, event_type, assert_status):
            request = self.factory.post('/', data=json.dumps({
                'hook': {
                    'event': 'message.direct_outbound.status'
                },
                'data': {
                    'message_uuid': 'the-uuid',
                    'status': event_type,
                }
            }), content_type='application/json')

            response = self.handler.dispatch(request, uuid=self.channel.uuid)
            self.assertEquals(201, response.status_code)
            sms = Msg.objects.get(pk=sms.id)
            self.assertEquals(assert_status, sms.status)

        assertStatus(msg, 'delivered', msg_models.DELIVERED)
        assertStatus(msg, 'failed', msg_models.FAILED)

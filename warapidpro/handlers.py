import json
import logging

from temba.channels.handlers import BaseChannelHandler
from temba.channels.models import Channel, ChannelLog
from temba.contacts.models import URN
from temba.msgs.models import Msg, OUTGOING
from temba.utils.http import HttpEvent

from django.http import HttpResponse, JsonResponse

logger = logging.getLogger(__name__)


class WhatsAppHandler(BaseChannelHandler):

    url = r'^whatsapp/(?P<uuid>[a-z0-9\-]+)/?$'
    url_name = 'handlers.whatsapp_handler'

    def lookup_channel(self, channel_type, uuid):
        # look up the channel
        channel = Channel.objects.filter(
            uuid=uuid, is_active=True,
            channel_type=channel_type).exclude(org=None).first()
        return channel

    def post(self, request, *args, **kwargs):
        uuid = kwargs['uuid']
        # parse our response
        try:
            body = json.loads(request.body)
        except Exception as e:  # pragma: needs cover
            logger.error(e)
            return HttpResponse(
                "Invalid JSON in POST body: %s" % str(e), status=400)

        handler = {
            'message.direct_inbound': self.handle_direct_inbound,
            'message.group_inbound': self.handle_group_inbound,
            'message.direct_outbound.status': (
                self.handle_outbound_status),
            'message.group_outbound.status': (
                self.handle_outbound_status),
        }.get(body.get('hook', {}).get('event'), self.noop)
        return handler(request, uuid, body.get('data', {}))

    def get_attachments(self, data):
        attachments = []
        if data.get('image_attachment'):
            attachments.append('%s:%s' % (
                Msg.MEDIA_IMAGE, data.get('image_attachment')))
        if data.get('audio_attachment'):
            attachments.append('%s:%s' % (
                Msg.MEDIA_AUDIO, data.get('audio_attachment')))
        if data.get('video_attachment'):
            attachments.append('%s:%s' % (
                Msg.MEDIA_VIDEO, data.get('video_attachment')))
        if data.get('document_attachment'):
            logger.warning(
                'Received document but RapidPro is not able to handle it.')
        if data.get('location'):
            attachments.append('%s:%s,%s' % (
                Msg.MEDIA_GPS,
                data['location']['coordinates'][1],
                data['location']['coordinates'][0]))

        return attachments

    def get_content(self, data):
        # RP doesn't allow None for content fields
        return (
            data.get('content') or
            data.get('image_attachment_caption') or
            data.get('document_attachment_caption') or
            '')

    def handle_direct_inbound(self, request, uuid, data):
        from warapidpro.types import WhatsAppDirectType
        channel = self.lookup_channel(WhatsAppDirectType.code, uuid)
        if not channel:
            error_msg = "Channel not found for id: %s" % (uuid,)
            logger.error(error_msg)
            return HttpResponse(error_msg, status=400)

        from_addr = data['from_addr']
        content = self.get_content(data)
        attachments = self.get_attachments(data)

        message = Msg.create_incoming(
            channel, URN.from_tel(from_addr), content,
            external_id=data['uuid'], attachments=attachments)
        response_body = {
            'message_id': message.pk,
        }

        request_body = request.body
        request_method = request.method
        request_path = request.get_full_path()

        event = HttpEvent(
            request_method, request_path, request_body, 201,
            json.dumps(response_body))
        ChannelLog.log_message(message, 'Handled inbound message.', event)
        return JsonResponse(response_body, status=201)

    def handle_group_inbound(self, request, uuid, data):
        from warapidpro.types import WhatsAppGroupType
        channel = self.lookup_channel(WhatsAppGroupType.code, uuid)
        if not channel:
            error_msg = "Channel not found for id: %s" % (uuid,)
            logger.error(error_msg)
            return HttpResponse(error_msg, status=400)

        from_addr = data['from_addr']
        content = self.get_content(data)
        attachments = self.get_attachments(data)
        group_uuid = data.get('group', {}).get('uuid')

        # The group webhook receives messages for all groups,
        # only grab the message if it's a group we're a channel for.
        if channel.config_json()['group_uuid'] != group_uuid:
            logger.info('Received message for a different group.')
            return JsonResponse({}, status=200)

        message = Msg.create_incoming(
            channel, URN.from_tel(from_addr), content,
            external_id=data['uuid'], attachments=attachments)

        response_body = {
            'message_id': message.pk,
        }

        request_body = request.body
        request_method = request.method
        request_path = request.get_full_path()

        event = HttpEvent(
            request_method, request_path, request_body, 201,
            json.dumps(response_body))
        ChannelLog.log_message(message, 'Handled inbound message.', event)
        return JsonResponse(response_body, status=201)

    def handle_outbound_status(self, request, uuid, data):
        from warapidpro.types import (
            WhatsAppDirectType, WhatsAppGroupType)

        channel = Channel.objects.filter(
            uuid=uuid, is_active=True,
            channel_type__in=[
                WhatsAppDirectType.code, WhatsAppGroupType.code
            ]).exclude(org=None).first()

        if not channel:
            error_msg = "Channel not found for id: %s" % (uuid,)
            logger.error(error_msg)
            return HttpResponse(error_msg, status=400)

        message_id = data['message_uuid']
        event_type = data['status']

        message = Msg.objects.filter(
            channel=channel,
            external_id=message_id,
            direction=OUTGOING).select_related('channel')

        if not message.exists():
            # NOTE: We receive events for all outbounds, so likely this
            #       was an event for something we didn't send
            return JsonResponse({}, status=200)

        if event_type == 'delivered':
            for message_obj in message:
                message_obj.status_delivered()
        elif event_type == 'failed':
            for message_obj in message:
                message_obj.status_fail()

        response_body = {
            'message_ids': [message_obj.pk for message_obj in message]
        }
        return JsonResponse(response_body, status=201)

    def noop(self, request, uuid, data):
        return JsonResponse(dict(status=["Ignored, unknown msg"]))

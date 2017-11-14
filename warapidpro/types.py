import logging
import requests
import json
import time
import os.path
import six
from io import BytesIO

from temba.channels.models import (
    Channel, ChannelType, TEMBA_HEADERS, SendException)
from temba.msgs.models import WIRED, Msg, Attachment
from temba.contacts.models import TEL_SCHEME
from temba.utils.http import HttpEvent
from django.shortcuts import reverse
from django.conf import settings

from .views import DirectClaimView, GroupClaimView

logger = logging.getLogger(__name__)


class WhatsAppType(ChannelType):
    category = ChannelType.Category.SOCIAL_MEDIA
    scheme = TEL_SCHEME
    max_length = 1600
    max_tps = None
    attachment_support = True
    free_sending = True

    def channel_url(self, channel):
        return 'https://%s%s' % (
            settings.HOSTNAME,
            reverse('handlers.whatsapp_handler', args=(channel.uuid,)))

    def wassup_url(self):
        return getattr(
            settings, 'WASSUP_API_URL', 'https://wassup.p16n.org/api/v1')

    def add_channel_webhook(self, channel, event):
        response = requests.post(
            '%s/webhooks/' % (self.wassup_url(),),
            json={
                'event': event,
                'url': self.channel_url(channel),
                'number': channel.address,
                'secret': channel.secret,
            },
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': 'Token %s' % (
                    channel.config_json()['api_token'],),
            })
        response.raise_for_status()
        data = response.json()
        return data['id']

    def remove_channel_webhook(self, channel, webhook_id):
        response = requests.delete(
            '%s/webhooks/%s/' % (self.wassup_url(), webhook_id,),
            headers={
                'Authorization': 'Token %s' % (
                    channel.config_json()['api_token'],),
            })
        response.raise_for_status()

    def remove_channel_webhooks(self, channel):
        for webhook_id in channel.config_json().get('wassup_webhook_ids', []):
            self.remove_channel_webhook(channel, webhook_id)

    def fetch_attachment(self, attachment):
        """
        NOTE:   this isn't using the streaming API that requests
                has because I'm failing to write a test for it
                If memory usage is going through the roof,
                look here.
        """
        category = attachment.content_type.split('/')[0]
        attachment_type = {
            'audio': 'audio_attachment',
            'image': 'image_attachment',
            'video': 'video_attachment',
            'application': 'document_attachment',
        }.get(category)
        if not attachment_type:
            logger.warning(
                'Trying to send unsupported attachment type: %s' % (
                    category,))
            return {}

        response = requests.get(attachment.url, stream=True)
        response.raise_for_status()
        return {
            attachment_type: (
                os.path.basename(attachment.url),
                BytesIO(response.content),
                attachment.content_type),
        }

    def send_whatsapp(self, channel_struct, msg, payload, attachments=None):
        url = ('%s/messages/' % (self.wassup_url(),))
        headers = TEMBA_HEADERS.copy()
        headers.update({
            'Accept': 'application/json',
            'Authorization': 'Token %s' % (
                channel_struct.config['api_token'],),
        })
        event = HttpEvent('POST', url, json.dumps(payload))
        start = time.time()

        # Grab the first attachment if it exists
        attachments = Attachment.parse_all(msg.attachments)
        attachment = attachments[0] if attachments else None

        try:
            if attachment:
                files = self.fetch_attachment(attachment)
                data = payload
            else:
                headers.update({
                    'Content-Type': 'application/json'
                })
                data = json.dumps(payload)
                files = {}

            response = requests.post(
                url, data=data, files=files, headers=headers)
            response.raise_for_status()
            event.status_code = response.status_code
            event.response_body = response.text
        except (requests.RequestException,) as e:
            raise SendException(
                'error: %s, request: %s, response: %s' % (
                    six.text_type(e), e.request.data, e.response.content),
                event=event, start=start)

        data = response.json()
        try:
            message_id = data['uuid']
            Channel.success(channel_struct, msg, WIRED, start,
                            event=event, external_id=message_id)
        except (KeyError,) as e:
            raise SendException(
                "Unable to read external message_id: %r" % (e,),
                event=HttpEvent('POST', url,
                                request_body=json.dumps(json.dumps(payload)),
                                response_body=json.dumps(data)),
                start=start)


class WhatsAppDirectType(WhatsAppType):

    claim_blurb = 'Claim your direct WhatsApp Channel'
    claim_view = DirectClaimView
    code = 'WAD'
    slug = 'wad'
    name = 'WhatsApp Direct'

    def activate(self, channel_struct):
        channel = Channel.objects.get(id=channel_struct.id)
        logger.info('Activating channel %s' % (channel,))
        dm_id = self.add_channel_webhook(
            channel, 'message.direct_inbound')
        status_id = self.add_channel_webhook(
            channel, 'message.direct_outbound.status')
        config = channel.config_json()
        config.update({
            'wassup_webhook_ids': [dm_id, status_id]
        })
        channel.config = json.dumps(config)
        channel.save(update_fields=['config'])

    def deactivate(self, channel_struct):
        channel = Channel.objects.get(id=channel_struct.id)
        logger.info('Deactivating channel %s' % (channel,))
        self.remove_channel_webhooks(channel)

    def activate_trigger(self, trigger):
        logger.info('Activating trigger %s' % (trigger,))

    def deactivate_trigger(self, trigger):
        logger.info('Deactivating trigger %s' % (trigger,))

    def send(self, channel_struct, msg, text):
        logger.info(
            'Sending message %s to channel %s, text: %s' % (
                msg, channel_struct, text))
        self.send_whatsapp(channel_struct, msg, {
            'to_addr': msg.urn_path,
            'number': channel_struct.address,
            'group': '',
            'in_reply_to': (
                Msg.objects.values_list(
                    'external_id', flat=True).filter(
                        pk=msg.response_to_id).first()) or '',
            'content': text,
        })


class WhatsAppGroupType(WhatsAppType):

    claim_blurb = 'Claim your WhatsApp Group Channel'
    claim_view = GroupClaimView
    code = 'WAG'
    slug = 'wag'
    name = 'WhatsApp Group'

    def activate(self, channel_struct):
        channel = Channel.objects.get(id=channel_struct.id)
        logger.info('Activating channel %s' % (channel,))
        dm_id = self.add_channel_webhook(
            channel, 'message.group_inbound')
        status_id = self.add_channel_webhook(
            channel, 'message.group_outbound.status')
        config = channel.config_json()
        config.update({
            'wassup_webhook_ids': [dm_id, status_id]
        })
        channel.config = json.dumps(config)
        channel.save(update_fields=['config'])

    def deactivate(self, channel_struct):
        channel = Channel.objects.get(id=channel_struct.id)
        logger.info('Deactivating channel %s' % (channel,))
        self.remove_channel_webhooks(channel)

    def activate_trigger(self, trigger):
        logger.info('Activating trigger %s' % (trigger,))

    def deactivate_trigger(self, trigger):
        logger.info('Deactivating trigger %s' % (trigger,))

    def send(self, channel_struct, msg, text):
        logger.info(
            'Sending message %s to channel %s, text: %s' % (
                msg, channel_struct, text))
        self.send_whatsapp(channel_struct, msg, {
            'to_addr': msg.urn_path,
            'number': channel_struct.address,
            'group': channel_struct.config.get('group_uuid'),
            'in_reply_to': (
                Msg.objects.values_list(
                    'external_id', flat=True).filter(
                        pk=msg.response_to_id).first()) or '',
            'content': text,
        })

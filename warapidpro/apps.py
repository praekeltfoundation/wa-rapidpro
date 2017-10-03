from __future__ import absolute_import

from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class IntegrationConfig(AppConfig):
    name = 'warapidpro'
    # NOTE: This is to maintain backwards compatibility with
    #       existing installations this was extracted from
    label = 'integration'
    verbose_name = "WhatsApp RapidPro integration"

    def ready(self):
        from temba.channels import types
        from .types import WhatsAppDirectType, WhatsAppGroupType
        from .handlers import WhatsAppHandler

        # NOTE: Loading WhatsAppHandler so when RapidPro
        # looks for ChannelHandler implementations it will
        # load this one into the urlpatterns too
        WhatsAppHandler

        types.register_channel_type(WhatsAppDirectType)
        types.register_channel_type(WhatsAppGroupType)

        logger.info('Registered the WhatsApp Channel')

import requests
import json
import pkg_resources
from datetime import datetime, timedelta
from temba import celery_app
from dateutil import parser
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from warapidpro.types import (
    WhatsAppDirectType, WhatsAppGroupType, WHATSAPP_CHANNEL_TYPES)
from warapidpro.views import DEFAULT_AUTH_URL


session = requests.Session()
distribution = pkg_resources.get_distribution('warapidpro')


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

    response = session.post(
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


@celery_app.task
def update_whatsappable_contacts(sample_size=100):
    from temba.orgs.models import Org

    orgs_with_whatsapp = Org.objects.filter(
        channels__channel_type__in=WHATSAPP_CHANNEL_TYPES).distinct('id')
    for org in orgs_with_whatsapp:
        check_org_whatsappable(org.pk, sample_size=sample_size)
        refresh_org_whatsappable(org.pk, sample_size=sample_size)


@celery_app.task
def check_org_whatsappable(org_pk, sample_size=100):
    from warapidpro.models import (
        has_whatsapp_contactfield, has_whatsapp_timestamp_contactfield)
    from temba.contacts.models import Contact
    from temba.orgs.models import Org

    org = Org.objects.get(pk=org_pk)

    channels = org.channels.filter(
        channel_type__in=WHATSAPP_CHANNEL_TYPES, is_active=True)
    if not channels.exists():
        return

    channel = channels.order_by('-modified_on').first()

    has_whatsapp = has_whatsapp_contactfield(org)
    has_whatsapp_timestamp = has_whatsapp_timestamp_contactfield(org)

    # Django's ORM only way of modelling this query is by using
    # .exclude() which introduces a massive subquery which is extremely
    # inefficient.
    new_contacts = Contact.objects.raw("""
        SELECT "contacts_contact".*
        FROM "contacts_contact"
        LEFT JOIN "values_value"
            ON "contacts_contact"."id" = "values_value"."contact_id"
        WHERE "contacts_contact"."org_id" = %s
        AND (("values_value"."contact_field_id" != %s
                AND "values_value"."contact_field_id" != %s)
                OR "values_value"."contact_field_id" IS NULL)
        ORDER BY RANDOM() ASC
        LIMIT %s
        """, [org.pk, has_whatsapp.pk, has_whatsapp_timestamp.pk, sample_size])

    check_contact_whatsappable.delay(
        [contact.pk for contact in new_contacts], channel.pk)


@celery_app.task
def refresh_org_whatsappable(org_pk, sample_size=100, delta=timedelta(days=7)):
    from warapidpro.models import (
        has_whatsapp_contactfield, has_whatsapp_timestamp_contactfield)
    from temba.contacts.models import Contact
    from temba.orgs.models import Org

    org = Org.objects.get(pk=org_pk)

    channels = org.channels.filter(
        channel_type__in=WHATSAPP_CHANNEL_TYPES, is_active=True)
    if not channels.exists():
        return

    channel = channels.order_by('-modified_on').first()

    has_whatsapp = has_whatsapp_contactfield(org)
    has_whatsapp_timestamp = has_whatsapp_timestamp_contactfield(org)

    checked_before = Contact.objects.filter(
        org=org, values__contact_field=has_whatsapp)

    needing_refreshing = checked_before.filter(
        values__contact_field=has_whatsapp_timestamp,
        values__datetime_value__lte=timezone.now() - delta)

    selected_for_refreshing = needing_refreshing.order_by('?')[:sample_size]

    check_contact_whatsappable.delay(
        [contact.pk for contact in selected_for_refreshing], channel.pk)


@celery_app.task
def check_contact_whatsappable(contact_pks, channel_pk):
    from warapidpro.models import (
        has_whatsapp_contactfield, has_whatsapp_timestamp_contactfield,
        get_whatsappable_group, YES, NO)
    from temba.contacts.models import Contact, TEL_SCHEME
    from temba.channels.models import Channel

    channel = Channel.objects.get(pk=channel_pk)
    org = channel.org
    has_whatsapp = has_whatsapp_contactfield(org)
    has_whatsapp_timestamp = has_whatsapp_timestamp_contactfield(org)
    # Make sure the group exists
    get_whatsappable_group(org)

    contacts = Contact.objects.filter(pk__in=contact_pks)
    contacts_and_urns = [
        (contact.get_urn(TEL_SCHEME), contact) for contact in contacts]
    contacts_and_msisdns = dict(
        [(urn.path, contact)
         for urn, contact in contacts_and_urns
         if urn is not None])

    config = channel.config_json()
    authorization = config.get('authorization', {})
    token = authorization.get('access_token') or config.get('api_token')

    wassup_url = getattr(
        settings, 'WASSUP_AUTH_URL', DEFAULT_AUTH_URL)

    response = session.post(
        '%s/api/v1/lookups/' % (wassup_url,),
        data=json.dumps({
            "number": channel.address,
            "msisdns": [urn for urn in contacts_and_msisdns],
            "wait": True,
        }),
        headers={
            'Authorization': '%s %s' % (
                authorization.get('token_type', 'Token'), token,),
            'Content-Type': 'application/json',
            'User-Agent': 'warapidpro/%s (%s, %s)' % (
                distribution.version, channel.org.name, settings.HOSTNAME)
        })

    response.raise_for_status()

    for record in response.json():
        msisdn = record['msisdn']
        wa_exists = record['wa_exists']

        contact = contacts_and_msisdns.get(msisdn)
        has_whatsapp_value = YES if wa_exists is True else NO

        contact.set_field(
            user=org.administrators.first(),
            key=has_whatsapp.key, value=has_whatsapp_value)
        contact.set_field(
            user=org.administrators.first(),
            key=has_whatsapp_timestamp.key, value=timezone.now())

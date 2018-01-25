from temba.contacts.models import ContactField, ContactGroup
from temba.values.models import Value

WHATSAPPABLE_GROUP = 'Contacts on WhatsApp'
HAS_WHATSAPP_KEY = 'has_whatsapp'
YES = 'yes'
NO = 'no'
HAS_WHATSAPP_TIMESTAMP_KEY = 'has_whatsapp_timestamp'


def has_whatsapp_contactfield(org):
    return ContactField.get_or_create(
        org, user=org.administrators.first(),
        key=HAS_WHATSAPP_KEY, value_type=Value.TYPE_TEXT)


def has_whatsapp_timestamp_contactfield(org):
    return ContactField.get_or_create(
        org, user=org.administrators.first(),
        key=HAS_WHATSAPP_TIMESTAMP_KEY, value_type=Value.TYPE_DATETIME)


def get_whatsappable_group(org):
    user = org.administrators.first()
    whatsapp_groups = ContactGroup.user_groups.filter(
        org=org, name=WHATSAPPABLE_GROUP)
    if whatsapp_groups.exists():
        return ContactGroup.get_or_create(
            org, user=user, name=WHATSAPPABLE_GROUP)

    return ContactGroup.create_dynamic(
        org, user=user, name=WHATSAPPABLE_GROUP,
        query='%s="%s"' % (HAS_WHATSAPP_KEY, YES))

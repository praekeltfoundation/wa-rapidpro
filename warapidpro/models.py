from temba.contacts.models import ContactField
from temba.values.models import Value


def has_whatsapp_contactfield(org):
    return ContactField.get_or_create(
        org, user=org.administrators.first(),
        key='has_whatsapp', value_type=Value.TYPE_TEXT)


def has_whatsapp_timestamp_contactfield(org):
    return ContactField.get_or_create(
        org, user=org.administrators.first(),
        key='has_whatsapp_timestamp', value_type=Value.TYPE_DATETIME)

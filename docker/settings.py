from temba.settings_original import *  # noqa
from datetime import timedelta
from getenv import env

# schedule the access token refresh check to happen every
# minute
CELERYBEAT_SCHEDULE.update({
    'refresh-wassup-oauth-access-tokens': {
        'task': 'warapidpro.tasks.refresh_channel_auth_tokens',
        'schedule': timedelta(seconds=60),
    },
    'update-whatsappable-contacts': {
        'task': 'warapidpro.tasks.update_whatsappable_contacts',
        'kwargs': {
            'sample_size': 500,
        },
        'schedule': timedelta(minutes=5)
    },
})

WASSUP_AUTH_URL = env('WASSUP_AUTH_URL', 'https://wassup.p16n.org')
WASSUP_AUTH_CLIENT_ID = env('WASSUP_AUTH_CLIENT_ID')
WASSUP_AUTH_CLIENT_SECRET = env('WASSUP_AUTH_CLIENT_SECRET')

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'temba.api.support.APITokenAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': (
        'temba.api.support.OrgRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'v2': '250000/hour',
        'v2.contacts': '250000/hour',
        'v2.messages': '250000/hour',
        'v2.runs': '250000/hour',
        'v2.api': '250000/hour',
    },
    'PAGE_SIZE': 250,
    'DEFAULT_RENDERER_CLASSES': (
        'temba.api.support.DocumentationRenderer',
        'rest_framework.renderers.JSONRenderer'
    ),
    'EXCEPTION_HANDLER': 'temba.api.support.temba_exception_handler',
    'UNICODE_JSON': False
}

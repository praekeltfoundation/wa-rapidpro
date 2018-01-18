import requests
import urllib
import logging

from datetime import datetime, timedelta
from uuid import uuid4
from django import forms
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from smartmin.views import SmartFormView

from temba.channels.views import ClaimViewMixin
from temba.channels.models import Channel


DEFAULT_STATE_KEY = 'wassup_auth_state'
DEFAULT_AUTHORIZATION_KEY = 'wassup_authorizations'
DEFAULT_AUTH_URL = 'https://wassup.p16n.org'
DEFAULT_SCOPES = " ".join([
    "numbers:read",
    "messages:read",
    "messages:write",
    "websocket:read",
    "profile:read",
])

logger = logging.getLogger(__name__)


class NumberForm(ClaimViewMixin.Form):

    number = forms.ChoiceField(
        required=True,
        help_text=_('Which number would you like to connect?'))


class GroupForm(ClaimViewMixin.Form):

    group = forms.ChoiceField(
        required=True,
        help_text=_('Which group would you like to connect?'))


class WhatsAppClaimView(ClaimViewMixin, SmartFormView):

    def pre_process(self, *args, **kwargs):
        response = super(WhatsAppClaimView, self).pre_process(
            *args, **kwargs)

        code = self.request.GET.get('code')
        state = self.request.GET.get('state')
        session_state = self.request.session.get(DEFAULT_STATE_KEY)
        if all([code, state]) and state == session_state:
            self.set_session_authorization(
                self.get_authorization(code))
            del self.request.session[DEFAULT_STATE_KEY]
            return redirect(
                reverse('channels.claim_%s' % (
                    self.channel_type.slug,)))

        return response

    def set_session_authorization(self, authorization):
        self.request.session[DEFAULT_AUTHORIZATION_KEY] = authorization

    def get_session_authorization(self):
        return self.request.session.get(
            DEFAULT_AUTHORIZATION_KEY, {})

    def clear_session_authorization(self):
        del self.request.session[DEFAULT_AUTHORIZATION_KEY]

    def get_authorization(self, code):
        wassup_url = getattr(
            settings, 'WASSUP_AUTH_URL', DEFAULT_AUTH_URL)
        client_id = getattr(
            settings, 'WASSUP_AUTH_CLIENT_ID', None)
        client_secret = getattr(
            settings, 'WASSUP_AUTH_CLIENT_SECRET', None)

        redirect_uri = self.get_redirect_uri()

        response = requests.post(
            '%s/oauth/token/' % (wassup_url,), {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            })
        response.raise_for_status()
        return response.json()

    def get_redirect_uri(self):
        return self.request.build_absolute_uri(
            reverse('channels.claim_%s' % (self.channel_type.slug,)))

    def get_context_data(self, **kwargs):
        context = super(WhatsAppClaimView, self).get_context_data(
            **kwargs)

        wassup_url = getattr(
            settings, 'WASSUP_AUTH_URL', DEFAULT_AUTH_URL)
        client_id = getattr(
            settings, 'WASSUP_AUTH_CLIENT_ID', None)
        auth_scopes = getattr(
            settings, 'WASSUP_AUTH_SCOPES', DEFAULT_SCOPES
        )

        auth_state = uuid4().hex[:8]
        self.request.session[DEFAULT_STATE_KEY] = auth_state

        auth_url = '%s/oauth/authorize/?%s' % (
            wassup_url,
            urllib.urlencode({
                "client_id": client_id,
                "redirect_uri": self.get_redirect_uri(),
                "scopes": auth_scopes,
                "response_type": "code",
                "state": auth_state,
            }))

        context['whatsapp_auth_url'] = auth_url

        # if we've not authorized yet, remove the form
        authorization = self.get_session_authorization()
        context['authorization'] = authorization
        if authorization.get('access_token') is not None:
            context['show_form'] = True
        else:
            context['show_form'] = False
        return context

    def wassup_url(self):
        return getattr(
            settings, 'WASSUP_API_URL', '%s/api/v1' % (DEFAULT_AUTH_URL,))

    def get_numbers(self, api_token):
        response = requests.get(
            '%s/numbers/' % (self.wassup_url(),),
            headers={
                'Authorization': 'Bearer %s' % (api_token),
                'Accept': 'application/json',
            })
        response.raise_for_status()
        data = response.json()
        return data['results']

    def get_number_choices(self, api_token):
        return [(
            '%(from_addr)s' % number,
            '%(vname)s (%(from_addr)s)' % number,
        ) for number in self.get_numbers(api_token)]

    def get_groups(self, api_token):
        response = requests.get(
            '%s/groups/' % (self.wassup_url(),),
            headers={
                'Authorization': 'Bearer %s' % (api_token),
                'Accept': 'application/json',
            })
        response.raise_for_status()
        data = response.json()
        return data['results']

    def get_group_choices(self, api_token):
        return [(group['uuid'], '%(subject)s for %(number)s' % group)
                for group in self.get_groups(api_token)]


class DirectClaimView(WhatsAppClaimView):

    def get_form_class(self, *args, **kwargs):
        return NumberForm

    # NOTE: this is a SmartMin callback
    def customize_form_field(self, name, field):
        authorization = self.request.session.get(DEFAULT_AUTHORIZATION_KEY)
        if authorization and name == 'number':
            field.choices = self.get_number_choices(
                authorization['access_token'])
        return field

    def form_valid(self, form):
        org = self.request.user.get_org()
        number = form.cleaned_data['number']
        authorization = self.get_session_authorization()

        config = {
            'authorization': authorization,
            'expires_at': (
                datetime.now() + timedelta(
                    seconds=authorization['expires_in'])).isoformat(),
            'number': number,
        }

        self.object = Channel.create(
            org, self.request.user, None, self.channel_type,
            name='Direct Messages to %s' % (number,),
            address=number, config=config,
            secret=Channel.generate_secret())

        self.clear_session_authorization
        return super(WhatsAppClaimView, self).form_valid(form)


class GroupClaimView(WhatsAppClaimView):

    def get_form_class(self, *args, **kwargs):
        return GroupForm

    # NOTE: this is a SmartMin callback
    def customize_form_field(self, name, field):
        authorization = self.request.session.get(DEFAULT_AUTHORIZATION_KEY)
        if authorization and name == 'group':
            field.choices = self.get_group_choices(
                authorization['access_token'])
        return field

    def form_valid(self, form):
        org = self.request.user.get_org()
        authorization = self.get_session_authorization()
        access_token = authorization['access_token']

        group_uuid = form.cleaned_data['group']
        [group] = [group
                   for group in self.get_groups(access_token)
                   if group['uuid'] == group_uuid]

        config = {
            'authorization': authorization,
            'expires_at': (
                (datetime.now() + timedelta(
                    seconds=authorization['expires_in']))).isoformat(),
            'group': group,
        }

        self.object = Channel.create(
            org, self.request.user, None, self.channel_type,
            name='group messages to %(subject)s on %(number)s' % group,
            address=group['number'], config=config,
            secret=Channel.generate_secret())

        self.clear_session_authorization()
        return super(WhatsAppClaimView, self).form_valid(form)

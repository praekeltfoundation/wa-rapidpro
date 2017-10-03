import requests
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

from smartmin.views import SmartFormView

from temba.channels.views import ClaimViewMixin
from temba.channels.models import Channel


class TokenForm(ClaimViewMixin.Form):
    api_token = forms.CharField(
        max_length=150, required=True,
        help_text=_("The API Token for WhatsApp integration"))

    def wassup_url(self):
        return getattr(
            settings, 'WASSUP_API_URL', 'https://wassup.p16n.org/api/v1')

    def clean_api_token(self):
        value = self.cleaned_data['api_token']

        response = requests.get(
            '%s/numbers/' % (self.wassup_url(),),
            headers={
                'Authorization': 'Token %s' % (value,)
            })
        if response.status_code != 200:
            raise ValidationError(
                _("Invalid API Token, please check it and try again."))
        return value


class NumberForm(ClaimViewMixin.Form):

    api_token = forms.CharField(required=True)
    number = forms.ChoiceField(
        required=True,
        help_text=_('Which number would you like to connect?'))

    def __init__(self, *args, **kwargs):
        super(NumberForm, self).__init__(*args, **kwargs)
        self.fields['api_token'].widget.attrs['readonly'] = True


class GroupForm(ClaimViewMixin.Form):

    api_token = forms.CharField(required=True)
    group = forms.ChoiceField(
        required=True,
        help_text=_('Which group would you like to connect?'))

    def __init__(self, *args, **kwargs):
        super(GroupForm, self).__init__(*args, **kwargs)
        self.fields['api_token'].widget.attrs['readonly'] = True


class WhatsAppClaimView(ClaimViewMixin, SmartFormView):

    # Subclasses should specify this
    claim_form_class = None

    def wassup_url(self):
        return getattr(
            settings, 'WASSUP_API_URL', 'https://wassup.p16n.org/api/v1')

    def get_numbers(self, api_token):
        response = requests.get(
            '%s/numbers/' % (self.wassup_url(),),
            headers={
                'Authorization': 'Token %s' % (api_token),
                'Accept': 'application/json',
            })
        response.raise_for_status()
        data = response.json()
        return data['results']

    def get_number_choices(self, api_token):
        return [(
            '+%(country_code)s%(number)s' % number,
            '+%(country_code)s%(number)s' % number,
        ) for number in self.get_numbers(api_token)]

    def get_groups(self, api_token):
        response = requests.get(
            '%s/groups/' % (self.wassup_url(),),
            headers={
                'Authorization': 'Token %s' % (api_token),
                'Accept': 'application/json',
            })
        response.raise_for_status()
        data = response.json()
        return data['results']

    def get_group_choices(self, api_token):
        return [(group['uuid'], '%(subject)s for %(number)s' % group)
                for group in self.get_groups(api_token)]

    def get_form_class(self):
        if 'api_token' in self.request.POST and self.request.method == 'POST':
            form_kwargs = self.get_form_kwargs()
            form = TokenForm(**form_kwargs)
            if form.is_valid():
                api_token = form.cleaned_data['api_token']
                form_kwargs = self.get_form_kwargs()
                form_kwargs.setdefault('initial', {}).update({
                    'api_token': api_token,
                })
                return self.claim_form_class

        return TokenForm

    def get_form_kwargs(self):
        kwargs = super(WhatsAppClaimView, self).get_form_kwargs()
        if 'api_token' in self.request.POST:
            kwargs.update({
                'initial': {
                    'api_token': self.request.POST['api_token'],
                }
            })
        return kwargs


class DirectClaimView(WhatsAppClaimView):

    claim_form_class = NumberForm

    # NOTE: this is a SmartMin callback
    def customize_form_field(self, name, field):
        if name == 'number':
            api_token = self.request.POST['api_token']
            field.choices = self.get_number_choices(api_token)
        return field

    def form_valid(self, form):
        org = self.request.user.get_org()
        api_token = form.cleaned_data['api_token']
        number = form.cleaned_data['number']

        config = {
            'api_token': api_token,
            'number': number,
        }

        self.object = Channel.create(
            org, self.request.user, None, self.channel_type,
            name='direct messages to %s' % (number,),
            address=number, config=config,
            secret=Channel.generate_secret())

        return super(DirectClaimView, self).form_valid(form)


class GroupClaimView(WhatsAppClaimView):

    claim_form_class = GroupForm

    # NOTE: this is a SmartMin callback
    def customize_form_field(self, name, field):
        if name == 'group':
            api_token = self.request.POST['api_token']
            field.choices = self.get_group_choices(api_token)
        return field

    def form_valid(self, form):
        org = self.request.user.get_org()
        api_token = form.cleaned_data['api_token']
        group_uuid = form.cleaned_data['group']

        [group] = [group
                   for group in self.get_groups(api_token)
                   if group['uuid'] == group_uuid]

        config = {
            'api_token': api_token,
            'group_uuid': group_uuid,
        }

        self.object = Channel.create(
            org, self.request.user, None, self.channel_type,
            name='group messages to %(subject)s on %(number)s' % group,
            address=group['number'], config=config,
            secret=Channel.generate_secret())

        return super(GroupClaimView, self).form_valid(form)

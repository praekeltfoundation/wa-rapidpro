from django.conf.urls import url
from django.views.generic.base import RedirectView

from temba import urls


urlpatterns = [
    url(r'^foos/$', RedirectView.as_view(url='https://www.google.com')),
    # url('', include('temba.urls')),
] + urls.urlpatterns

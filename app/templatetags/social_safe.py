from django import template
from allauth.socialaccount.templatetags.socialaccount import provider_login_url

register = template.Library()


@register.simple_tag(takes_context=True)
def provider_login_url_safe(context, provider, **params):
    """
    allauth `provider_login_url` tag, Google ilovasi (SocialApp)
    bazada yoki sozlamalarda kiritilmagan bo‘lsa ham sahifani
    qulatmaydi — o‘rniga oddiy '#' havolasini qaytaradi.
    """
    try:
        return provider_login_url(context, provider, **params)
    except Exception:
        return '#'

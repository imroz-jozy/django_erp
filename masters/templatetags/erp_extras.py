from django import template

from ..reports import _voucher_admin_url

register = template.Library()


@register.filter(name="admin_url")
def admin_url(obj):
    """Usage: {{ some_model_instance|admin_url }} -> '/admin/masters/sale/3/change/'
    or '' if obj is None / not saved / has no registered ModelAdmin.
    Lets report templates link straight back to the source voucher without
    each template needing to know which model (Sale, Purchase, Journal...)
    a given row actually is."""
    return _voucher_admin_url(obj) or ""

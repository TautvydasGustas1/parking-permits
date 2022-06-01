from django.core import mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.html import strip_tags


class PermitEmailType:
    CREATED = "created"
    UPDATED = "updated"
    ENDED = "ended"


permit_email_subjects = {
    PermitEmailType.CREATED: "Pysäköintitunnukset: Sinulle on luotu pysäköintitunnus",
    PermitEmailType.UPDATED: "Pysäköintitunnukset: Tiedot päivitetty",
    PermitEmailType.ENDED: "Pysäköintitunnukset: Tilauksesi on päättynyt",
}

permit_email_templates = {
    PermitEmailType.CREATED: "emails/permit_created.html",
    PermitEmailType.UPDATED: "emails/permit_updated.html",
    PermitEmailType.ENDED: "emails/permit_ended.html",
}


def send_permit_email(action, permit):
    subject = permit_email_subjects[action]
    template = permit_email_templates[action]
    with translation.override(permit.customer.language):
        html_message = render_to_string(template, context={"permit": permit})
    plain_message = strip_tags(html_message)
    recipient_list = [permit.customer.email]
    mail.send_mail(
        subject,
        plain_message,
        None,
        recipient_list,
        html_message=html_message,
    )

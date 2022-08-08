from django.core import mail
from django.template.loader import render_to_string
from django.utils import translation
from django.utils.html import strip_tags


class PermitEmailType:
    CREATED = "created"
    UPDATED = "updated"
    ENDED = "ended"
    TEMP_VEHICLE_ACTIVATED = "temp_vehicle_activated"
    TEMP_VEHICLE_DEACTIVATED = "temp_vehicle_deactivated"


permit_email_subjects = {
    PermitEmailType.CREATED: "Pysäköintitunnukset: Sinulle on luotu pysäköintitunnus",
    PermitEmailType.UPDATED: "Pysäköintitunnukset: Tiedot päivitetty",
    PermitEmailType.ENDED: "Pysäköintitunnukset: Tilauksesi on päättynyt",
    PermitEmailType.TEMP_VEHICLE_ACTIVATED: "Pysäköintitunnukset: Tilapäinen ajoneuvo liitetty tunnukseen",
    PermitEmailType.TEMP_VEHICLE_DEACTIVATED: "Pysäköintitunnukset: Pysäköintitunnuksen voimassaolo päättyy pian",
}

permit_email_templates = {
    PermitEmailType.CREATED: "emails/permit_created.html",
    PermitEmailType.UPDATED: "emails/permit_updated.html",
    PermitEmailType.ENDED: "emails/permit_ended.html",
    PermitEmailType.TEMP_VEHICLE_ACTIVATED: "emails/temporary_vehicle_activated.html",
    PermitEmailType.TEMP_VEHICLE_DEACTIVATED: "emails/temporary_vehicle_deactivated.html",
}


def send_permit_email(action, permit):
    with translation.override(permit.customer.language):
        subject = permit_email_subjects[action]
        template = permit_email_templates[action]
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


class RefundEmailType:
    CREATED = "created"
    ACCEPTED = "accepted"


refund_email_subjects = {
    RefundEmailType.CREATED: "Pysäköintitunnukset: Palautus otettu käsittelyyn",
    RefundEmailType.ACCEPTED: "Pysäköintitunnukset: Palautus on hyväksytty",
}


refund_email_templates = {
    RefundEmailType.CREATED: "emails/refund_created.html",
    RefundEmailType.ACCEPTED: "emails/refund_accepted.html",
}


def send_refund_email(action, customer):
    with translation.override(customer.language):
        subject = refund_email_subjects[action]
        template = refund_email_templates[action]
        html_message = render_to_string(template)
        plain_message = strip_tags(html_message)
        recipient_list = [customer.email]
        mail.send_mail(
            subject,
            plain_message,
            None,
            recipient_list,
            html_message=html_message,
        )

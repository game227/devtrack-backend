from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import IssueAttachment


@receiver(post_delete, sender=IssueAttachment, dispatch_uid="issues-attachment-file")
def delete_attachment_file(sender, instance, **kwargs):
    """Remove the stored file once the row is gone for good (also when its issue or project is deleted)."""
    if instance.file:
        storage, name = instance.file.storage, instance.file.name
        transaction.on_commit(lambda: storage.delete(name))

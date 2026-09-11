from django.db import models


class Milestone(models.Model):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="milestones"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    target_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["target_date"]

    def __str__(self):
        return self.name

from django.contrib import admin

from .models import Label, Project, ProjectMember

admin.site.register(Project)
admin.site.register(ProjectMember)
admin.site.register(Label)

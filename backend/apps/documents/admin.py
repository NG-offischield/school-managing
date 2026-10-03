"""Django admin registrations — developer tooling only (read-only)."""

from django.contrib import admin

from .models import Document, DocumentDownload


class ReadOnlyAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "status", "version", "generated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Document, ReadOnlyAdmin)


class DownloadAdmin(ReadOnlyAdmin):
    list_display = ("document", "actor", "downloaded_at")


admin.site.register(DocumentDownload, DownloadAdmin)

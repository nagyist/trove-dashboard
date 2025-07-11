# Copyright 2013 Rackspace Hosting
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.conf import settings
from django.template import defaultfilters as d_filters
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.utils.translation import pgettext_lazy

from horizon import tables
from horizon.utils import filters

from trove_dashboard import api


STATUS_CHOICES = (
    ("BUILDING", None),
    ("COMPLETED", True),
    ("DELETE_FAILED", False),
    ("FAILED", False),
    ("NEW", None),
    ("RESTORED", True),
    ("SAVING", None),
)
STATUS_DISPLAY_CHOICES = (
    ("BUILDING", pgettext_lazy("Current status of a Database Backup",
                               "Building")),
    ("COMPLETED", pgettext_lazy("Current status of a Database Backup",
                                "Completed")),
    ("DELETE_FAILED", pgettext_lazy("Current status of a Database Backup",
                                    "Delete Failed")),
    ("FAILED", pgettext_lazy("Current status of a Database Backup",
                             "Failed")),
    ("NEW", pgettext_lazy("Current status of a Database Backup",
                          "New")),
    ("RESTORED", pgettext_lazy("Current status of a Database Backup",
                               "Restored")),
    ("SAVING", pgettext_lazy("Current status of a Database Backup",
                             "Saving")),
)


class LaunchLink(tables.LinkAction):
    name = "create"
    verbose_name = _("Create Backup")
    url = "horizon:project:database_backups:create"
    classes = ("ajax-modal", "btn-create")
    icon = "camera"
    policy_rules = (("database", "backup:create"), )


class RestoreLink(tables.LinkAction):
    name = "restore"
    verbose_name = _("Restore Backup")
    url = "horizon:project:databases:launch"
    classes = ("ajax-modal",)
    icon = "cloud-upload"
    policy_rules = (("database", "backup:show"), )

    def allowed(self, request, backup=None):
        return backup.status in ['COMPLETED', 'RESTORED']

    def get_link_url(self, datum):
        url = reverse(self.url)
        return url + '?backup=%s' % datum.id


class DownloadBackup(tables.LinkAction):
    name = "download"
    verbose_name = _("Download Backup")
    url = 'horizon:project:containers:object_download'
    classes = ("btn-download",)
    policy_rules = (("database", "backup:show"), )

    def get_link_url(self, datum):
        ref = datum.locationRef.split('/')
        container_name = ref[5]
        object_path = '/'.join(ref[6:])
        return reverse(self.url,
                       kwargs={'container_name': container_name,
                               'object_path': object_path})

    def allowed(self, request, datum):
        legacy_swift_panel_enabled = False
        if ('swift_panel' in settings.HORIZON_CONFIG and
                settings.HORIZON_CONFIG['swift_panel'] == 'legacy' and
                datum.status == 'COMPLETED'):
            legacy_swift_panel_enabled = True
        return legacy_swift_panel_enabled


class DeleteBackup(tables.DeleteAction):
    policy_rules = (("database", "backup:delete"), )

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Delete Backup",
            "Delete Backups",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Deleted Backup",
            "Deleted Backups",
            count
        )

    def delete(self, request, obj_id):
        api.trove.backup_delete(request, obj_id)


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, backup_id):
        backup = api.trove.backup_get(request, backup_id)
        try:
            backup.instance = api.trove.instance_get(request,
                                                     backup.instance_id)
        except Exception:
            pass
        return backup


def db_link(obj):
    if not hasattr(obj, 'instance'):
        return
    if hasattr(obj.instance, 'name'):
        return reverse(
            'horizon:project:databases:detail',
            kwargs={'instance_id': obj.instance_id})


def db_name(obj):
    if not hasattr(obj, 'instance') or not hasattr(obj.instance, 'name'):
        return obj.instance_id
    return obj.instance.name


def get_datastore(obj):
    if hasattr(obj, "datastore"):
        return obj.datastore["type"]
    return _("Not available")


def get_datastore_version(obj):
    if hasattr(obj, "datastore"):
        return obj.datastore["version"]
    return _("Not available")


def is_incremental(obj):
    return hasattr(obj, 'parent_id') and obj.parent_id is not None


class BackupsTable(tables.DataTable):
    name = tables.Column("name",
                         link="horizon:project:database_backups:detail",
                         verbose_name=_("Name"))
    datastore = tables.Column(get_datastore,
                              verbose_name=_("Datastore"))
    datastore_version = tables.Column(get_datastore_version,
                                      verbose_name=_("Datastore Version"))
    created = tables.Column("created", verbose_name=_("Created"),
                            filters=[filters.parse_isotime])
    instance = tables.Column(db_name, link=db_link,
                             verbose_name=_("Database"))
    incremental = tables.Column(is_incremental,
                                verbose_name=_("Incremental"),
                                filters=(d_filters.yesno,
                                         d_filters.capfirst))
    status = tables.Column("status",
                           verbose_name=_("Status"),
                           status=True,
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)

    class Meta(object):
        name = "backups"
        verbose_name = _("Backups")
        status_columns = ["status"]
        row_class = UpdateRow
        table_actions = (LaunchLink, DeleteBackup)
        row_actions = (RestoreLink, DownloadBackup, DeleteBackup)

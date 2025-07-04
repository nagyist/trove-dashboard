# Copyright 2012 Nebula, Inc.
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

from urllib import parse as urlparse

from django.conf import settings
from django import template
from django.template import defaultfilters as d_filters
from django import urls
from django.urls import reverse
from django.utils import html
from django.utils import safestring

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy
from django.utils.translation import pgettext_lazy

from horizon import exceptions
from horizon import messages
from horizon import tables
from horizon.templatetags import sizeformat
from horizon.utils import filters

from trove_dashboard import api
from trove_dashboard.content.database_backups \
    import tables as backup_tables


ACTIVE_STATES = ("ACTIVE", "HEALTHY",)


class DeleteInstance(tables.DeleteAction):
    help_text = _("Deleted instances are not recoverable.")
    policy_rules = (("database", "instance:delete"),)

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Delete Instance",
            "Delete Instances",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Scheduled deletion of Instance",
            "Scheduled deletion of Instances",
            count
        )

    def delete(self, request, obj_id):
        api.trove.instance_delete(request, obj_id)


class RestartInstance(tables.BatchAction):
    help_text = _("Restarted instances will lose any data not"
                  " saved in persistent storage.")
    policy_rules = (("database", "instance:restart"),)

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Restart Instance",
            "Restart Instances",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Restarted Instance",
            "Restarted Instances",
            count
        )

    name = "restart"
    classes = ('btn-danger', 'btn-reboot')

    def allowed(self, request, instance=None):
        return ((instance.status in ACTIVE_STATES or
                 instance.status == 'SHUTDOWN' or
                 instance.status == 'RESTART_REQUIRED'))

    def action(self, request, obj_id):
        api.trove.instance_restart(request, obj_id)


class DetachReplica(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Detach Replica",
            "Detach Replicas",
            count
        )
    policy_rules = (("database", "instance:eject_replica_source"),)

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Replica Detached",
            "Replicas Detached",
            count
        )

    name = "detach_replica"
    classes = ('btn-danger', 'btn-detach-replica')

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES and
                hasattr(instance, 'replica_of'))

    def action(self, request, obj_id):
        api.trove.instance_detach_replica(request, obj_id)


class PromoteToReplicaSource(tables.LinkAction):
    name = "promote_to_replica_source"
    verbose_name = _("Promote to Replica Source")
    url = "horizon:project:databases:promote_to_replica_source"
    classes = ("ajax-modal", "btn-promote-to-replica-source")
    policy_rules = (("database", "instance:promote_to_replica_source"),)

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES and
                hasattr(instance, 'replica_of'))

    def get_link_url(self, datum):
        instance_id = self.table.get_object_id(datum)
        return urls.reverse(self.url, args=[instance_id])


class EjectReplicaSource(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Eject Replica Source",
            "Eject Replica Sources",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Ejected Replica Source",
            "Ejected Replica Sources",
            count
        )

    name = "eject_replica_source"
    classes = ('btn-danger', 'btn-eject-replica-source')
    policy_rules = (("database", "instance:eject_replica_source"),)

    def _allowed(self, request, instance=None):
        return (instance.status != 'PROMOTE' and
                hasattr(instance, 'replicas'))

    def action(self, request, obj_id):
        api.trove.eject_replica_source(request, obj_id)


class GrantAccess(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Grant Access",
            "Grant Access",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Granted Access to",
            "Granted Access to",
            count
        )

    name = "grant_access"
    classes = ('btn-grant-access')
    policy_rules = (("database", "instance:extension:user_access:update"),)

    def allowed(self, request, instance=None):
        if instance:
            return not instance.access
        return False

    def action(self, request, obj_id):
        api.trove.user_grant_access(
            request,
            self.table.kwargs['instance_id'],
            self.table.kwargs['user_name'],
            [obj_id],
            host=self.table.kwargs['user_host'])


class RevokeAccess(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Revoke Access",
            "Revoke Access",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Access Revoked to",
            "Access Revoked to",
            count
        )

    name = "revoke_access"
    classes = ('btn-revoke-access')
    policy_rules = (("database", "instance:extension:user_access:delete"),)

    def allowed(self, request, instance=None):
        if instance:
            return instance.access
        return False

    def action(self, request, obj_id):
        api.trove.user_revoke_access(
            request,
            self.table.kwargs['instance_id'],
            self.table.kwargs['user_name'],
            obj_id,
            host=self.table.kwargs['user_host'])


def parse_host_param(request):
    host = None
    if request.META.get('QUERY_STRING', ''):
        param = urlparse.parse_qs(request.META.get('QUERY_STRING'))
        values = param.get('host')
        if values:
            host = next(iter(values), None)
    return host


class AccessTable(tables.DataTable):
    dbname = tables.Column("name", verbose_name=_("Name"))

    access = tables.Column(
        "access",
        verbose_name=_("Accessible"),
        filters=(d_filters.yesno, d_filters.capfirst))

    class Meta(object):
        name = "access"
        verbose_name = _("Database Access")
        row_actions = (GrantAccess, RevokeAccess)

    def get_object_id(self, datum):
        return datum.name


class ManageAccess(tables.LinkAction):
    name = "manage_access"
    verbose_name = _("Manage Access")
    url = "horizon:project:databases:access_detail"
    icon = "pencil"
    policy_rules = (("database", "instance:extension:user_access:update"),)

    def allowed(self, request, instance=None):
        instance = self.table.kwargs['instance']
        return (instance.status in ACTIVE_STATES and
                has_user_add_perm(request))

    def get_link_url(self, datum):
        user = datum
        return urls.reverse(self.url, args=[user.instance.id,
                                            user.name,
                                            user.host])


class CreateUser(tables.LinkAction):
    name = "create_user"
    verbose_name = _("Create User")
    url = "horizon:project:databases:create_user"
    classes = ("ajax-modal",)
    icon = "plus"
    policy_rules = (("database", "instance:extension:user:create"),)

    def allowed(self, request, instance=None):
        instance = self.table.kwargs['instance']
        return (instance.status in ACTIVE_STATES and
                has_user_add_perm(request))

    def get_link_url(self, datum=None):
        instance_id = self.table.kwargs['instance_id']
        return urls.reverse(self.url, args=[instance_id])


class EditUser(tables.LinkAction):
    name = "edit_user"
    verbose_name = _("Edit User")
    url = "horizon:project:databases:edit_user"
    classes = ("ajax-modal",)
    icon = "pencil"
    policy_rules = (("database", "instance:extension:user:update"),)

    def allowed(self, request, instance=None):
        instance = self.table.kwargs['instance']
        return (instance.status in ACTIVE_STATES and
                has_user_add_perm(request))

    def get_link_url(self, datum):
        user = datum
        return urls.reverse(self.url, args=[user.instance.id,
                                            user.name,
                                            user.host])


def has_user_add_perm(request):
    perms = getattr(settings, 'TROVE_ADD_USER_PERMS', [])
    if perms:
        return request.user.has_perms(perms)
    return True


class DeleteUser(tables.DeleteAction):
    policy_rules = (("database", "instance:extension:user:delete"),)

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Delete User",
            "Delete Users",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Deleted User",
            "Deleted Users",
            count
        )

    def delete(self, request, obj_id):
        user = self.table.get_object_by_id(obj_id)
        api.trove.user_delete(request, user.instance.id, user.name,
                              host=user.host)


class CreateDatabase(tables.LinkAction):
    name = "create_database"
    verbose_name = _("Create Database")
    url = "horizon:project:databases:create_database"
    classes = ("ajax-modal",)
    icon = "plus"
    policy_rules = (("database", "instance:extension:database:create"),)

    def allowed(self, request, database=None):
        instance = self.table.kwargs['instance']
        return (instance.status in ACTIVE_STATES and
                has_database_add_perm(request))

    def get_link_url(self, datum=None):
        instance_id = self.table.kwargs['instance_id']
        return urls.reverse(self.url, args=[instance_id])


def has_database_add_perm(request):
    perms = getattr(settings, 'TROVE_ADD_DATABASE_PERMS', [])
    if perms:
        return request.user.has_perms(perms)
    return True


class DeleteDatabase(tables.DeleteAction):
    policy_rules = (("database", "instance:extension:database:delete"),)

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Delete Database",
            "Delete Databases",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Deleted Database",
            "Deleted Databases",
            count
        )

    def delete(self, request, obj_id):
        datum = self.table.get_object_by_id(obj_id)
        try:
            api.trove.database_delete(request, datum.instance.id, datum.name)
        except Exception:
            msg = _('Error deleting database on instance.')
            exceptions.handle(request, msg)


class LaunchLink(tables.LinkAction):
    name = "launch"
    verbose_name = _("Launch Instance")
    url = "horizon:project:databases:launch"
    classes = ("ajax-modal", "btn-launch")
    icon = "cloud-upload"
    policy_rules = (("database", "instance:create"),)


class CreateBackup(tables.LinkAction):
    name = "backup"
    verbose_name = _("Create Backup")
    url = "horizon:project:database_backups:create"
    classes = ("ajax-modal",)
    icon = "camera"
    policy_rules = (("database", "backup:create"),)

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES and
                request.user.has_perm('openstack.services.object-store'))

    def get_link_url(self, datam):
        url = urls.reverse(self.url)
        return url + "?instance=%s" % datam.id


class ResizeVolume(tables.LinkAction):
    name = "resize_volume"
    verbose_name = _("Resize Volume")
    url = "horizon:project:databases:resize_volume"
    classes = ("ajax-modal", "btn-resize")
    policy_rules = (("database", "instance:resize_volume"),)

    def allowed(self, request, instance=None):
        return instance.status in ACTIVE_STATES

    def get_link_url(self, datum):
        instance_id = self.table.get_object_id(datum)
        return urls.reverse(self.url, args=[instance_id])


class ResizeInstance(tables.LinkAction):
    name = "resize_instance"
    verbose_name = _("Resize Instance")
    url = "horizon:project:databases:resize_instance"
    classes = ("ajax-modal", "btn-resize")
    policy_rules = (("database", "instance:resize_flavor"),)

    def allowed(self, request, instance=None):
        return ((instance.status in ACTIVE_STATES or
                 instance.status == 'SHUTOFF'))

    def get_link_url(self, datum):
        instance_id = self.table.get_object_id(datum)
        return urls.reverse(self.url, args=[instance_id])


class AttachConfiguration(tables.LinkAction):
    name = "attach_configuration"
    verbose_name = _("Attach Configuration Group")
    url = "horizon:project:databases:attach_config"
    classes = ("btn-attach-config", "ajax-modal")
    policy_rules = (("database", "instance:update"),)

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES and
                not hasattr(instance, 'configuration'))


class DetachConfiguration(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Detach Configuration Group",
            "Detach Configuration Groups",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Detached Configuration Group",
            "Detached Configuration Groups",
            count
        )

    name = "detach_configuration"
    classes = ('btn-danger', 'btn-detach-config')
    policy_rules = (("database", "instance:update"),)

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES and
                hasattr(instance, 'configuration'))

    def action(self, request, obj_id):
        api.trove.instance_detach_configuration(request, obj_id)


class EnableRootAction(tables.Action):
    name = "enable_root_action"
    verbose_name = _("Enable Root")
    policy_rules = (("database", "instance:extension:root:create"),)

    def handle(self, table, request, obj_ids):
        try:
            username, password = api.trove.root_enable(request, obj_ids)
            table.data[0].enabled = True
            table.data[0].password = password
        except Exception:
            messages.error(request, _('There was a problem enabling root.'))


class DisableRootAction(tables.Action):
    name = "disable_root_action"
    verbose_name = _("Disable Root")
    policy_rules = (("database", "instance:extension:root:delete"),)

    def allowed(self, request, instance):
        enabled = api.trove.root_show(request, instance.id)
        return enabled.rootEnabled

    def single(self, table, request, object_id):
        try:
            api.trove.root_disable(request, object_id)
            table.data[0].password = None
            messages.success(request, _("Successfully disabled root access."))
        except Exception as e:
            messages.warning(request,
                             _("Cannot disable root access: %s") % e)


class ManageRoot(tables.LinkAction):
    name = "manage_root_action"
    verbose_name = _("Manage Root Access")
    url = "horizon:project:databases:manage_root"
    policy_rules = (("database", "instance:extension:root:index"),
                    ("database", "instance:extension:root:create"),
                    ("database", "instance:extension:root:delete"))

    def allowed(self, request, instance):
        return instance.status in ACTIVE_STATES

    def get_link_url(self, datum=None):
        instance_id = self.table.get_object_id(datum)
        return urls.reverse(self.url, args=[instance_id])


class ManageRootTable(tables.DataTable):
    name = tables.Column('name', verbose_name=_('Instance Name'))
    policy_rules = (("database", "instance:extension:root:index"), )
    enabled = tables.Column('enabled',
                            verbose_name=_('Has Root Ever Been Enabled'),
                            filters=(d_filters.yesno, d_filters.capfirst),
                            help_text=_("Status if root was ever enabled "
                                        "for an instance."))
    password = tables.Column('password', verbose_name=_('Password'),
                             help_text=_("Password is only visible "
                                         "immediately after the root is "
                                         "enabled or reset."))

    class Meta(object):
        name = "manage_root"
        verbose_name = _("Manage Root")
        row_actions = (EnableRootAction, DisableRootAction,)


class UpdateRow(tables.Row):
    ajax = True

    def get_data(self, request, instance_id):
        instance = api.trove.instance_get(request, instance_id)
        try:
            flavor_id = instance.flavor['id']
            instance.full_flavor = api.trove.flavor_get(request, flavor_id)
        except Exception:
            pass
        instance.host = get_host(instance)
        return instance


def get_datastore(instance):
    if hasattr(instance, "datastore"):
        return instance.datastore["type"]
    return _("Not available")


def get_datastore_version(instance):
    if hasattr(instance, "datastore"):
        return instance.datastore["version"]
    return _("Not available")


# NOTE(e0ne): the logic is based on
# openstack_dashboard.dashboards.project.instances.tables.get_ips
# Trove has a different instance addresses structure so we can't re-use
# nova-related code as is.
def get_ips(instance):
    template_name = 'project/instances/_instance_ips.html'
    ip_groups = {}

    for address in getattr(instance, 'addresses', []):
        ip_groups[address["type"]] = [address["address"]]

    context = {
        "ip_groups": ip_groups,
    }
    return template.loader.render_to_string(template_name, context)


def get_host(instance):
    if hasattr(instance, "hostname"):
        return instance.hostname
    elif hasattr(instance, "ip") and instance.ip:
        return get_ips(instance)
    return _("Not Assigned")


def get_size(instance):
    if hasattr(instance, "full_flavor"):
        size_string = _("%(name)s | %(RAM)s RAM")
        vals = {'name': instance.full_flavor.name,
                'RAM': sizeformat.mb_float_format(instance.full_flavor.ram)}
        return size_string % vals
    return _("Not available")


def get_volume_size(instance):
    if hasattr(instance, "volume"):
        return sizeformat.diskgbformat(instance.volume.get("size"))
    return _("Not available")


def get_databases(user):
    if hasattr(user, "access"):
        databases = [db.name for db in user.access]
        databases.sort()
        return ', '.join(databases)
    return _("-")


class ReplicaColumn(tables.WrappingColumn):
    """Customized column class.

        So it that does complex processing on the replication
        for a database instance.
        """

    instance_detail_url = "horizon:project:databases:detail"

    def get_instance_link(self, instance_id):
        request = self.table.request
        url = reverse(self.instance_detail_url, args=(instance_id,))
        instance = api.trove.instance_get(request, instance_id)
        link = '<a href="%s">%s</a>' % (url, html.escape(instance.name))
        return link

    def get_raw_data(self, instance):
        if hasattr(instance, "replicas"):
            links = []
            for replica in instance.replicas:
                instance_id = replica["id"]
                links.append(self.get_instance_link(instance_id))
            replicas = ', '.join(links)
            cell_text = ("Primary, has replicas: %s") % replicas
            return safestring.mark_safe(cell_text)
        if hasattr(instance, "replica_of"):
            instance_id = instance.replica_of["id"]
            link = self.get_instance_link(instance_id)
            replica_of = _("Replica of %s")
            return safestring.mark_safe(replica_of % link)
        return _("-")


class StopDatabase(tables.BatchAction):
    name = "stop_database"
    help_text = _("Stop database service inside an instance.")
    action_type = "danger"
    policy_rules = (("database", "instance:extension:database:delete"), )

    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Stop Database Service",
            "Stop Database Services",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Database Service stopped",
            "Database Services stopped",
            count
        )

    def action(self, request, obj_id):
        api.trove.stop_database(request, obj_id)

    def allowed(self, request, instance):
        return request.user.is_superuser and instance.status in ACTIVE_STATES


class UpdateInstance(tables.LinkAction):
    name = "edit_instance"
    verbose_name = _("Update Instance")
    url = "horizon:project:databases:edit_instance"
    classes = ("btn-attach-config", "ajax-modal")
    policy_rules = (("database", "instance:update"), )

    def allowed(self, request, instance=None):
        return (instance.status in ACTIVE_STATES)


class InstancesTable(tables.DataTable):
    STATUS_CHOICES = (
        ("ACTIVE", True),
        ("HEALTHY", True),
        ("BLOCKED", True),
        ("BUILD", None),
        ("FAILED", False),
        ("REBOOT", None),
        ("RESIZE", None),
        ("BACKUP", None),
        ("SHUTDOWN", False),
        ("ERROR", False),
        ("RESTART_REQUIRED", None),
    )
    STATUS_DISPLAY_CHOICES = (
        ("ACTIVE", pgettext_lazy("Current status of a Database Instance",
                                 "Active")),
        ("Healthy", pgettext_lazy("Current status of a Database Instance",
                                  "Healthy")),
        ("BLOCKED", pgettext_lazy("Current status of a Database Instance",
                                  "Blocked")),
        ("BUILD", pgettext_lazy("Current status of a Database Instance",
                                "Building")),
        ("FAILED", pgettext_lazy("Current status of a Database Instance",
                                 "Failed")),
        ("REBOOT", pgettext_lazy("Current status of a Database Instance",
                                 "Rebooting")),
        ("RESIZE", pgettext_lazy("Current status of a Database Instance",
                                 "Resizing")),
        ("BACKUP", pgettext_lazy("Current status of a Database Instance",
                                 "Backup")),
        ("SHUTDOWN", pgettext_lazy("Current status of a Database Instance",
                                   "Shutdown")),
        ("ERROR", pgettext_lazy("Current status of a Database Instance",
                                "Error")),
        ("RESTART_REQUIRED",
         pgettext_lazy("Current status of a Database Instance",
                       "Restart Required")),
    )
    name = tables.Column("name",
                         link="horizon:project:databases:detail",
                         verbose_name=_("Instance Name"))
    datastore = tables.Column(get_datastore,
                              verbose_name=_("Datastore"))
    datastore_version = tables.Column(get_datastore_version,
                                      verbose_name=_("Datastore Version"))
    host = tables.Column(get_host, verbose_name=_("Host"))
    size = tables.Column(get_size,
                         verbose_name=_("Size"),
                         attrs={'data-type': 'size'})
    replication = ReplicaColumn("replicas",
                                verbose_name=_("Replication Status"))
    volume = tables.Column(get_volume_size,
                           verbose_name=_("Volume Size"),
                           attrs={'data-type': 'size'})
    status = tables.Column("status",
                           verbose_name=_("Status"),
                           status_choices=STATUS_CHOICES,
                           display_choices=STATUS_DISPLAY_CHOICES)
    operating_status = tables.Column("operating_status",
                                     verbose_name=_("Operating Status"),
                                     status=True,
                                     status_choices=STATUS_CHOICES,
                                     display_choices=STATUS_DISPLAY_CHOICES)

    class Meta(object):
        name = "databases"
        verbose_name = _("Instances")
        status_columns = ["status"]
        row_class = UpdateRow
        table_actions = (LaunchLink, DeleteInstance)
        row_actions = (CreateBackup,
                       UpdateInstance,
                       ResizeVolume,
                       ResizeInstance,
                       PromoteToReplicaSource,
                       AttachConfiguration,
                       DetachConfiguration,
                       ManageRoot,
                       EjectReplicaSource,
                       DetachReplica,
                       RestartInstance,
                       StopDatabase,
                       DeleteInstance)


class UsersTable(tables.DataTable):
    name = tables.Column("name", verbose_name=_("User Name"))
    host = tables.Column("host", verbose_name=_("Allowed Host"))
    databases = tables.Column(get_databases, verbose_name=_("Databases"))

    class Meta(object):
        name = "users"
        verbose_name = _("Users")
        table_actions = [CreateUser, DeleteUser]
        row_actions = [EditUser, ManageAccess, DeleteUser]

    def get_object_id(self, datum):
        obj_id = datum.name + "@" + datum.host
        return obj_id


class DatabaseTable(tables.DataTable):
    name = tables.Column("name", verbose_name=_("Database Name"))

    class Meta(object):
        name = "databases"
        verbose_name = _("Databases")
        table_actions = [CreateDatabase, DeleteDatabase]
        row_actions = [DeleteDatabase]

    def get_object_id(self, datum):
        return datum.name


def is_incremental(obj):
    return hasattr(obj, 'parent_id') and obj.parent_id is not None


class InstanceBackupsTable(tables.DataTable):
    name = tables.Column("name",
                         link="horizon:project:database_backups:detail",
                         verbose_name=_("Name"))
    created = tables.Column("created", verbose_name=_("Created"),
                            filters=[filters.parse_isotime])
    location = tables.Column(lambda obj: _("Download"),
                             link=lambda obj: obj.locationRef,
                             verbose_name=_("Backup File"))
    incremental = tables.Column(is_incremental,
                                verbose_name=_("Incremental"),
                                filters=(d_filters.yesno,
                                         d_filters.capfirst))
    status = tables.Column(
        "status",
        verbose_name=_("Status"),
        status=True,
        status_choices=backup_tables.STATUS_CHOICES,
        display_choices=backup_tables.STATUS_DISPLAY_CHOICES)

    class Meta(object):
        name = "backups"
        verbose_name = _("Backups")
        status_columns = ["status"]
        row_class = UpdateRow
        table_actions = (backup_tables.LaunchLink, backup_tables.DeleteBackup)
        row_actions = (backup_tables.RestoreLink, backup_tables.DeleteBackup)


class ConfigDefaultsTable(tables.DataTable):
    name = tables.Column('name', verbose_name=_('Property'))
    value = tables.Column('value', verbose_name=_('Value'))

    class Meta(object):
        name = 'config_defaults'
        verbose_name = _('Configuration Defaults')

    def get_object_id(self, datum):
        return datum.name

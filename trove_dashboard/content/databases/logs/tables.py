# Copyright 2016 Tesora Inc.
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

from django import urls
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from horizon import tables

from trove_dashboard import api


class PublishLog(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Publish Log",
            "Publish Logs",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Published Log",
            "Published Logs",
            count
        )

    name = "publish_log"
    policy_rules = (("database", "instance:guest_log_list"),)

    def action(self, request, obj_id):
        instance_id = self.table.kwargs['instance_id']
        api.trove.log_publish(request, instance_id, obj_id)


class DiscardLog(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Discard Log",
            "Discard Logs",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Discarded Log",
            "Discarded Logs",
            count
        )

    name = "discard_log"
    policy_rules = (("database", "instance:guest_log_list"),)

    def action(self, request, obj_id):
        instance_id = self.table.kwargs['instance_id']
        api.trove.log_discard(request, instance_id, obj_id)


class EnableLog(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Enable Log",
            "Enable Logs",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Enabled Log",
            "Enabled Logs",
            count
        )

    name = "enable_log"
    policy_rules = (("database", "instance:guest_log_list"),)

    def action(self, request, obj_id):
        instance_id = self.table.kwargs['instance_id']
        api.trove.log_enable(request, instance_id, obj_id)


class DisableLog(tables.BatchAction):
    @staticmethod
    def action_present(count):
        return ngettext_lazy(
            "Disable Log",
            "Disable Logs",
            count
        )

    @staticmethod
    def action_past(count):
        return ngettext_lazy(
            "Disabled Log",
            "Disabled Logs",
            count
        )

    name = "disable_log"
    policy_rules = (("database", "instance:guest_log_list"),)

    def action(self, request, obj_id):
        instance_id = self.table.kwargs['instance_id']
        api.trove.log_disable(request, instance_id, obj_id)

    def allowed(self, request, datum=None):
        if datum:
            return datum.type != "SYS"
        return False


class ViewLog(tables.LinkAction):
    name = "view_log"
    verbose_name = _("View Log")
    url = "horizon:project:databases:logs:log_contents"
    policy_rules = (("database", "instance:guest_log_list"),)

    def get_link_url(self, datum):
        instance_id = self.table.kwargs['instance_id']
        return urls.reverse(self.url, args=(instance_id, datum.name))

    def allowed(self, request, datum=None):
        if datum:
            return datum.published > 0
        return False


class LogsTable(tables.DataTable):
    name = tables.Column('name', verbose_name=_('Name'))
    type = tables.Column('type', verbose_name=_("Type"))
    status = tables.Column('status', verbose_name=_("Status"))
    published = tables.Column('published', verbose_name=_('Published (bytes)'))
    pending = tables.Column('pending', verbose_name=_('Publishable (bytes)'))
    container = tables.Column('container', verbose_name=_('Container'))

    class Meta(object):
        name = "logs"
        verbose_name = _("Logs")
        row_actions = (ViewLog, PublishLog, EnableLog, DisableLog, DiscardLog)

    def get_object_id(self, datum):
        return datum.name

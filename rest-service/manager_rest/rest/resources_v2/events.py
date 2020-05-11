#########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  * See the License for the specific language governing permissions and
#  * limitations under the License.
#

from flask_restful_swagger import swagger
from sqlalchemy import bindparam
from datetime import datetime
import os
import subprocess

from cloudify import logs

from manager_rest import manager_exceptions
from manager_rest.rest import (
    resources_v1,
    rest_decorators,
)
from manager_rest.storage.models_base import db
from manager_rest.storage.resource_models import (
    Deployment,
    Execution,
    Event,
    Log,
)
from manager_rest.storage import ListResult
from manager_rest.security.authorization import authorize


class Events(resources_v1.Events):
    """Events resource.

    Through the events endpoint a user can retrieve both events and logs as
    stored in the SQL database.

    """

    @swagger.operation(
        responseclass='List[Event]',
        nickname="list events",
        notes='Returns a list of events for optionally provided filters'
    )
    @authorize('event_list')
    @rest_decorators.marshal_events
    @rest_decorators.create_filters()
    @rest_decorators.paginate
    @rest_decorators.rangeable
    @rest_decorators.projection
    @rest_decorators.sortable()
    def get(self, _include=None, filters=None,
            pagination=None, sort=None, range_filters=None, **kwargs):
        """List events using a SQL backend.

        :param _include:
            Projection used to get records from database (not currently used)
        :type _include: list(str)
        :param filters:
            Filter selection.

            It's used to decide if events:
                {'type': ['cloudify_event']}
            or both events and logs should be returned:
                {'type': ['cloudify_event', 'cloudify_log']}

            Also it's used to get only events for a particular execution:
                {'execution_id': '<some uuid>'}
        :type filters: dict(str, str)
        :param pagination:
            Parameters used to limit results returned in a single query.
            Expected values `size` and `offset` are mapped into SQL as `LIMIT`
            and `OFFSET`.
        :type pagination: dict(str, int)
        :param sort:
            Result sorting order. The only allowed and expected value is to
            sort by timestamp in ascending order:
                {'timestamp': 'asc'}
        :type sort: dict(str, str)
        :returns: Events that match the conditions passed as arguments
        :rtype: :class:`manager_rest.storage.storage_manager.ListResult`
        :param range_filters:
            Apparently was used to select a timestamp interval. It's not
            currently used.
        :type range_filters: dict(str)
        :returns: Events found in the SQL backend
        :rtype: :class:`manager_rest.storage.storage_manager.ListResult`

        """
        size = pagination.get('size', self.DEFAULT_SEARCH_SIZE)
        offset = pagination.get('offset', 0)
        params = {
            'limit': size,
            'offset': offset,
        }

        select_query, total = self._build_select_query(
            filters, sort, range_filters, self.current_tenant.id
        )

        results = [
            self._map_event_to_dict(_include, event)
            for event in select_query.params(**params).all()
        ]

        metadata = {
            'pagination': {
                'size': size,
                'offset': offset,
                'total': total,
            }
        }
        return ListResult(results, metadata)

    def post(self):
        raise manager_exceptions.MethodNotAllowedError()

    @swagger.operation(
        responseclass='List[Event]',
        nickname="delete events",
        notes='Deletes events according to a passed Deployment ID'
    )
    @authorize('event_delete')
    @rest_decorators.marshal_events
    @rest_decorators.create_filters()
    @rest_decorators.paginate
    @rest_decorators.rangeable
    @rest_decorators.projection
    @rest_decorators.sortable()
    def delete(self, filters=None, pagination=None, sort=None,
               range_filters=None, **kwargs):
        """Delete events/logs connected to a certain Deployment ID."""
        if not isinstance(filters, dict) or 'type' not in filters:
            raise manager_exceptions.BadParametersError(
                'Filter by type is expected')

        if 'cloudify_event' not in filters['type']:
            raise manager_exceptions.BadParametersError(
                'At least `type=cloudify_event` filter is expected')

        executions_query = (
            db.session.query(Execution._storage_id)
            .filter(
                Execution._deployment_fk == Deployment._storage_id,
                Deployment.id == bindparam('deployment_id'),
                Execution._tenant_id == bindparam('tenant_id')
            )
        )
        params = {
            'deployment_id': filters['deployment_id'][0],
            'tenant_id': self.current_tenant.id
        }
        do_store_before = 'store_before' in filters and \
                          filters['store_before'][0].upper() == 'TRUE'

        delete_event_query = Events._apply_range_filters(
            Events._build_delete_subquery(
                Event, executions_query, params),
            Event, range_filters)
        if do_store_before:
            self._store_log_entries('events', filters['deployment_id'][0],
                                    delete_event_query)
        # execution_fk = delete_event_query.first()._execution_fk
        deleted_entry_records = delete_event_query.delete(
            synchronize_session=False)
        # self._log_deletion(Event, filters['deployment_id'][0],
        #                    execution_fk, self.current_tenant.name,
        #                    deleted_entry_records)

        deleted_log_records = 0
        if 'cloudify_log' in filters['type']:
            delete_log_query = Events._apply_range_filters(
                Events._build_delete_subquery(
                    Log, executions_query, params),
                Log, range_filters)
            if do_store_before:
                self._store_log_entries('logs', filters['deployment_id'][0],
                                        delete_log_query)
            # execution_fk = delete_log_query.first()._execution_fk
            deleted_log_records = delete_log_query.delete('fetch')
            # self._log_deletion(Log, filters['deployment_id'][0],
            #                    execution_fk, self.current_tenant.name,
            #                    deleted_log_records)

        metadata = {
            'pagination':
                dict(pagination,
                     total=deleted_entry_records + deleted_log_records)
        }

        # Commit bulk row deletions to database
        db.session.commit()

        # We don't really want to return all of the deleted events,
        # so it's a bit of a hack to return the deleted element count.
        return ListResult([deleted_entry_records + deleted_log_records],
                          metadata)

    def _log_deletion(self, model, deployment_id, execution_fk,
                      deleted_records):
        if model is Event:
            message_type = 'cloudify_event'
        elif model is Log:
            message_type = 'cloudify_log'
        else:
            raise manager_exceptions.ConflictError()
        logentry = model()
        logentry._execution_fk = execution_fk
        logentry.message = u"Deleted {0} entries for deployment id {1}".format(
            deleted_records,
            deployment_id)
        logentry.operation = 'Logs deletion'
        db.session.add(logentry)
        return logentry

    def _store_log_entries(self, table_name, deployment_id, select_query):
        output_directory = Events._create_logs_output_directory()
        output_filename = "{0}_{1}_{2}.log".format(
            table_name, deployment_id,
            datetime.utcnow().strftime('%Y%m%dT%H%M%S')
        )
        output_filename = os.path.join(output_directory, output_filename)
        with open(output_filename, 'a') as output_file:
            results = [
                self._map_event_to_dict(None, event)
                for event in select_query.all()
            ]
            for event in results:
                output_file.write(logs.create_event_message_prefix(event))

    @staticmethod
    def _create_logs_output_directory():
        output_directory = os.path.join(os.sep, 'opt', 'manager', 'logs')
        cmd = 'mkdir {0}'.format(output_directory)
        subprocess.Popen(cmd, shell=True)
        return output_directory

    @staticmethod
    def _build_delete_subquery(model, execution_query, params):
        """Build delete subquery."""
        query = db.session.query(model).filter(
            model._execution_fk.in_(execution_query),
            model._tenant_id == bindparam('tenant_id'),
        )
        return query.params(**params)

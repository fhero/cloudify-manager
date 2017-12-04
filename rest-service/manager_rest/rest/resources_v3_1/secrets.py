#########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
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

from manager_rest import utils
from manager_rest.security import SecuredResource
from manager_rest.security.authorization import authorize
from manager_rest.storage import models, get_storage_manager
from manager_rest.resource_manager import get_resource_manager
from manager_rest.storage.models_states import AvailabilityState
from manager_rest.manager_exceptions import ConflictError
from manager_rest.rest.constants import (AVAILABILITY_VALUES,
                                         SET_AVAILABILITY_VALUES)
from manager_rest.rest import (rest_decorators,
                               resources_v3,
                               rest_utils)


class SecretsSetGlobal(SecuredResource):

    @rest_decorators.exceptions_handled
    @authorize('resource_set_global')
    @rest_decorators.marshal_with(models.Secret)
    def patch(self, key):
        """
        Set the secret's availability to global
        """
        return get_resource_manager().set_global_availability(
            models.Secret,
            key,
            AvailabilityState.GLOBAL
        )


class SecretsSetAvailability(SecuredResource):

    @rest_decorators.exceptions_handled
    @authorize('resource_set_availability')
    @rest_decorators.verify_params(SET_AVAILABILITY_VALUES)
    @rest_decorators.marshal_with(models.Secret)
    def patch(self, key, availability):
        """
        Set the secret's availability
        """
        return get_resource_manager().set_availability(models.Secret,
                                                       key,
                                                       availability)


class SecretsKey(resources_v3.SecretsKey):
    @rest_decorators.exceptions_handled
    @authorize('secret_create')
    @rest_decorators.verify_params(AVAILABILITY_VALUES)
    @rest_decorators.marshal_with(models.Secret)
    def put(self, key, **kwargs):
        """
        Create a new secret or update an existing secret if the flag
        update_if_exists is set to true
        """
        secret_params = self._get_secret_params(key)
        sm = get_storage_manager()
        timestamp = utils.get_formatted_timestamp()

        try:
            new_secret = models.Secret(
                id=key,
                value=secret_params['value'],
                created_at=timestamp,
                updated_at=timestamp,
                resource_availability=secret_params['availability'],
            )
            return sm.put(new_secret)
        except ConflictError:
            secret = sm.get(models.Secret, key)
            if secret and secret_params['update_if_exists']:
                get_resource_manager().validate_modification_permitted(
                    secret)
                secret.value = secret_params['value']
                secret.updated_at = timestamp
                return sm.update(secret)
            raise

    def _get_secret_params(self, key):
        request_dict = rest_utils.get_json_and_verify_params({
            'value': {'type': unicode},
            'update_if_exists': {'optional': True}
        })
        update_if_exists = rest_utils.verify_and_convert_bool(
            'update_if_exists',
            request_dict.get('update_if_exists', False),
        )
        rest_utils.validate_inputs({'key': key})
        availability_param = request_dict.get('availability', None)
        availability = get_resource_manager().get_resource_availability(
            models.Secret,
            key,
            availability_param
        )

        secret_params = {
            'value': request_dict['value'],
            'update_if_exists': update_if_exists,
            'availability': availability
        }
        return secret_params

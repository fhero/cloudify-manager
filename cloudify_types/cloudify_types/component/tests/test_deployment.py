# Copyright (c) 2017-2019 Cloudify Platform Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from cloudify.exceptions import NonRecoverableError

from ..operations import create, delete
from cloudify_types.component.component import Component
from .base_test_suite import (ComponentTestBase,
                              REST_CLIENT_EXCEPTION,
                              MOCK_TIMEOUT)


class TestDeploymentBase(ComponentTestBase):

    def setUp(self):
        super(TestDeploymentBase, self).setUp()
        self.sleep_mock = mock.patch('time.sleep', mock.MagicMock())
        self.sleep_mock.start()
        self._ctx.instance.runtime_properties['deployment'] = {}
        self._ctx.instance.runtime_properties['secrets'] = {}
        self._ctx.instance.runtime_properties['plugins'] = []

    def tearDown(self):
        self.sleep_mock.stop()
        super(TestDeploymentBase, self).tearDown()


class TestDeployment(TestDeploymentBase):
    def test_delete_deployment_rest_client_error(self):
        deployment_name = 'dep_name'
        self._ctx.instance.runtime_properties['deployment']['id'] =\
            deployment_name
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.deployments.delete = REST_CLIENT_EXCEPTION
            mock_client.return_value = self.cfy_mock_client
            error = self.assertRaises(NonRecoverableError,
                                      delete,
                                      deployment_id=deployment_name,
                                      timeout=MOCK_TIMEOUT)
            self.assertIn('action "delete" failed',
                          error.message)

    def test_delete_deployment_success(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.polling.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True
                output = delete(
                    operation='delete_deployment',
                    deployment_id='dep_name',
                    timeout=MOCK_TIMEOUT)
                self.assertTrue(output)

            assert not self.cfy_mock_client.secrets.delete.called
            assert not self.cfy_mock_client.plugins.delete.called
            self.assertEqual({}, self._ctx.instance.runtime_properties)

    def test_delete_deployment_any_dep_by_id(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            mock_client.return_value = self.cfy_mock_client
            output = delete(
                operation='delete_deployment',
                deployment_id='test_deployments_delete',
                timeout=MOCK_TIMEOUT)
            self.assertTrue(output)

    def test_create_deployment_rest_client_error(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.deployments.create = REST_CLIENT_EXCEPTION
            mock_client.return_value = self.cfy_mock_client
            error = self.assertRaises(NonRecoverableError,
                                      create,
                                      deployment_id='test_deployments_create',
                                      blueprint_id='test_deployments_create',
                                      timeout=MOCK_TIMEOUT)
            self.assertIn('action "create" failed',
                          error.message)

    def test_create_deployment_timeout(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.executions.set_existing_objects(
                [{
                    'id': 'exec_id',
                    'workflow_id': 'create_deployment_environment',
                    'deployment_id': 'dep'
                }])
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.polling.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = False
                error = self.assertRaises(
                    NonRecoverableError, create,
                    deployment_id='test_create_deployment_timeout',
                    blueprint_id='test',
                    timeout=MOCK_TIMEOUT)

                self.assertIn('Execution timed out', error.message)

    def test_create_deployment_success(self):
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.executions.set_existing_objects(
                [{
                    'id': 'exec_id',
                    'workflow_id': 'create_deployment_environment',
                    'deployment_id': 'dep'
                }])
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.component.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True

                output = create(operation='create_deployment',
                                timeout=MOCK_TIMEOUT)
                self.assertTrue(output)

    def test_create_deployment_failed(self):
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.executions.set_existing_objects(
                [{
                    'id': 'exec_id',
                    'workflow_id': 'test',
                    'deployment_id': 'dep'
                }])
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.polling.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True

                error = self.assertRaises(
                    NonRecoverableError,
                    create,
                    operation='create_deployment',
                    timeout=MOCK_TIMEOUT)

                self.assertIn('No execution Found for component'
                              ' \"test\" deployment', error.message)

    def test_create_deployment_exists(self):
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.deployments.set_existing_objects([
                {'id': 'dep'}])
            mock_client.return_value = self.cfy_mock_client
            output = create(operation='create_deployment',
                            timeout=MOCK_TIMEOUT)
            self.assertFalse(output)


class TestComponentPlugins(TestDeploymentBase):
    def test_upload_plugins(self):
        get_local_path = mock.Mock(return_value="some_path")

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            plugin = mock.Mock()
            plugin.id = "CustomPlugin"
            self.cfy_mock_client.plugins.upload = mock.Mock(
                return_value=plugin)

            mock_client.return_value = self.cfy_mock_client
            with mock.patch(
                'cloudify_types.component.component.get_local_path',
                get_local_path
            ):
                zip_files = mock.Mock(return_value="_zip")
                with mock.patch(
                    'cloudify_types.component.component.zip_files',
                    zip_files
                ):
                    # dist of plugins
                    component = Component({'plugins': {
                        'base_plugin': {
                            'wagon_path': '_wagon_path',
                            'plugin_yaml_path': '_plugin_yaml_path'}}})
                    os_mock = mock.Mock()
                    with mock.patch('cloudify_types.component.component.os',
                                    os_mock):
                        component._upload_plugins()
                    zip_files.assert_called_with(["some_path", "some_path"])
                    get_local_path.assert_has_calls([
                        mock.call('_wagon_path', create_temp=True),
                        mock.call('_plugin_yaml_path', create_temp=True)])
                    os_mock.remove.assert_has_calls([
                        mock.call('some_path'),
                        mock.call('some_path'),
                        mock.call('_zip')])

    def test_upload_empty_plugins(self):
        get_local_path = mock.Mock(return_value="some_path")

        with mock.patch('cloudify.manager.get_rest_client'):
            zip_files = mock.Mock(return_value="_zip")
            with mock.patch(
                'cloudify_types.component.component.zip_files',
                zip_files
            ):
                # empty plugins
                component = Component({'plugins': {}})
                component._upload_plugins()
                zip_files.assert_not_called()
                get_local_path.assert_not_called()

    def test_upload_plugins_with_wrong_format(self):
        with mock.patch('cloudify.manager.get_rest_client'):
            component = Component({'plugins': True})
            error = self.assertRaises(NonRecoverableError,
                                      component._upload_plugins)
            self.assertIn('Wrong type in plugins: True',
                          error.message)

            component = Component({'plugins': {
                'base_plugin': {
                    'wagon_path': '',
                    'plugin_yaml_path': ''}}})
            error = self.assertRaises(NonRecoverableError,
                                      component._upload_plugins)
            self.assertIn("You should provide both values wagon_path: '' "
                          "and plugin_yaml_path: ''", error.message)

    def test_delete_deployment_success_with_plugins(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'
        self._ctx.instance.runtime_properties['plugins'] = {'plugin_id'}

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.component.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True
                output = delete(
                    operation='delete_deployment',
                    deployment_id='dep_name',
                    timeout=MOCK_TIMEOUT)
                self.assertTrue(output)

            self.cfy_mock_client.plugins.delete.assert_called_with(
                plugin_id='plugin_id')


class TestComponentSecrets(TestDeploymentBase):
    def test_create_deployment_success_with_secrets(self):
        self._ctx.node.properties['secrets'] = {'a': 'b'}
        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            self.cfy_mock_client.executions.set_existing_objects(
                [{
                    'id': 'exec_id',
                    'workflow_id': 'create_deployment_environment',
                    'deployment_id': 'dep'
                }])

            self.cfy_mock_client.secrets.create = mock.Mock()
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.component.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True

                output = create(operation='create_deployment',
                                timeout=MOCK_TIMEOUT)
                self.assertTrue(output)

            self.cfy_mock_client.secrets.create.assert_called_with(key='a',
                                                                   value='b')

    def test_delete_deployment_success_with_secrets(self):
        self._ctx.instance.runtime_properties['deployment']['id'] = 'dep_name'
        self._ctx.instance.runtime_properties['secrets'] = {'a': 'b'}

        with mock.patch('cloudify.manager.get_rest_client') as mock_client:
            mock_client.return_value = self.cfy_mock_client

            poll_with_timeout_test = \
                'cloudify_types.component.component.poll_with_timeout'
            with mock.patch(poll_with_timeout_test) as poll:
                poll.return_value = True
                output = delete(
                    operation='delete_deployment',
                    deployment_id='dep_name',
                    timeout=MOCK_TIMEOUT)
                self.assertTrue(output)

            self.cfy_mock_client.secrets.delete.assert_called_with(key='a')
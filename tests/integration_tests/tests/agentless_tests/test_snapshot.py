########
# Copyright (c) 2013 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import time
import json
import pickle

import requests
from collections import Counter

from integration_tests.framework import docl
from integration_tests.framework import utils
from integration_tests import AgentlessTestCase
from integration_tests.framework import postgresql

from cloudify.snapshots import STATES
from cloudify.models_states import AgentState

from manager_rest.constants import DEFAULT_TENANT_NAME

from cloudify_rest_client.executions import Execution
from cloudify_rest_client.exceptions import CloudifyClientError

SNAPSHOTS = 'http://cloudify-tests-files.s3-eu-west-1.amazonaws.com/snapshots/'


class TestSnapshot(AgentlessTestCase):
    SNAPSHOT_ID = '0'
    REST_SEC_CONFIG_PATH = '/opt/manager/rest-security.conf'

    def setUp(self):
        super(TestSnapshot, self).setUp()
        self._save_security_config()
        self.addCleanup(self._restore_security_config)

    def test_4_4_snapshot_restore_with_bad_plugin_wgn_file(self):
        snapshot_path = \
            self._get_snapshot('snap_4_4_0_bad_plugin_wgn_file.zip')
        self._upload_and_restore_snapshot(
            snapshot_path,
            desired_execution_status=Execution.TERMINATED,
            error_execution_status=Execution.FAILED,
            ignore_plugin_failure=True)

        # Now make sure all the resources really exist in the DB
        # Assert snapshot restored
        self._assert_4_4_0_snapshot_restored_bad_plugin()

    def test_4_4_snapshot_restore_with_bad_plugin_no_directory(self):
        snapshot_path = \
            self._get_snapshot('snap_4_4_0_bad_plugin_no_directory.zip')
        self._upload_and_restore_snapshot(
            snapshot_path,
            desired_execution_status=Execution.TERMINATED,
            error_execution_status=Execution.FAILED,
            ignore_plugin_failure=True)

        # Now make sure all the resources really exist in the DB
        # Assert snapshot restored
        self._assert_4_4_0_snapshot_restored_bad_plugin()

    def test_4_4_snapshot_restore_with_bad_plugin_with_deps(self):
        snapshot_path = self._get_snapshot(
            'snap_4_4_0_bad_plugin_no_directory_with_deps.zip')
        self._upload_and_restore_snapshot(
            snapshot_path,
            desired_execution_status=Execution.TERMINATED,
            error_execution_status=Execution.FAILED,
            ignore_plugin_failure=True)

        # Now make sure all the resources really exist in the DB
        # Assert snapshot restored
        self._assert_4_4_0_snapshot_restored_bad_plugin(
            number_of_deployments=1)

    def test_4_4_snapshot_restore_with_bad_plugin_fails(self):
        snapshot_path = \
            self._get_snapshot('snap_4_4_0_bad_plugin_no_directory.zip')
        self._upload_and_restore_snapshot(
            snapshot_path,
            desired_execution_status=Execution.FAILED,
            error_execution_status=Execution.CANCELLED)

    def _assert_4_4_0_snapshot_restored_bad_plugin(
            self,
            tenant_name=DEFAULT_TENANT_NAME,
            number_of_deployments=0):
        self._assert_4_4_0_plugins_restored_bad_plugin(
            tenant_name=tenant_name,
            number_of_deployments=number_of_deployments
        )

    def test_v_4_3_restore_snapshot_with_secrets(self):
        """
        Validate the encryption of the secrets values for versions before 4.4.0
        """
        self._test_secrets_restored('snap_4.3.0_with_secrets.zip')

        # The secret's value is not hidden
        second_secret = self.client.secrets.get('sec2')
        assert second_secret.value == 'top_secret2'
        assert not second_secret.is_hidden_value

    def test_v_4_4_restore_snapshot_with_secrets(self):
        """
        Validate the restore of the secrets values for snapshot of 4.4.0
        """
        self._test_secrets_restored('snap_4.4.0_with_secrets.zip')

        # The secret's value is hidden
        second_secret = self.client.secrets.get('sec2')
        assert second_secret.value == 'top_secret2'
        assert second_secret.is_hidden_value

    def test_v_4_5_restore_snapshot_with_agents(self):
        """
        Validate the restore of agents
        """
        agents = self.client.agents.list()
        assert len(agents) == 0
        snapshot_path = self._get_snapshot('snap_4.5.0_with_agents.zip')
        self._upload_and_restore_snapshot(snapshot_path)
        states = [AgentState.STARTED, AgentState.RESTORED]
        agents = self.client.agents.list(state=states)
        self.assertEqual(len(agents), 3)
        first_agent = self.client.agents.get(agents[0].id)
        self.assertEqual(first_agent.state, AgentState.RESTORED)
        self.assertEqual(first_agent.rabbitmq_exchange, agents[0].id)
        self.assertIsNone(first_agent.rabbitmq_username)

    def test_v_4_5_restore_snapshot_without_imported_blueprints(self):
        """
        Validate deletion protection against imported blueprints is not applied
        to blueprints from 4.5.0 version down.
        """
        snapshot_path = self._get_snapshot('snap_4.5.0_with_blueprint.zip')
        # This snapshot only contain one blueprint.
        self._upload_and_restore_snapshot(snapshot_path)
        blueprints = self.client.blueprints.list(_include=['id'])
        self.client.blueprints.delete(blueprints[0]['id'])
        self.assertEqual(0,
                         len(self.client.blueprints.list(_include=['id'])))

    def test_v_4_5_5_restore_snapshot_with_executions(self):
        """
        Validate the restore of executions
        """
        snapshot_path = self._get_snapshot('snap_4.5.5_with_executions.zip')
        self._upload_and_restore_snapshot(snapshot_path)
        result = postgresql.run_query("SELECT workflow_id, token, "
                                      "blueprint_id FROM executions;")

        # The executions from the snapshot don't have a token or a blueprint_id
        for execution in result['all'][:3]:
            self.assertIsNone(execution[1])
            self.assertIsNone(execution[2])

        # The execution of the restore snapshot has a token
        token_4 = result['all'][5][1]
        self.assertIsNotNone(token_4)
        self.assertGreater(len(token_4), 10)
        self.assertEqual(result['all'][5][0], 'restore_snapshot')

    def test_v_4_6_0_restore_snapshot_and_restart_services(self):
        snapshot_path = self._get_snapshot('snap_4_6_0_hello_world.zip')
        self._upload_and_restore_snapshot(snapshot_path)
        docl.execute('cfy_manager restart --force')
        self.assertTrue(self._all_services_restarted_properly())

    def test_v_5_0_5_restore_snapshot(self):
        """ Validate the restore of new DB fields added in 5.0 or 5.0.5 """
        snapshot_path = \
            self._get_snapshot('snap_5.0.5_with_updated_deployment.zip')
        self._upload_and_restore_snapshot(snapshot_path)

        managers = postgresql.run_query("SELECT node_id FROM managers;")['all']
        self.assertGreater(len(managers[0][0]), 10)

        brokers = postgresql.run_query("SELECT is_external, node_id "
                                       "FROM rabbitmq_brokers;")['all']
        self.assertFalse(brokers[0][0])
        self.assertGreater(len(brokers[0][1]), 10)

    def test_v_5_0_5_restore_snapshot_with_executions(self):
        """
        Validate the restore of new DB fields added in 5.0 or 5.0.5 which
        relate to deployments and executions
        """
        snapshot_path = self._get_snapshot('snap_5.0.5_with_executions.zip')
        self._upload_and_restore_snapshot(snapshot_path)
        deployments = postgresql.run_query(
            "SELECT id, runtime_only_evaluation FROM deployments;"
        )['all']
        self.assertEqual(set(deployments[0]), {'hello-world', False})

        executions = postgresql.run_query("SELECT workflow_id, blueprint_id "
                                          "FROM executions;")['all']
        # executions of `create_deployment_environment` and `install` have
        # blueprint ids
        self.assertEqual(executions[0][0], 'install')
        self.assertEqual(executions[0][1], 'hello-world')
        self.assertEqual(executions[2][0], 'create_deployment_environment')
        self.assertEqual(executions[2][1], 'hello-world')

        # index added in 5.0.5. with only one instance per node, all indexes=1
        instances = postgresql.run_query("SELECT index "
                                         "FROM node_instances;")['all']
        for instance in instances:
            self.assertEqual(instance[0], 1)

    def test_v_5_0_5_restore_snapshot_with_updated_deployment(self):
        """
        Validate the restore of an updated deployment,
        with DB fields added in 5.0 or 5.0.5
        """
        snapshot_path = \
            self._get_snapshot('snap_5.0.5_with_updated_deployment.zip')
        self._upload_and_restore_snapshot(snapshot_path)

        dep_updates = postgresql.run_query(
            "SELECT central_plugins_to_install, central_plugins_to_uninstall,"
            "runtime_only_evaluation FROM deployment_updates;"
        )['all']

        plugins_to_install = pickle.loads(dep_updates[0][0])
        plugins_to_uninstall = pickle.loads(dep_updates[0][1])
        runtime_only_evaluation = dep_updates[0][2]
        for plug in plugins_to_install:
            self.assertEqual(plug['package_name'], 'cloudify-utilities-plugin')
            self.assertEqual(plug['package_version'], '1.14.0')
        self.assertListEqual(plugins_to_uninstall, [])
        self.assertFalse(runtime_only_evaluation)

    def test_v_5_0_5_restore_snapshot_and_inter_deployment_dependencies(self):
        snapshot_path = self._get_snapshot(
            'snap_5.0.5_with_component_openstack.zip')
        self._upload_and_restore_snapshot(snapshot_path)

        inter_deployment_dependencies = postgresql.run_query(
            "SELECT _source_deployment, _target_deployment,  "
            "dependency_creator FROM inter_deployment_dependencies;"
        )['all']

        assert (self._openstack_inter_deployment_dependencies()).issubset(
            set(inter_deployment_dependencies))

        self._assert_component_listed(inter_deployment_dependencies)

    @staticmethod
    def _assert_component_listed(inter_deployment_dependencies):
        if not any(d[2].startswith('component.infrastructure')
                   for d in inter_deployment_dependencies):
            raise AssertionError('component.infrastructure does not exist '
                                 'as a dependency creator.')

    @staticmethod
    def _openstack_inter_deployment_dependencies():
        dependency_creator_node = 'nodes.jboss.operations.cloudify.' \
                                       'interfaces.lifecycle.{0}.inputs.' \
                                       'fabric_env.{1}.get_capability'
        dependency_creator_input = 'nodes.jboss.operations.configure.inputs.' \
                                   'fabric_env.{0}.get_capability'

        return {
            (2, 3, dependency_creator_node.format('create', 'host_string')),
            (2, 3, dependency_creator_node.format('create', 'user')),
            (2, 3, dependency_creator_node.format('create', 'key')),
            (2, 3, dependency_creator_input.format('host_string')),
            (2, 3, dependency_creator_input.format('user')),
            (2, 3, dependency_creator_input.format('key')),
            (2, 3, dependency_creator_input.format('key')),
            (2, 3, dependency_creator_node.format('configure', 'host_string')),
            (2, 3, dependency_creator_node.format('configure', 'user')),
            (2, 3, dependency_creator_node.format('configure', 'key')),
            (2, 3, dependency_creator_node.format('start', 'host_string')),
            (2, 3, dependency_creator_node.format('start', 'user')),
            (2, 3, dependency_creator_node.format('start', 'key')),
            (2, 3, dependency_creator_node.format('stop', 'host_string')),
            (2, 3, dependency_creator_node.format('stop', 'user')),
            (2, 3, dependency_creator_node.format('stop', 'key')),
            (2, 3, 'outputs.admin_url.value.concat[1].get_capability'),
        }

    def test_snapshot_status_returns_correct_status(self):
        self._assert_restore_marker_file_does_not_exist()
        self._assert_snapshot_restore_status(is_running=False)

        snapshot_id = "test_snapshot_id"
        snapshot_create_execution = self.client.snapshots.create(
            snapshot_id, False)
        self.wait_for_execution_to_end(snapshot_create_execution)

        snapshot_restore_execution_id = self.client.snapshots.restore(
            snapshot_id).id
        self.client.maintenance_mode.activate()
        self._wait_for_restore_marker_file_to_be_created()
        self._assert_snapshot_restore_status(is_running=True)
        self.wait_for_snapshot_restore_to_end(snapshot_restore_execution_id)
        self.client.maintenance_mode.deactivate()

        self._assert_restore_marker_file_does_not_exist()
        self._assert_snapshot_restore_status(is_running=False)

    def _assert_restore_marker_file_does_not_exist(self):
        marker_file_exists = self._does_restore_marker_file_exists()
        self.assertFalse(marker_file_exists)

    def _assert_snapshot_restore_status(self, is_running):
        status_msg = STATES.RUNNING if is_running else STATES.NOT_RUNNING
        restore_status = self.client.snapshots.get_status()
        self.assertIn('status', restore_status)
        self.assertEquals(restore_status['status'], status_msg)

    def _all_services_restarted_properly(self):
        manager_status = self.client.manager.get_status()
        if manager_status['status'] == 'OK':
            self.logger.info('All processes restarted properly')
            return True
        for display_name, service in manager_status['services'].items():
            if service['status'] == 'Active':
                continue
            else:
                self.logger.error('The service `{}` did not restart properly'.
                                  format(service))
        return False

    def _test_secrets_restored(self, snapshot_name):
        snapshot_path = self._get_snapshot(snapshot_name)
        self._upload_and_restore_snapshot(snapshot_path)

        # The secrets values as in the snapshot
        secrets = self.client.secrets.list(_include=['key'])
        assert len(secrets) == 3
        secret_string = self.client.secrets.get('sec1')
        secret_file = self.client.secrets.get('sec3')
        assert secret_string.value == 'top_secret'
        assert 'test_mail' in secret_file.value

        # Validate the value is encrypted in the DB
        result = postgresql.run_query("SELECT value "
                                      "FROM secrets "
                                      "WHERE id='sec1';")
        secret_encrypted = result['all'][0][0]
        assert secret_encrypted != 'top_secret'

        # The secrets values are not hidden
        assert (not secret_string.is_hidden_value and
                not secret_file.is_hidden_value)

    def _assert_snapshot_restored(self,
                                  blueprint_id,
                                  deployment_id,
                                  node_ids,
                                  node_instance_ids,
                                  num_of_workflows,
                                  num_of_inputs,
                                  num_of_outputs,
                                  num_of_executions,
                                  num_of_events=4,
                                  tenant_name=DEFAULT_TENANT_NAME):
        with self.client_using_tenant(self.client, tenant_name):
            self.client.blueprints.get(blueprint_id)
        self._assert_deployment_restored(
            blueprint_id=blueprint_id,
            deployment_id=deployment_id,
            num_of_workflows=num_of_workflows,
            num_of_inputs=num_of_inputs,
            num_of_outputs=num_of_outputs,
            tenant_name=tenant_name
        )

        execution_id = self._assert_execution_restored(
            deployment_id,
            num_of_executions,
            tenant_name,
        )
        self._assert_events_restored(
            execution_id,
            num_of_events,
            tenant_name,
        )

        with self.client_using_tenant(self.client, tenant_name):
            for node_id in node_ids:
                self.client.nodes.get(deployment_id, node_id)
            for node_instance_id in node_instance_ids:
                self.client.node_instances.get(node_instance_id)

    def _assert_4_4_0_plugins_restored_bad_plugin(
            self,
            tenant_name=DEFAULT_TENANT_NAME,
            number_of_deployments=0):
        """
        Validate only 7 of the 8 plugins in the snapshot are being restored.
        Also, validating all deployments exist
        """
        with self.client_using_tenant(self.client, tenant_name):
            plugins = self.client.plugins.list()
            deployments = self.client.deployments.list()
        self.assertEqual(len(plugins), 7)
        self.assertEqual(len(deployments), number_of_deployments)
        package_names = [plugin.package_name for plugin in plugins]
        package_name_counts = Counter(package_names)
        self.assertEqual(package_name_counts['cloudify-fabric-plugin'], 1)
        self.assertEqual(package_name_counts['cloudify-script-plugin'], 1)
        self.assertEqual(package_name_counts['cloudify-diamond-plugin'], 5)

    def _assert_deployment_restored(self,
                                    blueprint_id,
                                    deployment_id,
                                    num_of_workflows,
                                    num_of_inputs,
                                    num_of_outputs,
                                    tenant_name):
        with self.client_using_tenant(self.client, tenant_name):
            deployment = self.client.deployments.get(deployment_id)
        self.assertEqual(deployment.id, deployment_id)
        self.assertEqual(len(deployment.workflows), num_of_workflows)
        self.assertEqual(deployment.blueprint_id, blueprint_id)
        self.assertEqual(deployment.created_by, 'admin')
        self.assertEqual(deployment['tenant_name'], tenant_name)
        self.assertEqual(len(deployment.inputs), num_of_inputs)
        self.assertEqual(len(deployment.outputs), num_of_outputs)

    def _assert_execution_restored(self,
                                   deployment_id,
                                   num_of_executions,
                                   tenant_name):
        def condition(execution):
            return execution.workflow_id == 'create_deployment_environment'

        with self.client_using_tenant(self.client, tenant_name):
            executions = self.client.executions.list(
                deployment_id=deployment_id
            )

        self.assertEqual(len(executions), num_of_executions)
        executions = [execution for execution
                      in executions if condition(execution)]
        self.assertEqual(len(executions), 1)
        return executions[0].id

    def _assert_events_restored(self,
                                execution_id,
                                num_of_events,
                                tenant_name):
        output = self.cfy.events.list(
            execution_id=execution_id,
            tenant_name=tenant_name
        )
        expected_output = 'Showing {0} of {0} events'.format(num_of_events)
        self.assertIn(expected_output, output)

    def _get_snapshot(self, name):
        snapshot_url = os.path.join(SNAPSHOTS, name)
        self.logger.info('Retrieving snapshot: {0}'.format(snapshot_url))
        tmp_file = os.path.join(self.workdir, name)
        return utils.download_file(snapshot_url, tmp_file)

    def _upload_and_restore_snapshot(
            self,
            snapshot_path,
            tenant_name=DEFAULT_TENANT_NAME,
            snapshot_id=None,
            desired_execution_status=Execution.TERMINATED,
            error_execution_status=Execution.FAILED,
            ignore_plugin_failure=False):
        """Upload the snapshot and launch the restore workflow
        """
        snapshot_id = snapshot_id or self.SNAPSHOT_ID
        rest_client = utils.create_rest_client(tenant=tenant_name)
        self._upload_and_validate_snapshot(snapshot_path,
                                           snapshot_id,
                                           rest_client)
        self.logger.debug('Restoring snapshot...')
        execution = rest_client.snapshots.restore(
            snapshot_id,
            ignore_plugin_failure=ignore_plugin_failure)
        rest_client.maintenance_mode.activate()
        self.wait_for_snapshot_restore_to_end(execution.id, client=rest_client)
        rest_client.maintenance_mode.deactivate()
        execution = self._wait_for_restore_execution_to_end(
            execution, rest_client, timeout_seconds=240)
        if execution.status == error_execution_status:
            self.logger.error('Execution error: {0}'.format(execution.error))
        self.assertEqual(desired_execution_status, execution.status)

    def _upload_and_validate_snapshot(self,
                                      snapshot_path,
                                      snapshot_id,
                                      rest_client):
        self.logger.debug('Uploading snapshot: {0}'.format(snapshot_path))
        rest_client.snapshots.upload(snapshot_path, snapshot_id)
        snapshot = rest_client.snapshots.get(snapshot_id)
        self.logger.debug('Retrieved snapshot: {0}'.format(snapshot))
        self.assertEquals(snapshot['id'], snapshot_id)
        self.assertEquals(snapshot['status'], 'uploaded')
        self.logger.info('Snapshot uploaded and validated')

    def _wait_for_restore_execution_to_end(
            self, execution, rest_client, timeout_seconds=120):
        """Can't use the `wait_for_execution_to_end` in the class because
         we need to be able to handle client errors
        """
        deadline = time.time() + timeout_seconds
        while execution.status not in Execution.END_STATES:
            time.sleep(0.5)
            # This might fail due to the fact that we're changing the DB in
            # real time - it's OK. Just try again
            try:
                execution = rest_client.executions.get(execution.id)
            except (requests.exceptions.ConnectionError, CloudifyClientError):
                pass
            if time.time() > deadline:
                raise utils.TimeoutException(
                    'Execution timed out: \n{0}'.format(
                        json.dumps(execution, indent=2)
                    )
                )
        return execution

    def _save_security_config(self):
        tmp_config_path = os.path.join(self.workdir, 'rest-security.conf')
        docl.copy_file_from_manager(self.REST_SEC_CONFIG_PATH, tmp_config_path)

    def _restore_security_config(self):
        tmp_config_path = os.path.join(self.workdir, 'rest-security.conf')
        docl.copy_file_to_manager(tmp_config_path,
                                  self.REST_SEC_CONFIG_PATH)
        docl.execute('chown cfyuser: {securityconf}'.format(
            securityconf=self.REST_SEC_CONFIG_PATH,
        ))
        self.restart_service('cloudify-restservice')

    def test_restore_snapshot_scheduled_tasks(self):
        """
        Validate workflow restoration from snapshot.

        This test uses a file with four scheduled transactions:
          - uninstall  at 2020-03-10 12:00:00+00:00
          - install    at 2020-03-11 12:00:00+00:00
          - install    at 2050-01-01 12:00:00+00:00
          - uninstall  at 2050-01-02 12:00:00+00:00
        """
        SNAPSHOTS_DIR = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'resources', 'snapshots')
        snapshot_path = os.path.join(SNAPSHOTS_DIR,
                                     'snap_with_scheduled_execs_20200310.zip')
        self._upload_and_restore_snapshot(snapshot_path)

        failed_executions = self.client.executions.list(
            status=Execution.FAILED
        )
        self.assertEqual(len(failed_executions), 2)

        executions = self.client.executions.list(status=Execution.SCHEDULED)
        self.assertEqual(len(executions), 2)

        for execution in executions:
            if execution.workflow_id == 'install':
                self.assertEqual(execution.scheduled_for,
                                 '2050-01-01T12:00:00.000Z')
            if execution.workflow_id == 'uninstall':
                self.assertEqual(execution.scheduled_for,
                                 '2050-01-02T12:00:00.000Z')

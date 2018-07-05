from asynctest import TestCase, mock
from aiosfstream import ReplayOption

from rabbit_force.factories import create_salesforce_org, \
    create_message_source, create_broker, create_message_sink, create_rule, \
    create_router, create_replay_storage


class TestCreateSalesforceOrg(TestCase):
    @mock.patch("rabbit_force.factories.SalesforceOrg")
    async def test_create(self, org_cls):
        name = "name"
        consumer_key = "key"
        consumer_secret = "secret"
        username = "username"
        password = "password"
        resource_spec = {"key": "value"}
        streaming_resource_specs = [resource_spec]
        org_mock = mock.MagicMock()
        org_mock.add_resource = mock.CoroutineMock()
        org_cls.return_value = org_mock

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = await create_salesforce_org(
                name=name,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                username=username,
                password=password,
                streaming_resource_specs=streaming_resource_specs,
                loop=self.loop
            )

        self.assertIs(result, org_mock)
        org_cls.assert_called_with(
            consumer_key,
            consumer_secret,
            username,
            password,
            loop=self.loop
        )
        org_mock.add_resource.assert_called_with(**resource_spec)
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating Salesforce org {name!r}",
            f"DEBUG:rabbit_force.factories:Adding resource to org {name!r}: "
            f"{resource_spec!r}"
        ])


class TestCreateMessageSource(TestCase):
    @mock.patch("rabbit_force.factories.ujson")
    @mock.patch("rabbit_force.factories.MultiMessageSource")
    @mock.patch("rabbit_force.factories.SalesforceOrgMessageSource")
    async def test_create(self, org_source_cls, multi_source_cls, ujson_mod):
        org_specs = {
            "org_name1": {
                "key1": "value1"
            },
            "org_name2": {
                "key2": "value2"
            }
        }
        org1 = object()
        org2 = object()
        org_factory = mock.CoroutineMock(side_effect=[org1, org2])
        org_source1 = object()
        org_source2 = object()
        org_source_cls.side_effect = [org_source1, org_source2]
        replay_spec = object()
        replay_storage1 = object()
        replay_storage2 = object()
        replay_storage_factory = mock.CoroutineMock(
            side_effect=((replay_storage1, ReplayOption.ALL_EVENTS),
                         (replay_storage2, ReplayOption.ALL_EVENTS))
        )
        ignore_replay_storage_errors = True
        connection_timeout = 20.0

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = await create_message_source(
                org_specs=org_specs,
                replay_spec=replay_spec,
                org_factory=org_factory,
                replay_storage_factory=replay_storage_factory,
                ignore_replay_storage_errors=ignore_replay_storage_errors,
                connection_timeout=connection_timeout,
                loop=self.loop
            )

        self.assertIs(result, multi_source_cls.return_value)
        org_factory.assert_has_calls([
            mock.call(**org_specs["org_name1"], name="org_name1"),
            mock.call(**org_specs["org_name2"], name="org_name2")
        ])
        replay_storage_factory.assert_has_calls([
            mock.call(replay_spec=replay_spec,
                      source_name="org_name1",
                      ignore_network_errors=ignore_replay_storage_errors,
                      loop=self.loop),
            mock.call(replay_spec=replay_spec,
                      source_name="org_name2",
                      ignore_network_errors=ignore_replay_storage_errors,
                      loop=self.loop)
        ])
        org_source_cls.assert_has_calls([
            mock.call("org_name1", org1, replay_storage1,
                      ReplayOption.ALL_EVENTS, connection_timeout,
                      json_dumps=ujson_mod.dumps, json_loads=ujson_mod.loads,
                      loop=self.loop),
            mock.call("org_name2", org2, replay_storage2,
                      ReplayOption.ALL_EVENTS, connection_timeout,
                      json_dumps=ujson_mod.dumps, json_loads=ujson_mod.loads,
                      loop=self.loop)
        ])
        multi_source_cls.assert_called_with([org_source1, org_source2],
                                            loop=self.loop)
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating Salesforce orgs",
            f"DEBUG:rabbit_force.factories:Creating message sources",
            f"DEBUG:rabbit_force.factories:Creating replay storage for "
            f"message source named 'org_name1'",
            f"DEBUG:rabbit_force.factories:Creating message source named "
            f"'org_name1' with replay storage {replay_storage1!r} and replay "
            f"fallback {ReplayOption.ALL_EVENTS!r}",
            f"DEBUG:rabbit_force.factories:Creating replay storage for "
            f"message source named 'org_name2'",
            f"DEBUG:rabbit_force.factories:Creating message source named "
            f"'org_name2' with replay storage {replay_storage2!r} and replay "
            f"fallback {ReplayOption.ALL_EVENTS!r}",
            f"DEBUG:rabbit_force.factories:Multiple message sources are "
            f"defined, creating a multi message source."
        ])

    @mock.patch("rabbit_force.factories.ujson")
    @mock.patch("rabbit_force.factories.MultiMessageSource")
    @mock.patch("rabbit_force.factories.SalesforceOrgMessageSource")
    async def test_create_single_source(self, org_source_cls,
                                        multi_source_cls, ujson_mod):
        org_specs = {
            "org_name1": {
                "key1": "value1"
            }
        }
        org1 = object()
        org_factory = mock.CoroutineMock(side_effect=[org1])
        org_source1 = object()
        org_source_cls.side_effect = [org_source1]
        replay_spec = object()
        replay_storage1 = object()
        replay_storage_factory = mock.CoroutineMock(
            return_value=(replay_storage1, ReplayOption.ALL_EVENTS)
        )
        ignore_replay_storage_errors = True
        connection_timeout = 20.0

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = await create_message_source(
                org_specs=org_specs,
                replay_spec=replay_spec,
                org_factory=org_factory,
                replay_storage_factory=replay_storage_factory,
                ignore_replay_storage_errors=ignore_replay_storage_errors,
                connection_timeout=connection_timeout,
                loop=self.loop
            )

        self.assertIs(result, org_source1)
        org_factory.assert_has_calls([
            mock.call(**org_specs["org_name1"], name="org_name1")
        ])
        replay_storage_factory.assert_has_calls([
            mock.call(replay_spec=replay_spec,
                      source_name="org_name1",
                      ignore_network_errors=ignore_replay_storage_errors,
                      loop=self.loop)
        ])
        org_source_cls.assert_has_calls([
            mock.call("org_name1", org1, replay_storage1,
                      ReplayOption.ALL_EVENTS, connection_timeout,
                      json_loads=ujson_mod.loads, json_dumps=ujson_mod.dumps,
                      loop=self.loop)
        ])
        multi_source_cls.assert_not_called()
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating Salesforce orgs",
            f"DEBUG:rabbit_force.factories:Creating message sources",
            f"DEBUG:rabbit_force.factories:Creating replay storage for "
            f"message source named 'org_name1'",
            f"DEBUG:rabbit_force.factories:Creating message source named "
            f"'org_name1' with replay storage {replay_storage1!r} and replay "
            f"fallback {ReplayOption.ALL_EVENTS!r}",
            f"DEBUG:rabbit_force.factories:Only a single message source is "
            f"defined, using it as the main message source."
        ])


class TestCreateBroker(TestCase):
    @mock.patch("rabbit_force.factories.AmqpBroker")
    async def test_create(self, broker_cls):
        name = "name"
        host = "host"
        exchange_specs = [{"key": "value"}]
        port = 1234
        login = "login"
        password = "password"
        virtualhost = "virt_host"
        ssl = True
        login_method = "plain"
        insist = True
        verify_ssl = True
        broker = mock.MagicMock()
        broker.exchange_declare = mock.CoroutineMock()
        broker_cls.return_value = broker

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = await create_broker(
                name=name,
                host=host,
                exchange_specs=exchange_specs,
                port=port,
                login=login,
                password=password,
                virtualhost=virtualhost,
                ssl=ssl,
                login_method=login_method,
                insist=insist,
                verify_ssl=verify_ssl,
                loop=self.loop
            )

        self.assertEqual(result, broker)
        broker_cls.assert_called_with(
            host, port=port, login=login, password=password,
            virtualhost=virtualhost, ssl=ssl, login_method=login_method,
            insist=insist, verify_ssl=verify_ssl, loop=self.loop
        )
        broker.exchange_declare.assert_called_with(**exchange_specs[0])
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating message broker {name!r}",
            f"DEBUG:rabbit_force.factories:Declaring exchange in broker "
            f"{name!r}: {exchange_specs[0]!r}"
        ])


class TestCreateMessageSink(TestCase):
    @mock.patch("rabbit_force.factories.ujson")
    @mock.patch("rabbit_force.factories.MultiMessageSink")
    async def test_create(self, multi_sink_cls, ujson_mod):
        broker_specs = {
            "broker1": {
                "key": "value"
            }
        }
        broker = object()
        broker_factory = mock.CoroutineMock(return_value=broker)
        message_sink = object()
        broker_sink_factory = mock.MagicMock(return_value=message_sink)

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = await create_message_sink(
                broker_specs=broker_specs,
                broker_factory=broker_factory,
                broker_sink_factory=broker_sink_factory,
                loop=self.loop
            )

        self.assertIs(result, multi_sink_cls.return_value)
        broker_factory.assert_called_with(**broker_specs["broker1"],
                                          name="broker1",
                                          loop=self.loop)
        broker_sink_factory.assert_called_with(broker,
                                               json_dumps=ujson_mod.dumps)
        multi_sink_cls.assert_called_with(
            {"broker1": message_sink}, loop=self.loop
        )
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.factories:Creating message brokers",
            "DEBUG:rabbit_force.factories:Creating message sinks",
            "DEBUG:rabbit_force.factories:Creating multi message sink as the "
            "main message sink"
        ])


class TestCreateRule(TestCase):
    @mock.patch("rabbit_force.factories.RoutingRule")
    def test_create(self, rule_cls):
        condition_factory = mock.MagicMock()
        route_factory = mock.MagicMock()
        condition_spec = object()
        route_spec = {"key": "value"}

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = create_rule(
                condition_spec=condition_spec,
                route_spec=route_spec,
                condition_factory=condition_factory,
                route_factory=route_factory
            )

        self.assertIs(result, rule_cls.return_value)
        condition_factory.assert_called_with(condition_spec)
        route_factory.assert_called_with(**route_spec)
        rule_cls.assert_called_with(condition_factory.return_value,
                                    route_factory.return_value)
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating routing rule with "
            f"condition {condition_spec!r} and route {route_spec!r}"
        ])


class TestCreateRouter(TestCase):
    @mock.patch("rabbit_force.factories.MessageRouter")
    def test_create(self, router_cls):
        route_factory = mock.MagicMock()
        rule_factory = mock.MagicMock()
        default_route_spec = {"key": "value"}
        rule = {"rule_key": "rule_value"}
        rule_specs = [rule]

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = create_router(
                default_route_spec=default_route_spec,
                rule_specs=rule_specs,
                route_factory=route_factory,
                rule_factory=rule_factory
            )

        self.assertIs(result, router_cls.return_value)
        route_factory.assert_called_with(**default_route_spec)
        rule_factory.assert_called_with(**rule)
        router_cls.assert_called_with(route_factory.return_value,
                                      [rule_factory.return_value])
        self.assertEqual(log.output, [
            f"DEBUG:rabbit_force.factories:Creating default route: "
            f"{default_route_spec!r}",
            "DEBUG:rabbit_force.factories:Creating routing rules",
            "DEBUG:rabbit_force.factories:Creating message router object"
        ])

    @mock.patch("rabbit_force.factories.MessageRouter")
    def test_create_without_default_route(self, router_cls):
        route_factory = mock.MagicMock()
        rule_factory = mock.MagicMock()
        default_route_spec = None
        rule = {"rule_key": "rule_value"}
        rule_specs = [rule]

        with self.assertLogs("rabbit_force.factories", "DEBUG") as log:
            result = create_router(
                default_route_spec=default_route_spec,
                rule_specs=rule_specs,
                route_factory=route_factory,
                rule_factory=rule_factory
            )

        self.assertIs(result, router_cls.return_value)
        route_factory.assert_not_called()
        rule_factory.assert_called_with(**rule)
        router_cls.assert_called_with(None, [rule_factory.return_value])
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.factories:No default route is defined",
            "DEBUG:rabbit_force.factories:Creating routing rules",
            "DEBUG:rabbit_force.factories:Creating message router object"
        ])


class TestCreateReplayStorage(TestCase):
    async def test_create_no_replay_spec(self):
        replay_spec = None
        source_name = "name"

        result = await create_replay_storage(
            replay_spec=replay_spec,
            source_name=source_name,
            loop=self.loop
        )

        self.assertEqual(result[0], ReplayOption.NEW_EVENTS)
        self.assertIsNone(result[1])

    @mock.patch("rabbit_force.factories.RedisReplayStorage")
    async def test_create_with_replay_spec(self, replay_cls):
        replay_spec = {
            "address": "address",
            "key_prefix": "prefix"
        }
        source_name = "name"
        ignore_network_errors = True
        replay = object()
        replay_cls.return_value = replay

        result = await create_replay_storage(
            replay_spec=replay_spec,
            source_name=source_name,
            ignore_network_errors=ignore_network_errors,
            loop=self.loop
        )

        self.assertIs(result[0], replay)
        self.assertEqual(result[1], ReplayOption.ALL_EVENTS)
        replay_cls.assert_called_with(
            address="address",
            key_prefix="prefix:name",
            ignore_network_errors=ignore_network_errors,
            loop=self.loop
        )

    @mock.patch("rabbit_force.factories.RedisReplayStorage")
    async def test_create_with_replay_spec_without_prefix(self, replay_cls):
        replay_spec = {
            "address": "address"
        }
        source_name = "name"
        ignore_network_errors = True
        replay = object()
        replay_cls.return_value = replay

        result = await create_replay_storage(
            replay_spec=replay_spec,
            source_name=source_name,
            ignore_network_errors=ignore_network_errors,
            loop=self.loop
        )

        self.assertIs(result[0], replay)
        self.assertEqual(result[1], ReplayOption.ALL_EVENTS)
        replay_cls.assert_called_with(
            address="address",
            key_prefix="name",
            ignore_network_errors=ignore_network_errors,
            loop=self.loop
        )

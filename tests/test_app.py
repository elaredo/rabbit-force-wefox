import asyncio
import signal

from asynctest import TestCase, mock

from rabbit_force.app import Application, SourceMessagePair
from rabbit_force.routing import Route
from rabbit_force.exceptions import MessageSinkError


class TestApplication(TestCase):
    def setUp(self):
        self.config = object()
        self.ignore_replay_storage_errors = True
        self.ignore_sink_errors = True
        self.source_connection_timeout = 20
        self.app = Application(
            self.config,
            ignore_replay_storage_errors=self.ignore_replay_storage_errors,
            ignore_sink_errors=self.ignore_sink_errors,
            source_connection_timeout=self.source_connection_timeout
        )
        self.app._loop = self.loop

    def test_init(self):
        self.assertIs(self.app.config, self.config)
        self.assertEqual(self.app.ignore_replay_storage_errors,
                         self.ignore_replay_storage_errors)
        self.assertEqual(self.app.ignore_sink_errors,
                         self.ignore_sink_errors)
        self.assertEqual(self.app.source_connection_timeout,
                         self.source_connection_timeout)
        self.assertIsNone(self.app._source)
        self.assertIsNone(self.app._sink)
        self.assertIsNone(self.app._router)
        self.assertFalse(self.app._configured)
        self.assertEqual(self.app._forwarding_tasks, {})
        self.assertIs(self.app._loop, self.loop)

    async def test__run(self):
        self.app._configure = mock.CoroutineMock()
        self.app._listen_for_messages = mock.CoroutineMock()

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            await self.app._run()

        self.app._configure.assert_called()
        self.app._listen_for_messages.assert_called()
        self.assertEqual(log.output, [
            "INFO:rabbit_force.app:Configuring application ...",
            "DEBUG:rabbit_force.app:Start listening for messages"
        ])

    @mock.patch("rabbit_force.app.create_message_source")
    @mock.patch("rabbit_force.app.create_message_sink")
    @mock.patch("rabbit_force.app.create_router")
    async def test_configure(self, create_router, create_message_sink,
                             create_message_source):
        self.app.config = {
            "source": {"key1": "value1"},
            "sink": {"key2": "value2"},
            "router": {"key3": "value3"}
        }

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            await self.app._configure()

        create_message_source.assert_called_with(
            **self.app.config["source"],
            ignore_replay_storage_errors=self.ignore_replay_storage_errors,
            connection_timeout=self.source_connection_timeout,
            loop=self.loop
        )
        create_message_sink.assert_called_with(
            **self.app.config["sink"],
            loop=self.loop
        )
        create_router.assert_called_with(**self.app.config["router"])
        self.assertTrue(self.app._configured)
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.app:Creating message source from "
            "configuration",
            "DEBUG:rabbit_force.app:Creating message sink from configuration",
            "DEBUG:rabbit_force.app:Creating message router from configuration"
        ])

    @mock.patch("rabbit_force.app.asyncio")
    async def test_schedule_message_forwarding(self, asyncio_mod):
        self.app._loop = self.loop
        coro = object()
        self.app._forward_message = mock.MagicMock(return_value=coro)
        task = mock.MagicMock()
        asyncio_mod.ensure_future.return_value = task
        source_name = "source"
        message = object()

        await self.app._schedule_message_forwarding(source_name, message)

        self.app._forward_message.assert_called_with(source_name, message)
        asyncio_mod.ensure_future.assert_called_with(coro, loop=self.loop)
        task.add_done_callback.assert_called_with(
            self.app._forward_message_done
        )
        self.assertEqual(self.app._forwarding_tasks,
                         {task: SourceMessagePair(source_name, message)})

    @mock.patch("rabbit_force.app.asyncio")
    async def test_wait_scheduled_forwarding_tasks(self, asyncio_mod):
        self.app._loop = self.loop
        self.app._forwarding_tasks = {object(): object()}
        asyncio_mod.wait = mock.CoroutineMock()

        await self.app._wait_scheduled_forwarding_tasks()

        asyncio_mod.wait.assert_called_with(self.app._forwarding_tasks,
                                            loop=self.loop)

    @mock.patch("rabbit_force.app.asyncio")
    async def test_wait_scheduled_forwarding_tasks_without_tasks(self,
                                                                 asyncio_mod):
        self.app._loop = self.loop
        self.app._forwarding_tasks = {}
        asyncio_mod.wait = mock.CoroutineMock()

        await self.app._wait_scheduled_forwarding_tasks()

        asyncio_mod.wait.assert_not_called()

    async def test_forward_message(self):
        self.app._router = mock.MagicMock()
        route = Route(broker_name="broker", exchange_name="exchange",
                      routing_key="key", properties={})
        self.app._router.find_route.return_value = route
        self.app._sink = mock.MagicMock()
        self.app._sink.consume_message = mock.CoroutineMock()
        source_name = "source"
        message = object()

        result = await self.app._forward_message(source_name, message)

        self.assertEqual(result, route)
        self.app._router.find_route.assert_called_with(source_name, message)
        self.app._sink.consume_message.assert_called_with(
            message, route.broker_name, route.exchange_name, route.routing_key,
            route.properties
        )

    async def test_forward_message_without_route(self):
        self.app._router = mock.MagicMock()
        route = None
        self.app._router.find_route.return_value = route
        self.app._sink = mock.MagicMock()
        self.app._sink.consume_message = mock.CoroutineMock()
        source_name = "source"
        message = object()

        result = await self.app._forward_message(source_name, message)

        self.assertEqual(result, route)
        self.app._router.find_route.assert_called_with(source_name, message)
        self.app._sink.consume_message.assert_not_called()

    def test_forward_message_done(self):
        future = mock.MagicMock()
        replay_id = 12
        channel = "channel"
        message = {
            "channel": channel,
            "data": {"event": {"replayId": replay_id}}
        }
        source_name = "source"
        route = object()
        future.result.return_value = route
        self.app._forwarding_tasks = {future: SourceMessagePair(source_name,
                                                                message)}

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            self.app._forward_message_done(future)

        self.assertEqual(log.output, [
            f"INFO:rabbit_force.app:Forwarded message {replay_id!r} on "
            f"channel {channel!r} from {source_name!r} to {route!r}."
        ])
        self.assertFalse(self.app._forwarding_tasks)

    def test_forward_message_done_without_route(self):
        future = mock.MagicMock()
        replay_id = 12
        channel = "channel"
        message = {
            "channel": channel,
            "data": {"event": {"replayId": replay_id}}
        }
        source_name = "source"
        route = None
        future.result.return_value = route
        self.app._forwarding_tasks = {future: SourceMessagePair(source_name,
                                                                message)}

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            self.app._forward_message_done(future)

        self.assertEqual(log.output, [
            f"WARNING:rabbit_force.app:Dropped message {replay_id!s} on "
            f"channel {channel!r} from {source_name!r}, no route found."
        ])
        self.assertFalse(self.app._forwarding_tasks)

    def test_forward_message_done_on_error(self):
        future = mock.MagicMock()
        replay_id = 12
        channel = "channel"
        message = {
            "channel": channel,
            "data": {"event": {"replayId": replay_id}}
        }
        source_name = "source"
        future.result.side_effect = TypeError()
        self.app._forwarding_tasks = {future: SourceMessagePair(source_name,
                                                                message)}

        with self.assertRaises(TypeError):
            self.app._forward_message_done(future)

        self.assertFalse(self.app._forwarding_tasks)

    def test_forward_message_done_on_sink_error(self):
        future = mock.MagicMock()
        replay_id = 12
        channel = "channel"
        message = {
            "channel": channel,
            "data": {"event": {"replayId": replay_id}}
        }
        source_name = "source"
        error = MessageSinkError("message")
        future.result.side_effect = error
        self.app._forwarding_tasks = {future: SourceMessagePair(source_name,
                                                                message)}

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            self.app._forward_message_done(future)

        self.assertEqual(log.output, [
            f"ERROR:rabbit_force.app:Dropped message {replay_id!s} on channel "
            f"{channel!r} from {source_name!r}. {error!s}"
        ])
        self.assertFalse(self.app._forwarding_tasks)

    def test_forward_message_done_on_sink_error_not_ignored(self):
        self.app.ignore_sink_errors = False
        future = mock.MagicMock()
        replay_id = 12
        channel = "channel"
        message = {
            "channel": channel,
            "data": {"event": {"replayId": replay_id}}
        }
        source_name = "source"
        error = MessageSinkError("message")
        future.result.side_effect = error
        self.app._forwarding_tasks = {future: SourceMessagePair(source_name,
                                                                message)}

        with self.assertRaisesRegex(MessageSinkError, str(error)):
            self.app._forward_message_done(future)

    @mock.patch("rabbit_force.app.uvloop")
    @mock.patch("rabbit_force.app.asyncio")
    async def test_run(self, asyncio_mod, uvloop_mod):
        task = mock.MagicMock()
        asyncio_mod.ensure_future.return_value = task
        self.app._run = mock.MagicMock()
        loop = mock.MagicMock()
        loop.run_until_complete.side_effect = (KeyboardInterrupt, None)
        asyncio_mod.get_event_loop.return_value = loop

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            self.app.run()

        asyncio_mod.set_event_loop_policy.assert_called_with(
            uvloop_mod.EventLoopPolicy.return_value
        )
        self.assertEqual(self.app._loop, loop)
        asyncio_mod.ensure_future.assert_called_with(
            self.app._run.return_value, loop=loop
        )
        task.cancel.assert_called()
        loop.run_until_complete.assert_has_calls([mock.call(task)] * 2)
        loop.add_signal_handler.assert_called_with(
            signal.SIGTERM,
            self.app._on_termination_signal,
            task
        )
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.app:Starting event loop",
            "DEBUG:rabbit_force.app:Received keyboard interrupt",
            "DEBUG:rabbit_force.app:Event loop terminated"
        ])

    async def test_listen_for_messages(self):
        source = mock.MagicMock()
        closed = mock.PropertyMock(side_effect=(False, True, True))
        type(source).closed = closed
        has_pending_messages = mock.PropertyMock(side_effect=(True, False))
        type(source).has_pending_messages = has_pending_messages
        source.close = mock.CoroutineMock()
        source.open = mock.CoroutineMock()
        self.app._source = source
        message1 = object()
        message2 = object()
        source1 = object()
        source2 = object()
        source.get_message = mock.CoroutineMock(
            side_effect=((source1, message1), (source2, message2))
        )
        self.app._schedule_message_forwarding = mock.CoroutineMock()
        self.app._wait_scheduled_forwarding_tasks = mock.CoroutineMock()
        self.app._sink = mock.MagicMock()
        self.app._sink.close = mock.CoroutineMock()

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            await self.app._listen_for_messages()

        source.open.assert_called()
        self.assertEqual(self.app._schedule_message_forwarding.mock_calls, [
            mock.call(source1, message1),
            mock.call(source2, message2)
        ])
        source.close.assert_called()
        self.app._wait_scheduled_forwarding_tasks.assert_called()
        self.app._sink.close.assert_called()
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.app:Opening message source",
            "DEBUG:rabbit_force.app:Waiting for incoming messages",
            f"DEBUG:rabbit_force.app:Received incoming message from source "
            f"{source1!s}, scheduling message forwarding",
            f"DEBUG:rabbit_force.app:Received incoming message from source "
            f"{source2!s}, scheduling message forwarding",
            "DEBUG:rabbit_force.app:Closing message source",
            "DEBUG:rabbit_force.app:Waiting for running forwarding tasks to "
            "complete",
            "DEBUG:rabbit_force.app:Closing message sink"
        ])

    async def test_listen_for_messages_cancelled(self):
        source = mock.MagicMock()
        closed = mock.PropertyMock(side_effect=(False, False, True, True))
        type(source).closed = closed
        has_pending_messages = mock.PropertyMock(side_effect=(True, False))
        type(source).has_pending_messages = has_pending_messages
        source.close = mock.CoroutineMock()
        source.open = mock.CoroutineMock()
        self.app._source = source
        message1 = object()
        message2 = object()
        source1 = object()
        source2 = object()
        source.get_message = mock.CoroutineMock(
            side_effect=((source1, message1), asyncio.CancelledError(),
                         (source2, message2))
        )
        self.app._schedule_message_forwarding = mock.CoroutineMock()
        self.app._wait_scheduled_forwarding_tasks = mock.CoroutineMock()
        self.app._sink = mock.MagicMock()
        self.app._sink.close = mock.CoroutineMock()

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            await self.app._listen_for_messages()

        source.open.assert_called()
        self.assertEqual(self.app._schedule_message_forwarding.mock_calls, [
            mock.call(source1, message1),
            mock.call(source2, message2)
        ])
        source.close.assert_called()
        self.app._wait_scheduled_forwarding_tasks.assert_called()
        self.app._sink.close.assert_called()
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.app:Opening message source",
            "DEBUG:rabbit_force.app:Waiting for incoming messages",
            f"DEBUG:rabbit_force.app:Received incoming message from source "
            f"{source1!s}, scheduling message forwarding",
            "DEBUG:rabbit_force.app:Canceling wait for incoming messages",
            "INFO:rabbit_force.app:Shutting down ...",
            f"DEBUG:rabbit_force.app:Received incoming message from source "
            f"{source2!s}, scheduling message forwarding",
            "DEBUG:rabbit_force.app:Closing message source",
            "DEBUG:rabbit_force.app:Waiting for running forwarding tasks to "
            "complete",
            "DEBUG:rabbit_force.app:Closing message sink"
        ])

    def test_on_termination_signal(self):
        task = mock.MagicMock()

        with self.assertLogs("rabbit_force.app", "DEBUG") as log:
            self.app._on_termination_signal(task)

        task.cancel.assert_called()
        self.assertEqual(log.output, [
            "DEBUG:rabbit_force.app:Received termination signal"
        ])

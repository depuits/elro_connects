import logging

import trio
from distmqtt.client import open_mqttclient
from distmqtt.mqtt.constants import QOS_1
from valideer import accepts, Pattern

from elro.validation import ip_address, hostname


class MQTTPublisher:
    """
    A MQTTPublisher listens to all hub events and publishes messages to an MQTT broker accordingly
    """
    @accepts(broker_host=Pattern(f"({ip_address}|{hostname})"),
             base_topic=Pattern("^[/_\\-a-zA-Z0-9]*$"))
    def __init__(self, broker_host, base_topic=None):
        """
        Constructor
        :param broker_host: The MQTT broker host or ip
        :param base_topic: The base topic to publish under, i.e., the publisher publishes messages under
                           <base topic>/elro/<device name or id>
        """
        self.broker_host = broker_host
        if not self.broker_host.startswith("mqtt://"):
            self.broker_host = f"mqtt://{self.broker_host}"

        if base_topic is None:
            self.base_topic = ""
        else:
            self.base_topic = base_topic

    def topic(self, last_hierarchy):
        """
        The topic name for a given hierarchy endpoint
        :param last_hierarchy: The last part of the topic
        """
        return f"{self.base_topic}/elro/{last_hierarchy}"

    def topic_name(self, device):
        """
        The topic name for a given device
        :param device: The device to get the topic name for
        """
        if device.name == "":
            last_hierarchy = device.id
        else:
            last_hierarchy = device.name

        return self.topic(last_hierarchy)

    async def device_alarm_task(self, device):
        """
        The main loop for handling alarm events
        :param device: The device to handle alarm events for.
        """
        while True:
            await self.handle_device_alarm(device)

    async def handle_device_alarm(self, device):
        """
        Listens for a device's alarm event and publishes a message on arrival.
        :param device: The device to listen to
        """
        await device.alarm.wait()
        topic = self.topic_name(device)
        logging.info(f"Publish on '{topic}':\n"
                     f"alarm")

        await self.client.publish(topic,
                             b'alarm',
                             QOS_1)

    async def device_update_task(self, device):
        """
        The main loop for handling device updates
        :param device: The device to listen to update events for
        """
        while True:
            await self.handle_device_update(device)

    async def handle_device_update(self, device):
        """
        Listens to a device's update events and publish a message on arrival
        :param device: The device to listen for updates for
        """
        await device.updated.wait()
        topic = self.topic_name(device)
        logging.info(f"Publish on '{topic}':\n"
                     f"{device.json.encode('utf-8')}")

        await self.client.publish(topic,
                             device.json.encode('utf-8'),
                             QOS_1)

    async def handle_hub_events(self, hub):
        """
        Main loop to handle all device events
        :param hub: The hub to listen for devices
        """
        config = {
            'uri': self.broker_host,
            'will': {
                'topic': self.topic('status'),
                'message': b'offline',
                'qos': 0x01,
                'retain': True,
            }
        }

        async with open_mqttclient(config=config) as self.client:
            await self.client.publish(self.topic('status'),
                                b'online',
                                QOS_1,
                                retain=True)

            async with trio.open_nursery() as nursery:
                async for device_id in hub.new_device_receive_ch:
                    logging.info(f"New device registered: {hub.devices[device_id]}")
                    nursery.start_soon(self.device_update_task, hub.devices[device_id])
                    nursery.start_soon(self.device_alarm_task, hub.devices[device_id])

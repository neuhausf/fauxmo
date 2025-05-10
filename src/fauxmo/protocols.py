"""protocols.py :: Provide asyncio protocols for UPnP and SSDP discovery."""

from __future__ import annotations

import asyncio
import random
import typing as t
import uuid
import time
from email.utils import formatdate
from typing import cast

from fauxmo import logger
from fauxmo.plugins import FauxmoPlugin
from fauxmo.utils import make_serial


class Fauxmo(asyncio.Protocol):
    """Mimics a WeMo switch on the network.

    Aysncio protocol intended for use with BaseEventLoop.create_server.
    """

    NEWLINE = "\r\n"

    def __init__(self, name: str, plugin: FauxmoPlugin) -> None:
        """Initialize a Fauxmo device.

        Args:
            name: How you want to call the device, e.g. "bedroom light"
            plugin: Fauxmo plugin

        """
        self.name = name
        self.serial = make_serial(name)
        self.plugin = plugin
        self.transport: asyncio.Transport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Accept an incoming TCP connection.

        Args:
            transport: Passed in asyncio.Transport

        """
        peername = transport.get_extra_info("peername")
        logger.debug(f"Connection made with: {peername}")
        self.transport = cast(asyncio.Transport, transport)

    def data_received(self, data: bytes) -> None:
        """Decode incoming data.

        Args:
            data: Incoming message, either setup request or action request

        """
        msg = data.decode()
        #addr = self.transport.get_extra_info("peername")
        
        #if "192.168.1.211" in addr:
        logger.debug(f"Received message:\n{msg}")
        
        if msg.startswith("GET /setup.xml HTTP/1.1"):
            logger.info("setup.xml requested by Echo")
            self.handle_setup()
        elif "/eventservice.xml" in msg:
            logger.info("eventservice.xml request by Echo")
            self.handle_event()
        elif "/metainfoservice.xml" in msg:
            logger.info("metainfoservice.xml request by Echo")
            self.handle_metainfo()
        elif "/insightservice.xml" in msg:
            logger.info("insightservice.xml request by Echo")
            self.handle_insight()
        elif (
            msg.startswith("POST") 
            and "/upnp/control/insight1 HTTP/1.1" in msg
        ):
            logger.info("request insight1")
            self.handle_action(msg)
        elif (
            msg.startswith("POST") 
            and "/upnp/control/timesync1 HTTP/1.1" in msg
        ):
            logger.info("request TimeSync1")
            self.handle_timesync_command(msg)
        elif (
            msg.startswith("POST") 
            and "/upnp/control/basicevent1 HTTP/1.1" in msg
        ):
            logger.info("request BasicEvent1")
            self.handle_action(msg)

    def handle_timesync_command(self, msg: str) -> None:
        """Respond to request for timesync."""
        if not self.transport:
            raise Exception("No transport")
        
        soap_format = (
            "<s:Envelope "
            'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body>"
            "<u:TimeSyncResponse "
            'xmlns:u="urn:Belkin:service:timesync:1">'
            "<UTC>{return_val}</UTC>"
            "</u:TimeSyncResponse>"
            "</s:Body>"
            "</s:Envelope>"
        ).format
        
        soap_message = soap_format(
            return_val=int(time.time()) 
        )
        timesync_response = self.add_http_headers(soap_message)
        logger.debug(f"Fauxmo response to timesync request:\n{timesync_response}")
        self.transport.write(timesync_response.encode())
        self.transport.close()
        
    def handle_setup(self) -> None:
        """Create a response to the Echo's setup request."""
        setup_xml = (
            '<?xml version="1.0"?>'
            '<root xmlns="urn:Belkin:device-1-0">'
            "<specVersion><major>1</major><minor>0</minor></specVersion>"
            "<device>"
            "<deviceType>urn:Belkin:device:insight:1</deviceType>"
            f"<friendlyName>{self.name}</friendlyName>"
            "<manufacturer>Belkin International Inc.</manufacturer>"
            "<modelName>Insight</modelName>"
            "<modelNumber>1.0</modelNumber>"
            f"<serialNumber>{self.serial}</serialNumber>"
            f"<UDN>uuid:Insight-1_0-{self.serial}</UDN>"
            "<UPC>123456789</UPC>"
            "<macAddress>001122334455</macAddress>"
            "<firmwareVersion>WeMo_WW_2.00.11532.PVT-OWRT-InsightV2</firmwareVersion>"
            "<iconVersion>3|49153</iconVersion>"
            "<binaryState>0</binaryState>"
            "<binaryOption>1</binaryOption>"
            "<serviceList>"
            "<service>"
            "<serviceType>urn:Belkin:service:basicevent:1</serviceType>"
            "<serviceId>urn:Belkin:serviceId:basicevent1</serviceId>"
            "<controlURL>/upnp/control/basicevent1</controlURL>"
            "<eventSubURL>/upnp/event/basicevent1</eventSubURL>"
            "<SCPDURL>/eventservice.xml</SCPDURL>"
            "</service>"
            "<service>"
            "<serviceType>urn:Belkin:service:metainfo:1</serviceType>"
            "<serviceId>urn:Belkin:serviceId:metainfo1</serviceId>"
            "<controlURL>/upnp/control/metainfo1</controlURL>"
            "<eventSubURL>/upnp/event/metainfo1</eventSubURL>"
            "<SCPDURL>/metainfoservice.xml</SCPDURL>"
            "</service>"
            "<service>"
            "<serviceType>urn:Belkin:service:insight:1</serviceType>"
            "<serviceId>urn:Belkin:serviceId:insight1</serviceId>"
            "<controlURL>/upnp/control/insight1</controlURL>"
            "<eventSubURL>/upnp/event/insight1</eventSubURL>"
            "<SCPDURL>/insightservice.xml</SCPDURL>"
            "</service>"
            "</serviceList>"
            "</device>"
            "</root>"
        )

        setup_response = self.add_http_headers(setup_xml)
        logger.debug(f"Fauxmo response to setup request:\n{setup_response}")

        if not self.transport:
            raise Exception("No transport")

        self.transport.write(setup_response.encode())
        self.transport.close()

    def handle_action(self, msg: str) -> None:
        """Execute `on`, `off`, or `get_state` method of plugin.

        Args:
            msg: Body of the Echo's HTTP request to trigger an action

        """
        logger.debug(f"Handling action for plugin type {self.plugin}")

        if not self.transport:
            raise Exception("No transport")

        soap_format = (
            "<s:Envelope "
            'xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            "<s:Body>"
            "<u:{action}{action_type}Response "
            'xmlns:u="urn:Belkin:service:{service_type}:1">'
            "<{action_type}>{return_val}</{action_type}>"
            "<CountdownEndTime>0</CountdownEndTime><deviceCurrentTime>1611532922</deviceCurrentTime>"
            "</u:{action}{action_type}Response>"
            "</s:Body>"
            "</s:Envelope>"
        ).format

        command_format = (
            'SOAPACTION:"urn:Belkin:service:basicevent:1#{}"'
        ).format
        
        command_insight_format = (
            'SOAPACTION:"urn:Belkin:service:insight:1#{}"'
        ).format
        
        soap_message: str | None = None
        action: str | None = None
        action_type: str | None = None
        return_val: str | None = None
        service_type: str | None = None
        success: bool = False

        if command_format("GetBinaryState").casefold() in msg.casefold().replace(" ", ""):
            logger.info(f"Attempting to get state for {self.plugin.name}")

            action = "Get"
            action_type = "BinaryState"
            service_type = "basicevent"
            state = self.plugin.get_state().casefold()
            logger.info(f"{self.plugin.name} state: {state}")

            if state in ["off", "on"]:
                success = True
                return_val = str(int(state.lower() == "on"))
        elif command_insight_format("GetInsightParams").casefold() in msg.casefold().replace(" ", ""):
            random_number = random.randint(1000, 300000)
            action = "Get"
            action_type = "InsightParams"
            service_type = "insight"
            return_val = f"8|1549126755|0|0|0|9319|10|{random_number}|0|0.000000|7000"
            success = True
            logger.info(f"{self.plugin.name} returning insight parameters")

        elif command_format("SetBinaryState").casefold() in msg.casefold().replace(" ", ""):
            action = "Set"
            action_type = "BinaryState"
            service_type = "basicevent"
            if "<BinaryState>0</BinaryState>" in msg:
                logger.info(f"Attempting to turn off {self.plugin.name}")
                return_val = "0|1611532923|231|300|183183|1209600|8|1170|1164707|99830512"
                success = self.plugin.off()

            elif "<BinaryState>1</BinaryState>" in msg:
                logger.info(f"Attempting to turn on {self.plugin.name}")
                return_val = "8|1611530424|231|300|183183|1209600|8|1190|1164707|99830512"
                success = self.plugin.on()

            else:
                logger.warning(f"Unrecognized request:\n{msg}")

        elif command_format("GetFriendlyName").casefold() in msg.casefold().replace(" ", ""):
            action = "Get"
            action_type = "FriendlyName"
            service_type = "basicevent"
            return_val = self.plugin.name
            success = True
            logger.info(f"{self.plugin.name} returning friendly name")

        if success:
            soap_message = soap_format(
                action=action, action_type=action_type, service_type=service_type, return_val=return_val
            )

            response = self.add_http_headers(soap_message)
            logger.debug(response)
            self.transport.write(response.encode())
        else:
            errmsg = (
                f"Unable to complete command for {self.plugin.name}:\n{msg}"
            )
            logger.warning(errmsg)
        self.transport.close()

    def handle_insight(self) -> None:
        """Respond to request for insight."""
        if not self.transport:
            raise Exception("No transport")
        
        insight_xml = (
            '<?xml version="1.0"?>'
            '<scpd xmlns="urn:Belkin:service-1-0">'
            "<specVersion>"
            "<major>1</major>"
            "<minor>0</minor>"
            "</specVersion>"
            "<actionList>"
            "<action>"
            "<name>GetPower</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>InstantPower</name>"
            "<relatedStateVariable>InstantPower</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetTodayKWH</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>TodayKWH</name>"
            "<relatedStateVariable>TodayKWH</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>SetAutoPowerThreshold</name>"
            "<argumentList>"
            "<argument>"
            "<name>PowerThreshold</name>"
            "<relatedStateVariable>PowerThreshold</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetPowerThreshold</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>PowerThreshold</name>"
            "<relatedStateVariable>PowerThreshold</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>SetPowerThreshold</name>"
            "<argumentList>"
            "<argument>"
            "<name>PowerThreshold</name>"
            "<relatedStateVariable>PowerThreshold</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>ResetPowerThreshold</name>"
            "<argumentList>"
            "<argument>"
            "<name>PowerThreshold</name>"
            "<relatedStateVariable>PowerThreshold</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetInsightInfo</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>InsightInfo</name>"
            "<relatedStateVariable>InsightInfo</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetInsightParams</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>InsightParams</name>"
            "<relatedStateVariable>InsightParams</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetONFor</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>ONFor</name>"
            "<relatedStateVariable>ONFor</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetInSBYSince</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>InSBYSince</name>"
            "<relatedStateVariable>InSBYSince</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetTodayONTime</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>TodayONTime</name>"
            "<relatedStateVariable>TodayONTime</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetTodaySBYTime</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>TodaySBYTime</name>"
            "<relatedStateVariable>TodaySBYTime</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>ScheduleDataExport</name>"
            "<argumentList>"
            "<argument>"
            "<name>EmailAddress</name>"
            "<relatedStateVariable>EmailAddress</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "<argument>"
            "<name>DataExportType</name>"
            "<relatedStateVariable>DataExportType</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetDataExportInfo</name>"
            "<argumentList>"
            "<argument>"
            "<retval />"
            "<name>LastDataExportTS</name>"
            "<relatedStateVariable>LastDataExportTS</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "<argument>"
            "<retval />"
            "<name>DataExportType</name>"
            "<relatedStateVariable>DataExportType</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "<argument>"
            "<retval />"
            "<name>EmailAddress</name>"
            "<relatedStateVariable>EmailAddress</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "</actionList>"
            "<serviceStateTable>"
            '<stateVariable sendEvents="yes">'
            "<name>InstantPower</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>TodayKWH</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>InsightInfo</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>InsightParams</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>TodayONTime</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>InSBYSince</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>ONFor</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>TodaySBYTime</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>PowerThreshold</name>"
            "<dataType>String</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>EmailAddress</name>"
            "<dataType>string</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>DataExportType</name>"
            "<dataType>string</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>LastDataExportTS</name>"
            "<dataType>string</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            "</serviceStateTable>"
            "</scpd>"
        ) + 2 * Fauxmo.NEWLINE

        insight_response = self.add_http_headers(insight_xml)
        logger.debug(f"Fauxmo response to insight request:\n{insight_response}")
        self.transport.write(insight_response.encode())
        self.transport.close()

    def handle_metainfo(self) -> None:
        """Respond to request for metadata."""
        if not self.transport:
            raise Exception("No transport")

        metainfo_xml = (
            '<scpd xmlns="urn:Belkin:service-1-0">'
            "<specVersion>"
            "<major>1</major>"
            "<minor>0</minor>"
            "</specVersion>"
            "<actionList>"
            "<action>"
            "<name>GetMetaInfo</name>"
            "<argumentList>"
            "<retval />"
            "<name>GetMetaInfo</name>"
            "<relatedStateVariable>MetaInfo</relatedStateVariable>"
            "<direction>in</direction>"
            "</argumentList>"
            "</action>"
            "</actionList>"
            "<serviceStateTable>"
            '<stateVariable sendEvents="yes">'
            "<name>MetaInfo</name>"
            "<dataType>string</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            "</serviceStateTable>"
            "</scpd>"
        ) + 2 * Fauxmo.NEWLINE

        meta_response = self.add_http_headers(metainfo_xml)
        logger.debug(f"Fauxmo response to setup request:\n{meta_response}")
        self.transport.write(meta_response.encode())
        self.transport.close()

    def handle_event(self) -> None:
        """Respond to request for eventservice.xml."""
        if not self.transport:
            raise Exception("No transport")

        eventservice_xml = (
            '<scpd xmlns="urn:Belkin:service-1-0">'
            "<actionList>"
            "<action>"
            "<name>SetBinaryState</name>"
            "<argumentList>"
            "<argument>"
            "<retval/>"
            "<name>BinaryState</name>"
            "<relatedStateVariable>BinaryState</relatedStateVariable>"
            "<direction>in</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "<action>"
            "<name>GetBinaryState</name>"
            "<argumentList>"
            "<argument>"
            "<retval/>"
            "<name>BinaryState</name>"
            "<relatedStateVariable>BinaryState</relatedStateVariable>"
            "<direction>out</direction>"
            "</argument>"
            "</argumentList>"
            "</action>"
            "</actionList>"
            "<serviceStateTable>"
            '<stateVariable sendEvents="yes">'
            "<name>BinaryState</name>"
            "<dataType>Boolean</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            '<stateVariable sendEvents="yes">'
            "<name>level</name>"
            "<dataType>string</dataType>"
            "<defaultValue>0</defaultValue>"
            "</stateVariable>"
            "</serviceStateTable>"
            "</scpd>"
        ) + 2 * Fauxmo.NEWLINE

        event_response = self.add_http_headers(eventservice_xml)
        logger.debug(f"Fauxmo response to setup request:\n{event_response}")
        self.transport.write(event_response.encode())
        self.transport.close()

    @staticmethod
    def add_http_headers(xml: str) -> str:
        """Add HTTP headers to an XML body.

        Args:
            xml: XML body that needs HTTP headers

        """
        date_str = formatdate(timeval=None, localtime=False, usegmt=True)
        return (Fauxmo.NEWLINE).join(
            [
                "HTTP/1.1 200 OK",
                f'CONTENT-LENGTH: {len(xml.encode("utf8"))}',
                "CONTENT-TYPE: text/xml",
                f"DATE: {date_str}",
                "LAST-MODIFIED: Sat, 01 Jan 2000 00:01:15 GMT",
                "SERVER: Unspecified, UPnP/1.0, Unspecified",
                "X-User-Agent: Fauxmo",
                f"CONNECTION: close{Fauxmo.NEWLINE}",
                f"{xml}",
            ]
        )


class SSDPServer(asyncio.DatagramProtocol):
    """UDP server that responds to the Echo's SSDP / UPnP requests."""

    def __init__(self, devices: t.Iterable[dict] | None = None) -> None:
        """Initialize an SSDPServer instance.

        Args:
            devices: Iterable of devices to advertise when the Echo's SSDP
                     search request is received.

        """
        self.devices = list(devices or ())

    def add_device(self, name: str, ip_address: str, port: int) -> None:
        """Keep track of a list of devices for logging and shutdown.

        Args:
            name: Device name
            ip_address: IP address of device
            port: Port of device

        """
        device_dict = {"name": name, "ip_address": ip_address, "port": port}
        self.devices.append(device_dict)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Set transport attribute to incoming transport.

        Args:
            transport: Incoming asyncio.DatagramTransport

        """
        self.transport = cast(asyncio.DatagramTransport, transport)

    def datagram_received(
        self, data: t.Union[bytes, t.Text], addr: t.Tuple[str, int]
    ) -> None:
        """Check incoming UDP data for requests for Wemo devices.

        Args:
            data: Incoming data content
            addr: Address sending data

        """
        if isinstance(data, bytes):
            data = data.decode("utf8")

        logger.debug(f"Received data below from {addr}:")
        logger.debug(data)

        discover_patterns = [
            "ST: urn:Belkin:device:**",
            "ST: urn:Belkin:device:",
            "ST: urn:Belkin:service:basicevent:1",
            "ST: urn:Belkin:service:insight:1",
            "ST: upnp:rootdevice",
            "ST: ssdp:all",
        ]

        discover_pattern = next(
            (pattern for pattern in discover_patterns if pattern in data), None
        )
        if (
            'man: "ssdp:discover"' in data.lower()
            and discover_pattern is not None
        ):
            mx = 0.0
            mx_line = next(
                (
                    line
                    for line in str(data).splitlines()
                    if line.startswith("MX: ")
                ),
                None,
            )
            if mx_line:
                mx_str = mx_line.split()[-1]
                if mx_str.replace(".", "", 1).isnumeric():
                    mx = float(mx_str)

            self.respond_to_search(addr, discover_pattern, mx)

    def respond_to_search(
        self, addr: t.Tuple[str, int], discover_pattern: str, mx: float = 0.0
    ) -> None:
        """Build and send an appropriate response to an SSDP search request.

        Args:
            addr: Address sending search request

        """
        if discover_pattern == "ST: urn:Belkin:device:":
            discover_pattern = "ST: urn:Belkin:device:**"
        
        date_str = formatdate(timeval=None, localtime=False, usegmt=True)
        for device in self.devices:
            name = device["name"]
            ip_address = device.get("ip_address")
            port = device.get("port")

            location = f"http://{ip_address}:{port}/setup.xml"
            serial = make_serial(name)
            usn = (
                f"uuid:Insight-1_0-{serial}::"
                f'{discover_pattern.lstrip("ST: ")}'
            )

            response = (Fauxmo.NEWLINE).join(
                [
                    "HTTP/1.1 200 OK",
                    "CACHE-CONTROL: max-age=86400",
                    f"DATE: {date_str}",
                    "EXT:",
                    f"LOCATION: {location}",
                    'OPT: "http://schemas.upnp.org/upnp/1/0/"; ns=01',
                    f"01-NLS: {uuid.uuid4()}",
                    "SERVER: Unspecified, UPnP/1.0, Unspecified",
                    f"{discover_pattern}",
                    f"USN: {usn}",
                ]
            ) + (2 * Fauxmo.NEWLINE)
            asyncio.ensure_future(
                self._send_async_response(response.encode("utf8"), addr, mx)
            )

    async def _send_async_response(
        self, response: bytes, addr: t.Tuple[str, int], mx: float = 0.0
    ) -> None:
        logger.debug(f"Sending response to {addr} with mx {mx}:\n{response!r}")
        await asyncio.sleep(random.random() * max(0, min(5, mx)))
        self.transport.sendto(response, addr)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle lost connections.

        Args:
            exc: Exception type

        """
        if exc:
            logger.warning(f"SSDPServer closed with exception: {exc}")

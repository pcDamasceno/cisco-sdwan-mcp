"""Representative vManage payloads, trimmed to the fields the tools read."""

DEVICES = [
    {
        "host-name": "BR1-EDGE1",
        "system-ip": "10.0.0.11",
        "site-id": "1001",
        "device-type": "vedge",
        "device-model": "vedge-C8000V",
        "reachability": "reachable",
        "status": "normal",
        "version": "20.9.1",
        "personality": "vedge",
        "uuid": "C8K-AAAA-0001",
        "chasisNumber": "C8K-AAAA-0001",
    },
    {
        "host-name": "BR2-EDGE1",
        "system-ip": "10.0.0.12",
        "site-id": "1002",
        "device-type": "vedge",
        "device-model": "vedge-C8000V",
        "reachability": "unreachable",
        "status": "normal",
        "version": "20.9.1",
        "personality": "vedge",
        "uuid": "C8K-AAAA-0002",
    },
    {
        "host-name": "VSMART1",
        "system-ip": "10.0.0.2",
        "site-id": "1",
        "device-type": "vsmart",
        "device-model": "vsmart",
        "reachability": "reachable",
        "status": "normal",
        "version": "20.9.2",
        "personality": "vsmart",
    },
]

CONTROL_CONNECTIONS = [
    {
        "system-ip": "10.0.0.11",
        "peer-type": "vsmart",
        "peer-system-ip": "10.0.0.2",
        "state": "up",
        "local-color": "mpls",
        "site-id": "1",
        "protocol": "dtls",
    },
    {
        "system-ip": "10.0.0.11",
        "peer-type": "vmanage",
        "peer-system-ip": "10.0.0.1",
        "state": "connect",
        "local-color": "mpls",
        "site-id": "1",
        "protocol": "dtls",
    },
]

BFD_SESSIONS = [
    {
        "system-ip": "10.0.0.11",
        "state": "up",
        "local-color": "mpls",
        "color": "mpls",
        "src-ip": "192.0.2.11",
        "dst-ip": "192.0.2.12",
        "site-id": "1002",
        "uptime": "0:01:22:33",
    },
    {
        "system-ip": "10.0.0.11",
        "state": "down",
        "local-color": "biz-internet",
        "color": "biz-internet",
        "src-ip": "198.51.100.11",
        "dst-ip": "198.51.100.12",
        "site-id": "1002",
    },
]

SYSTEM_STATUS = [
    {
        "vdevice-host-name": "BR1-EDGE1",
        "vdevice-name": "10.0.0.11",
        "state": "green",
        "uptime": "10 days",
        "mem_used": 2048,
        "mem_total": 8192,
        "cpu_idle": 91.5,
        "version": "20.9.1",
        "reboot_reason": "Initiated by user",
    }
]

APPROUTE_STATS = [
    {
        "name": "10.0.0.11:mpls-10.0.0.12:mpls",
        "local_system_ip": "10.0.0.11",
        "remote_system_ip": "10.0.0.12",
        "local_color": "mpls",
        "remote_color": "mpls",
        "latency": 22.0,
        "loss_percentage": 0.1,
        "jitter": 3.0,
        "vqoe_score": 9.8,
    },
    {
        "name": "10.0.0.11:biz-internet-10.0.0.12:biz-internet",
        "local_system_ip": "10.0.0.11",
        "remote_system_ip": "10.0.0.12",
        "local_color": "biz-internet",
        "remote_color": "biz-internet",
        "latency": 310.0,
        "loss_percentage": 7.5,
        "jitter": 45.0,
        "vqoe_score": 3.1,
    },
]

ALARMS = [
    {
        "severity": "critical",
        "component": "BFD",
        "rule_name_display": "BFD_Session_Down",
        "host_name": "BR2-EDGE1",
        "system_ip": "10.0.0.12",
        "active": True,
        "message": "BFD session down",
        "entry_time": 1700000000000,
    },
    {
        "severity": "major",
        "component": "Control",
        "rule_name_display": "Control_Connection_Down",
        "host_name": "BR2-EDGE1",
        "system_ip": "10.0.0.12",
        "active": False,
        "message": "Control connection down",
        "entry_time": 1700000100000,
    },
]

DEVICE_TEMPLATES = [
    {
        "templateId": "tmpl-001",
        "templateName": "Branch-C8000V",
        "templateDescription": "Standard branch template",
        "deviceType": "vedge-C8000V",
        "devicesAttached": 2,
        "configType": "template",
        "factoryDefault": False,
    },
    {
        "templateId": "tmpl-002",
        "templateName": "Unused-Template",
        "deviceType": "vedge-C8000V",
        "devicesAttached": 0,
        "configType": "template",
        "factoryDefault": False,
    },
]

VSMART_POLICIES = [
    {
        "policyId": "pol-001",
        "policyName": "Prod-Central-Policy",
        "policyDescription": "App-route + data policy",
        "isPolicyActivated": True,
        "policyVersion": "3",
    },
    {
        "policyId": "pol-002",
        "policyName": "Maintenance-Policy",
        "isPolicyActivated": False,
        "policyVersion": "1",
    },
]

#: Routes covering the read-only tool surface.
READ_ROUTES = {
    "/dataservice/device": {"data": DEVICES},
    "/dataservice/device/control/connections": {"data": CONTROL_CONNECTIONS},
    "/dataservice/device/bfd/sessions": {"data": BFD_SESSIONS},
    "/dataservice/device/system/status": {"data": SYSTEM_STATUS},
    "/dataservice/device/omp/peers": {"data": []},
    "/dataservice/device/interface": {"data": []},
    "/dataservice/statistics/approute": {"data": APPROUTE_STATS},
    "/dataservice/statistics/interface": {"data": []},
    "/dataservice/alarms": {"data": ALARMS},
    "/dataservice/event": {"data": []},
    "/dataservice/template/device": {"data": DEVICE_TEMPLATES},
    "/dataservice/template/feature": {"data": []},
    "/dataservice/template/policy/vsmart": {"data": VSMART_POLICIES},
    "/dataservice/template/policy/vedge": {"data": []},
    "/dataservice/system/device/vedges": {"data": DEVICES[:2]},
    "/dataservice/system/device/controllers": {"data": DEVICES[2:]},
}

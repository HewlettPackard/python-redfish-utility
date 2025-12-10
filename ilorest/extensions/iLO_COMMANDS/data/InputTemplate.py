template = {
    "commonSettings": {
        "computeOpsManagement": {"activationKey": "ACTIVATION-KEY-XXXX-YYYY-ZZZZ", "workspace_id": "WORKSPACE-ID-PLACEHOLDER-12345"},
        "iloAuthentication": {"iloUser": "GENERIC_ADMIN_USER", "iloPassword": "GENERIC_SECURE_PASSWORD"},
        "network": {"dns": ["203.0.113.10", "203.0.113.11"], "ntp": ["198.51.100.50", "198.51.100.51"]},
        "proxy": {
            "server": "proxy.example.net",
            "port": 8080,
            "credentials": {"username": "PROXY_USER", "password": "PROXY_PASSWORD"},
        },
    },
    "targets": {
        "ilos": {
            "individual": [
                {"ip": "192.0.2.10"},
                {"ip": "192.0.2.11", "network": {"dns": ["203.0.113.20", "203.0.113.21"]}},
                {"ip": "192.0.2.12", "network": {"ntp": ["198.51.100.60", "198.51.100.61"]}, "skipDns": True},
                {"ip": "192.0.2.13", "network": {"dns": ["203.0.113.200"]}, "skipNtp": True},
                {"ip": "192.0.2.14", "skipDns": True, "skipNtp": True},
                {"ip": "192.0.2.15", "skipProxy": True},
                {"ip": "192.0.2.16", "skipDns": True, "skipProxy": True},
            ],
            "ranges": [
                {"start": "192.0.2.100", "end": "192.0.2.110"},
                {"start": "192.0.2.120", "end": "192.0.2.125", "skipNtp": True},
                {"start": "192.0.2.130", "end": "192.0.2.132", "network": {"ntp": ["198.51.100.99"]}},
                {"start": "192.0.2.140", "end": "192.0.2.142", "skipProxy": True},
            ],
        }
    },
}

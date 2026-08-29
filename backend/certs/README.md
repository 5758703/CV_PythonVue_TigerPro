# EMQX TLS CA

将控制台下载的 `emqxsl-ca.crt` 放在本目录。  
后端通过 `MQTT_CA_CERTS=certs/emqxsl-ca.crt`（或绝对路径）加载。

当前部署示例：`deployment-a30f3e71`（深圳 · Serverless），MQTT TLS **8883**，WebSocket TLS **8084**。

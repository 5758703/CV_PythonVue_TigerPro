# Tiger AI · 部署文件

本目录提供 **Docker Compose 实验性编排**。完整操作步骤见文档：

| 文档 | 说明 |
|------|------|
| [docs/deploy/README.md](../docs/deploy/README.md) | 部署总览与选型 |
| [docs/deploy/local.md](../docs/deploy/local.md) | 本地开发（Windows / macOS / Linux） |
| [docs/deploy/linux.md](../docs/deploy/linux.md) | Linux 生产（gunicorn + Nginx） |
| [docs/deploy/docker.md](../docs/deploy/docker.md) | Docker / Compose 详解 |

## 快速 Docker 启动

```bash
cp deploy/.env.example deploy/.env
# 编辑 SECRET_KEY / 数据库密码
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

- 门户：http://localhost/
- 控制台：http://localhost/console/
- 默认账号：`admin` / `admin123`

> 后端镜像含深度学习依赖，**首次构建耗时长、镜像体积大**；详见 docker 文档中的限制说明。

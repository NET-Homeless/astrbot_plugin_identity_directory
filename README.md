# 通讯录（Identity Directory）

跨平台身份通讯录：把 QQ / Rocket.Chat / Telegram / Discord 等平台上散落的账号、群名片归并为"同一个人"，供 bot 认出对方并挂载长期记忆。

## 特性

- **现代化 WebUI**：基于 **Vite+ (`vp`) + Svelte 5 + shadcn-svelte (Nova)** 构建，原生响应式状态与精致组件，无缝适配 AstrBot 亮暗主题。
- **被动全量观察**：通过 AstrBot 自定义过滤器在**不唤醒消息管线**的前提下登记每一位发言者（与 livingmemory 插件同款机制）。
- **稳定身份锚点**：以 `(platform, platform_user_id)` 为唯一身份依据——QQ 号、RC `_id` 这类不可变 ID；群名片/昵称只作显示名历史，绝不作为身份 key。
- **SQLite 持久化**：WAL 模式，存储于 `data/plugin_data/astrbot_plugin_identity_directory/directory.db`，插件升级不丢数据。
- **改名追踪**：自动记录账号用过的显示名（区分平台级昵称与各群名片），供消息提及消歧与"改名前的人是谁"查询。
- **独立 Python API**：其他插件（如记忆插件）可调用 `directory_service` 把 `event` 解析为稳定 `person_id`。

## 数据模型

| 实体 | 说明 | 身份依据 |
|---|---|---|
| **Person** 联系人 | 现实中的人，全局唯一，有规范名/备注/标签 | — |
| **Account** 平台账号 | 某平台一个账号，如 `aiocqhttp:100000001` | `(platform, platform_user_id)`，不可变 |
| **Membership** 群成员 | 账号在某群里的成员关系 | `(account, group_id)`；群名片挂这里，**不同群可有不同名片** |
| **Alias** 显示名历史 | 账号用过的名字，带平台/群作用域与时间 | 仅用于消歧，不作身份 |

## 前端开发与构建

页面源码位于 `web/` 目录：

```bash
cd web

# 开发调试
vp dev

# 校验与代码检查
vp check

# 生产构建（自动输出到 ../pages/directory/）
vp build
```

## 开关（插件配置）

| 配置 | 默认 | 说明 |
|---|---|---|
| `observe_messages` | 开 | 自动登记发言者账号 |
| `auto_track_display_names` | 开 | 显示名变化时记入别名历史 |
| `auto_stub_person` | 开 | 新账号首次发言自动建独立联系人（之后手动合并） |
| `capture_bots` | 关 | 是否登记 bot 账号 |

## 指令

- `/whoami`（`/我是谁`）— 显示当前账号在通讯录里的身份。

## 其他插件调用

```python
plugin = context.get_registered_star("astrbot_plugin_identity_directory")
if plugin and plugin.star_cls:
    service = plugin.star_cls.directory_service
    resolution = await service.resolve_sender("aiocqhttp", "100000001", group_id="100001")
    if resolution and resolution.person:
        name = resolution.person.canonical_name   # 规范名，跨平台稳定
        pid  = resolution.person.person_id         # 稳定身份 ID，用于记忆 tag
```

按显示名查人（提及消歧，群作用域优先）：

```python
candidates = await service.find_by_name("测试用户", platform="aiocqhttp", group_id="100001")
```

## 许可

MIT

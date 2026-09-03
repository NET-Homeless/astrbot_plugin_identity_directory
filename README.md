# 通讯录（Identity Directory）

跨平台身份通讯录：把 QQ / Rocket.Chat / Telegram / Discord 等平台上散落的账号、群名片归并为"同一个人"，供 bot 认出对方并挂载长期记忆。

## 特性

- **现代化 WebUI**：基于 **Vite+ (`vp`) + Svelte 5 + shadcn-svelte (Nova)** 构建，原生响应式状态与精致组件，无缝适配 AstrBot 亮暗主题。
- **被动全量观察**：通过 AstrBot 自定义过滤器在**不唤醒消息管线**的前提下登记每一位发言者（与 livingmemory 插件同款机制）。
- **稳定账号锚点**：以 `(platform, platform_instance_id, platform_user_id)` 为唯一账号依据。相同平台的多个 bot/工作区不会互相串号；群名片和昵称只作显示历史。
- **SQLite 持久化与迁移**：WAL 模式，存储于 `data/plugin_data/astrbot_plugin_identity_directory/directory.db`；schema 自动迁移，升级不丢现有关系。
- **改名追踪**：自动记录账号用过的显示名（区分平台级昵称与各群名片），供消息提及消歧与“改名前的人是谁”查询。
- **Person 记忆作用域**：可直接对接 Hindsight，以稳定 `person_id` 召回/写入记忆；联系人合并后的旧 ID 仍可召回，群聊默认按平台实例和群隔离。
- **独立 Python API**：其他插件可调用 `directory_service`，把 `event` 解析为稳定 `person_id`。

## 数据模型

| 实体 | 说明 | 身份依据 |
|---|---|---|
| **Person** 联系人 | 现实中的人，全局唯一，有规范名/备注/标签 | — |
| **Account** 平台账号 | 某个平台实例中的一个账号 | `(platform, platform_instance_id, platform_user_id)`，不可变 |
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
| `umo_filter_mode` | `blacklist` | 按会话 UMO 选择黑名单或白名单模式。黑名单允许未列出的会话，白名单仅允许列出的会话；名单为空时分别表示允许全部/不允许任何会话。 |
| `umo_filter_list` | 空 | 填写 AstrBot 官方 `unified_msg_origin`（UMO）完整值，例如 `aiocqhttp:GroupMessage:123456789`；会话不在适用名单时不会登记、注入身份或读写本插件记忆。 |
| `auto_track_display_names` | 开 | 显示名变化时记入别名历史 |
| `auto_stub_person` | 开 | 新账号首次发言自动建独立联系人（之后手动合并） |
| `capture_bots` | 关 | 是否登记 bot 账号 |
| `inject_identity_context` | 开 | 向当前 LLM 请求注入已解析的规范名、当前显示名和联系人画像，不写入会话历史。 |
| `allow_self_persona` | 开 | 是否允许成员在私聊或群聊中查看或更新自己的画像；群聊查询仅显示公开画像内容。 |
| `allow_member_lookup` | 关 | 是否允许普通成员在群聊中查询**当前平台实例的本群成员**；结果不会显示账号 ID。关闭时仅管理员可查询。 |
| `hindsight_recall_enabled` | 开 | 从 Hindsight 召回当前 Person 可见的记忆 |
| `hindsight_retain_enabled` | 开 | 以结构化对话和幂等文档 ID 写入当前 Person 作用域 |
| `hindsight_cross_group_memory` | 关 | 开启后同一 Person 可跨私聊/群/平台召回；可能造成跨群信息流动 |
| `hindsight_api_base` | `http://host.docker.internal:8899` | Hindsight API 地址 |
| `hindsight_bank_id` | （空） | Hindsight Bank ID；启用前必须填写 |
| `hindsight_timeout_seconds` | `3` | 召回/写入总超时（最多 3 秒）；失败只跳过增强，不阻断消息 |

## 指令

| 英文指令 | 中文别名 | 权限 | 说明 |
|---|---|---|---|
| `/whoami` | `/我是谁` | 全员 | 显示当前账号在通讯录里的身份与绑定账号总数 |
| `/directory` | `/通讯录` | **管理员，私聊** | 查看全局通讯录统计数据 |
| `/lookup <名字>` | `/查人 <名字>` | **管理员**；成员可选开启 | 管理员私聊可查看当前平台实例的 Person ID 与账号；成员仅可在群聊中查询本群成员且不显示账号 ID |
| `/link` | `/绑定` | 全员 | 申请 6 位绑定码；目标账号提交后，发起账号执行确认即完成合并 |
| `/persona [名字/ID]` | `/画像 [名字/ID]` | **管理员，私聊** | 查看指定联系人的完整画像、关联账号与长期记忆；重名时必须使用 Person ID 消歧 |
| `/self_persona [内容]` | `/自我画像 [内容]` | 全员（可配置） | 在私聊或群聊中查看或更新自己的个人画像；群聊查询仅显示公开画像内容，内容最多 500 字符。 |

### 安全绑定流程

1. 在发起账号发送 `/link` 获取 6 位绑定码。
2. 在目标账号发送 `/link <绑定码>` 提交请求；此时不会修改通讯录。
3. 回到发起账号发送 `/link confirm <绑定码>`；确认命令会立即合并账号。

绑定码 10 分钟有效、仅可绑定一个目标账号，且连续输错 5 次后会临时限制继续尝试。

## 其他插件调用

```python
plugin = context.get_registered_star("astrbot_plugin_identity_directory")
if plugin and plugin.star_cls:
    service = plugin.star_cls.directory_service
    resolution = await service.resolve_sender(
        "aiocqhttp",
        "100000001",
        group_id="100001",
        platform_instance_id="bot-account-1",
    )
    if resolution and resolution.person:
        name = resolution.person.canonical_name  # 规范名，跨平台稳定
        pid = resolution.person.person_id  # 稳定身份 ID，用于记忆 tag
```

按显示名查人（提及消歧，群作用域优先）：

```python
candidates = await service.find_by_name("测试用户", platform="aiocqhttp", group_id="100001")
```

## Hindsight 作用域

- 私聊默认使用 `Person` 作用域：手动绑定到同一联系人的 QQ、Rocket.Chat、Telegram 等账号共享记忆。
- 群聊默认使用 `Person + platform instance + group` 作用域：能认出是同一个人，但不会把一个群里的记忆带到另一个群。
- 明确开启 `hindsight_cross_group_memory` 后，群聊也改用 `Person` 作用域，从而实现跨群记忆；这是隐私边界变更，因此不默认开启。
- 新写入只使用合并后的规范 Person ID；召回同时查询规范 ID 和全部合并来源 ID，合并前的 Person 记忆不会失联。
- 记忆文本按不可信数据注入并进行转义；明显凭据、命令和过短消息不写入。每轮使用稳定 `document_id` 与 `operation_id`，重试不会重复创建文档。

## 许可

[MIT](LICENSE)

# defect-batch v0.1

**Producer:** Agent-1 · **Consumers:** Agent-2, Agent-3

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | string | `"0.1.0"` |
| `productLine` | string | 线别 |
| `posture` | `alpha` \| `beta` | beta = 仅 Open/New 进功能漏斗 |
| `generatedAt` | ISO string | |
| `funnel` | `Record<string, number>` | total / strict / locatable_only / needs_info / hard_reject / security / excluded / duplicate |
| `clusters[]` | cluster | **仅**含 `pool=strict` 的簇 |
| `tickets[]` | ticket | **全量**票（含各 pool） |

### clusters[]

| Field | Type |
|---|---|
| `clusterId` | string (`productLine::module::tag::intent`) |
| `testModule` / `titleTag` / `intent` | string / enum |
| `size` / `openCount` | number |
| `defectIds[]` | string |

### tickets[]

| Field | Type | Notes |
|---|---|---|
| `defectId` / `title` | string | 必填 |
| `pool` | enum | 见漏斗 |
| `clusterId` | string? | 仅 strict 有 |
| `testModule` / `titleTag` / `intent` | ? | L1/L2/L3 |
| `expectQuality` | enum | explicit/inferred/ambiguous/absent |
| `observed` / `expected` / `steps` | string? | 蒸馏切片 |
| `reasonCode` / `reasonDetail` | string? | 非 strict 时常有 |
| `status` / `severity` / … | ? | 透传 |

**禁止字段：** `所属模块` 等闭环字段不得进入契约。

# Column aliases — why the count check exists

Defect platform exports do not have a stable schema. The same product line ships English camelCase one month and Chinese headers the next, and two teams on one project disagree on whether the ID column is `缺陷ID` or `缺陷单号`.

`prepare-batch` maps columns through an alias table inside the executable. A column it does not recognise is silently skipped, so the two facts to establish before trusting any number are: how many rows were in the file, and how many made it through. That is what `agent1 preflight` reports.

## Known-good spellings

| Contract field | Accepted column names (first non-empty hit wins) |
|---|---|
| `defectId` | `defectId`, `缺陷单号`, `缺陷ID`, `缺陷编号`, `ID`, `id` |
| `title` | `defectTitle`, `缺陷标题`, `标题`, `title` |
| `description` | `describle`, `defectDescribe`, `缺陷描述`, `描述`, `description` |
| `status` | `defectStatus`, `缺陷状态`, `状态`, `status` |
| `flowStatus` | `flowStatusName`, `flowStatus`, `流程状态` |
| `testModule` | `testModule`, `测试模块`, `所属模块` |
| `fieldType` | `defectType`, `类型`, `缺陷类型`, `type`, `fieldType` |
| `severity` | `severityName`, `severity`, `严重级别` |
| `createdAt` | `createDate`, `createdAt`, `创建时间` |
| `duplicateOf` | `duplicateOf`, `关联重复缺陷编号`, `关联缺陷ID`, `relateDefectId` |

`describle` is not our typo — that is the platform's spelling and it must stay or the largest export format breaks.

`测试模块` is preferred over `所属模块` because one real export ships both: `测试模块` is filled at creation, `所属模块` is only filled when the ticket is closed, so on that export every open ticket has an empty `所属模块`.

## When preflight says MISS

The mapping is data, not logic: adding a spelling does not change any decision the funnel makes, so it is a safe change. This packaged skill ships only the executable, so **you cannot add a spelling here** — the alias table is compiled in. Report the missing spelling (exact header text) to whoever maintains `bugfix_agent/ingest/field_map.py`; the CSV and xlsx paths both read that one table, so one edit fixes both.

They drifted once: `缺陷单号` was in neither, so every Chinese web export mapped zero rows. That is why the two paths now share a single table instead of each carrying its own copy.

**Do not "fix" a missing column by editing the CSV by hand.** The batch then no longer corresponds to the file the user handed you, and nobody can reproduce the funnel from the original export. If you need a temporary shim because you cannot change the package, write a rename-only adapter, say so explicitly in your report, and keep the row count identical.

## What is dropped on purpose

Columns that are not screening inputs (`检出活动`, `出现概率`, `缺陷/建议`, `所属软件`, `版本号`, `项目编号`, `当前处理人`, `发现人`, `解决人`, …) are not part of the delivered artifact. `RawDefect.metadata` carries the English export's extras in memory, but `BatchTicket` has no metadata field, so nothing below `description` survives into `defect-batch.json`.

That is a real limitation, not an oversight to work around: if a `needs_info` ticket needs its missing detail chased, the original export is still the only place to find out who to ask.

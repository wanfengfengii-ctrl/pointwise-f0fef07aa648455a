# 固定日账的修订区间交接

README.md 说明源接纳、质控、封账和隔离站现有用法。夜班使用同一个日账号读取固定原账和该日封账前的逐槽账态。

## 接口和账态

- 在 `seal.cut` 提供 `close_day_with_history(source, archive, day, revision, *, before_commit=None) -> str`。日号、修订校验、账号形状、回调时点和异常沿用 `close_day`。回调或提交失败抛 `PublicationError`，该次账号不可领取，既有成果仍可领取。
- 在 `rehearsal.report` 提供 `read_slot_history(store, account, slot)`。返回按起点升序排列的 `tuple`，每项为 `(start, end, row)`，边界是整数，`row` 为 `archive.payloads.LedgerRow` 或 `None`。槽号沿用原标识规则，非法槽号抛 `ValueError`，未知账号沿用 `UnknownDay`。旧件缺历史时抛 `rehearsal.report.HistoryUnavailable`，继承 `LookupError`。
- 修订 r 的状态等于按原口径封存该日修订 r 后，该槽在原账中的行或空槽。一次源接纳事务中的所有记录在同一修订可见。版序和处置序仅比较该修订已经可见的记录。
- 封存修订 R 的历史以半开区间无重叠地覆盖 `[1,R+1)`。空槽用 `None`，合法未知槽返回 `((1, R+1, None),)`。相邻区间仅在整条 `LedgerRow` 相等或同为 `None` 时合并，并交付最大连续区间。

## 固定件交接

- 历史与原账在同一固定账号下一起发布。`export_fixed_day`、`accept_fixed_day` 和 `exchange_day` 交接新旧固定件，隔离库无须源库或发布库便可领取。`read_day` 与 `simulate` 对新件仍按固定终截面的原有口径工作。普通 `close_day` 仍产出原格式，已有 V1 件的规范化字节保持原样。
- 新件是与 V1 共享 `account`、`day`、`revision`、`original` 和 `evidence` 字段及其格式的 UTF-8 JSON，`format` 为整数 `2`，另有 `history` 字段。账号以外层的 `account` 为准，`history` 的内部表示由实现方决定。同号同件按原入口的规范化比较幂等，原账相同而历史不同的合法新件抛 `ExchangeConflict`，保留首次固定结果。
- 接纳时验证历史的修订边界、覆盖、出处引用和末态。历史中的非空账行须对应件内原观测的槽、观测号、原批和精确读数。若证据声明接纳事件，事务分组与目标可见性也须符合原源接口。末修订各槽状态须与 `original` 一致。无效件抛 `InvalidPayload`，不新增账号或更改已有成果。

允许全量重算。简述发布方保证的历史含义、接纳时可核对的条件及隔离站如何保证领取一致。

## 样例与运行

A 提交 S01/a/10，B 提交同槽较高版序 S01/b/20，H 禁用 a。A→B→H 和 A→H→B 在修订 3 的原账均为 S01/b/B/20。前者的 S01 区间为 `[1,2)` 取 a、`[2,4)` 取 b；后者为 `[1,2)` 取 a、`[2,3)` 为空、`[3,4)` 取 b。

封账和交接前可运行 `python3.11 -B history_examples.py fixture` 查看 V1 的逐截面参照。新增入口完成后，`python3.11 -B history_examples.py verify` 核对实际交接和隔离库重开，`python3.11 -B history_examples.py demo` 展示两种交班的区间、出处及终账。将两条新增核验和演示分别接入 `.pointwise-runtime.json` 现有 `verify` 和 `demo` 对应流程，保留原回归及原演示。验证失败须非零退出。

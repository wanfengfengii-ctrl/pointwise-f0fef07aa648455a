# 清溪水质观测湖

清溪区水质资料中心用这套程序接纳仪器批、登记质控处置、固定日账并交接到隔离站。夜班在来源停供后，可以按日账号核对出处，并试算剔除可疑原批的替代账。程序使用 Python 3.11 标准库和 SQLite。

## 运行

```sh
python3.11 -B shift.py verify
python3.11 -B shift.py demo
```

`verify` 执行完整业务回归。`demo` 显式载入 `samples/day_shift.json`，创建独立临时库，演示断源复核、提交失败回滚及更正后同时领取新旧日账。每个库通过对象的 `initialize()` 首次建表，重复执行保留既有数据。日常业务应使用各自选定的源库、封账库和隔离库路径。

## Python 接口

```python
from archive.exchange import accept_fixed_day, export_fixed_day
from archive.lookup import read_day
from archive.storage import ArchiveStore
from intake.batches import admit
from intake.observations import ObservationInput
from intake.source_store import SourceStore
from quality.dispositions import add_disposition
from rehearsal.report import simulate
from seal.cut import close_day

source = SourceStore('source.sqlite')
published = ArchiveStore('published.sqlite')
station = ArchiveStore('station.sqlite')
for store in (source, published, station):
    store.initialize()

day = '2026-01-14'
admit(source, day, 'A', [ObservationInput('S01', 'a', 1, 10)])
add_disposition(source, day, 'H', 'a', 1, 'disable')
admit(source, day, 'B', [ObservationInput('S01', 'b', 2, 20)])
revision = add_disposition(source, day, 'B', 'a', 2, 'enable')
account = close_day(source, published, day, revision)
accept_fixed_day(station, export_fixed_day(published, account))
original = read_day(station, account)
without_b = simulate(station, account, {'B'})
without_b_and_h = simulate(station, account, {'B', 'H'})
```

- `admit(source, day, batch, records)` 返回 `AdmissionReceipt`，包含 `revision` 和按输入顺序排列的 `observation_ids`。日号、槽号、原批号和观测号是非空字符串，无首尾空白、NUL 或无效 UTF-8 字符。源库的观测号唯一。同一日、槽和版序只能接纳一条观测。批必须至少含一条观测。字段或身份冲突抛出 `AdmissionError`，整个批回滚。
- `add_disposition(source, day, batch, observation_id, sequence, action)` 返回同日新修订。同日历史观测也可登记，目标未知、跨日、字段非法或同观测处置序冲突抛出 `DispositionError`。同日同一原批可以贡献观测、处置或两者。
- `close_day(source, archive, day, revision, *, before_commit=None)` 返回形如 `D-` 加 32 位小写十六进制的固定日账号。未找到该日修订时抛出 `UnknownRevision`。同一有效修订可另外封存一份新号。可选的 `before_commit(account)` 在目录和载荷写入后、提交前运行，用于模拟发布中断。回调异常或归档数据库提交错误表现为 `PublicationError`，失败件不可领取。
- `export_fixed_day(store, account)` 返回版本 1 的 UTF-8 JSON 字节。`accept_fixed_day(store, data)` 原子接纳并返回账号。`exchange_day(published, station, account)` 完成上述两步。重投同一规范化固定件返回原账号。非法件抛出 `InvalidPayload`，同号异件抛出 `ExchangeConflict`。账行顺序固定，证据中批次、候选、处置数组的排列无业务含义。`samples/manual_fixed_day.json` 是可直接接纳的有限样例。
- `read_day(store, account)` 和 `simulate(store, account, bad_batches=())` 返回 `Ledger`，包含按槽号排序的 `rows`、`count` 和 `total`。每行含 `slot`、`observation_id`、`batch` 和 `reading`。未知账号抛出 `UnknownDay`。剔除参数可传入一组批号，重复批号只计一次。非法参数抛出 `InvalidQuarantine`，任一批号不属于该件时整次抛出 `UnknownBatch`。试算不写入归档库。

## 日账口径

版序、处置序和读数为整数，读数单位为微单位。每条留存观测以目标所剩最高处置序决定资格。最高处置为禁用时排除，为解禁或没有处置时可用。每槽选可用候选中版序最高的一条。合法零值照常计入条数，缺报和无可用观测的槽省略，空账返回零条和总和 0。固定件与源库用精确十进制表示保存相关整数，账目以 Python 整数求和。

交接件同时保存原账与所选源修订的历史观测、历史处置和原批目录。样例原账是 `S01/b/B/20`。剔除 B 后，H 仍禁用 a，得到空账。再剔除 H 后，得到 `S01/a/A/10`。更正 C 封账后新号读回 30，旧号仍读回 20，并保留原有试算结果。

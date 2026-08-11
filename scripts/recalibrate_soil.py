#!/usr/bin/env python3
"""土壤湿度历史数据重校准脚本。

背景：旧的 VAL_WATER（6883）偏低，导致土壤湿度百分比整体偏高，
大量读数被钳制在 100%（溢出）。校准后发现真实田间持水量对应的
ADC 值约为 7491。本脚本用正确的 VAL_WATER 重新计算历史数据。

能救多少：
  - 0 < 旧百分比 < 100 的读数（约 72%）：可完全恢复--
    反推原始 ADC 值（soil_adc_raw），用新基准重新计算百分比。
  - 旧百分比 = 100 的读数（约 28%）：原始 ADC 值已丢失（被钳制时丢失），
    百分比维持 100.0（用新基准算仍然 >=100，所以 100 是正确的）。
  - 旧百分比 = 0 或 NULL：维持原值。

数学原理：
  旧公式：pct_old = (VAL_AIR - raw) / (VAL_AIR - old_VAL_WATER) * 100
  反推：   raw = VAL_AIR - (pct_old / 100) * (VAL_AIR - old_VAL_WATER)
  新公式：pct_new = (VAL_AIR - raw) / (VAL_AIR - new_VAL_WATER) * 100
  合并：   pct_new = pct_old * (VAL_AIR - old_VAL_WATER) / (VAL_AIR - new_VAL_WATER)

用法：
  # 预览（dry-run，不写入）
  python3 scripts/recalibrate_soil.py

  # 实际执行
  python3 scripts/recalibrate_soil.py --apply

  # 自定义校准值
  python3 scripts/recalibrate_soil.py --val-air 17545 --old-val-water 6883 --new-val-water 7491 --apply
"""

import argparse
import os
import sqlite3
import sys

# 让脚本能直接 python scripts/recalibrate_soil.py 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.paths import DB_FILE  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="重校准土壤湿度历史数据")
    p.add_argument("--db-path", default=DB_FILE, help=f"数据库路径（默认 {DB_FILE}）")
    p.add_argument("--val-air", type=float, default=17545, help="干燥空气 ADC 基准值（默认 17545）")
    p.add_argument("--old-val-water", type=float, default=6883, help="旧的 100% 湿度 ADC 基准（默认 6883）")
    p.add_argument("--new-val-water", type=float, default=7491, help="新的 100% 湿度 ADC 基准（默认 7491）")
    p.add_argument("--apply", action="store_true", help="实际执行写入（默认只预览）")
    return p.parse_args()


def check_column_exists(conn, table, column):
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    return column in cols


def show_stats(conn, val_air, old_vw, new_vw):
    """显示当前数据分布与重校准预览。"""
    ratio = (val_air - old_vw) / (val_air - new_vw)

    print(f"\n{'='*60}")
    print(f"  VAL_AIR       = {val_air}")
    print(f"  old VAL_WATER = {old_vw}")
    print(f"  new VAL_WATER = {new_vw}")
    print(f"  重校准比例    = {ratio:.6f}  (new_pct = old_pct × {ratio:.4f})")
    print(f"{'='*60}\n")

    # node_data 统计
    row = conn.execute("""
        SELECT
          COUNT(*),
          SUM(CASE WHEN soil_moisture >= 100 THEN 1 ELSE 0 END),
          SUM(CASE WHEN soil_moisture > 0 AND soil_moisture < 100 THEN 1 ELSE 0 END),
          SUM(CASE WHEN soil_moisture = 0 OR soil_moisture IS NULL THEN 1 ELSE 0 END)
        FROM node_data WHERE soil_moisture IS NOT NULL
    """).fetchone()
    total, capped, recoverable, dry = row

    print(f"  node_data (soil_moisture 非空):")
    print(f"    总行数              {total}")
    print(f"    100% 钳制（不可恢复） {capped}  ({capped*100//max(total,1)}%)")
    print(f"    0-100%（可完全恢复） {recoverable}  ({recoverable*100//max(total,1)}%)")
    print(f"    0 或 NULL（维持原值） {dry}")
    print()

    # 预览几个样本
    print(f"  {'旧百分比':>10} → {'新百分比':>10}   {'反推 raw ADC':>14}")
    print(f"  {'-'*10}   {'-'*10}   {'-'*14}")
    for old_pct in [20.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 94.0, 94.3, 95.0, 99.0, 100.0]:
        if old_pct >= 100:
            new_pct = 100.0
            raw = None
        else:
            raw = val_air - (old_pct / 100.0) * (val_air - old_vw)
            new_pct = min(100.0, old_pct * ratio)
        raw_str = f"{raw:.1f}" if raw is not None else "  (丢失)"
        print(f"  {old_pct:>10.1f} → {new_pct:>10.1f}   {raw_str:>14}")

    # watering_log 统计
    wl = conn.execute("""
        SELECT COUNT(*),
          SUM(CASE WHEN soil_before >= 100 THEN 1 ELSE 0 END),
          SUM(CASE WHEN soil_before > 0 AND soil_before < 100 THEN 1 ELSE 0 END)
        FROM watering_log WHERE soil_before IS NOT NULL
    """).fetchone()
    if wl and wl[0] > 0:
        print(f"\n  watering_log (soil_before 非空):")
        print(f"    总行数              {wl[0]}")
        print(f"    100% 钳制            {wl[1]}")
        print(f"    可恢复               {wl[2]}")

    print()


def run_migration(conn, val_air, old_vw, new_vw, apply_changes):
    """执行重校准。返回 (node_data 更新行数, watering_log 更新行数)。"""
    ratio = (val_air - old_vw) / (val_air - new_vw)

    # 1. 确保 soil_adc_raw 列存在
    if not check_column_exists(conn, "node_data", "soil_adc_raw"):
        if apply_changes:
            conn.execute("ALTER TABLE node_data ADD COLUMN soil_adc_raw REAL")
            print("  ✅ 已添加 soil_adc_raw 列")
        else:
            print("  [预览] 将添加 soil_adc_raw 列")

    # 2. node_data: 反推 raw + 重算百分比
    #
    # 只处理 soil_adc_raw IS NULL 的行（幂等：已处理的行不会重复计算）。
    # 对 0 < soil_moisture < 100 的行：
    #   raw = VAL_AIR - (pct/100) * (VAL_AIR - old_VAL_WATER)
    #   new_pct = min(100, pct * ratio)
    # 对 soil_moisture >= 100 的行：raw 丢失，维持 100.0。
    nd_count = conn.execute("""
        SELECT COUNT(*) FROM node_data
        WHERE soil_adc_raw IS NULL AND soil_moisture IS NOT NULL
    """).fetchone()[0]

    if nd_count > 0:
        if apply_changes:
            # 可恢复的行：反推 raw + 重算 pct
            conn.execute("""
                UPDATE node_data SET
                    soil_adc_raw = ROUND(:val_air - (soil_moisture / 100.0) * (:val_air - :old_vw), 1),
                    soil_moisture = ROUND(MIN(100.0, soil_moisture * :ratio), 1)
                WHERE soil_adc_raw IS NULL
                  AND soil_moisture > 0 AND soil_moisture < 100.0
            """, {"val_air": val_air, "old_vw": old_vw, "ratio": ratio})

            # 100% 钳制的行：raw 丢失，pct 维持 100.0（无需 UPDATE）
            # 但标记一下已处理（soil_adc_raw 仍为 NULL，是"已处理但不可恢复"的语义）
            # 这里不加标记——soil_adc_raw IS NULL 对 100% 行天然表示"不可恢复"

            nd_updated = conn.execute("""
                SELECT COUNT(*) FROM node_data
                WHERE soil_adc_raw IS NOT NULL
            """).fetchone()[0]
            print(f"  ✅ node_data: 反推 raw ADC + 重算百分比 ({nd_updated} 行)")
            print(f"     (另有 {nd_count - nd_updated} 行为 100% 钳制，raw 不可恢复，维持 100.0)")
        else:
            recoverable = conn.execute("""
                SELECT COUNT(*) FROM node_data
                WHERE soil_adc_raw IS NULL AND soil_moisture > 0 AND soil_moisture < 100.0
            """).fetchone()[0]
            capped = conn.execute("""
                SELECT COUNT(*) FROM node_data
                WHERE soil_adc_raw IS NULL AND soil_moisture >= 100.0
            """).fetchone()[0]
            print(f"  [预览] node_data: 将恢复 {recoverable} 行的 raw ADC + 重算百分比")
            print(f"  [预览] node_data: {capped} 行为 100% 钳制，维持 100.0（raw 丢失）")
    else:
        print("  ℹ️  node_data: 无需迁移（soil_adc_raw 已全部填充或无数据）")

    # 3. watering_log: 重算 soil_before
    #
    # 注意：watering_log 没有 soil_adc_raw 列，无法用同样的幂等检查。
    # 这里用 node_data 的迁移状态作为代理：如果 node_data 没有需要迁移的行，
    # 说明已经迁移过，watering_log 也跳过。
    if nd_count > 0:
        wl_recoverable = conn.execute("""
            SELECT COUNT(*) FROM watering_log
            WHERE soil_before > 0 AND soil_before < 100.0
        """).fetchone()[0]

        if wl_recoverable > 0:
            if apply_changes:
                conn.execute("""
                    UPDATE watering_log SET
                        soil_before = ROUND(MIN(100.0, soil_before * :ratio), 1)
                    WHERE soil_before > 0 AND soil_before < 100.0
                """, {"ratio": ratio})
                print(f"  ✅ watering_log: 重算 soil_before ({wl_recoverable} 行)")
            else:
                print(f"  [预览] watering_log: 将重算 {wl_recoverable} 行的 soil_before")

    return nd_count


def verify(conn, val_air, new_vw):
    """迁移后验证：抽样检查几个数据点。"""
    print(f"\n  迁移后抽样验证:")
    print(f"  {'时间':>20}  {'soil_moisture':>14}  {'soil_adc_raw':>14}")
    print(f"  {'-'*20}  {'-'*14}  {'-'*14}")

    rows = conn.execute("""
        SELECT datetime(timestamp, 'localtime'), soil_moisture, soil_adc_raw
        FROM node_data
        WHERE soil_adc_raw IS NOT NULL
        ORDER BY timestamp DESC LIMIT 5
    """).fetchall()
    for ts, pct, raw in rows:
        print(f"  {ts:>20}  {pct:>14.1f}  {raw:>14.1f}")

    # 验证反推一致性：raw -> pct 应与存储的 pct 一致
    mismatch = conn.execute("""
        SELECT COUNT(*) FROM node_data
        WHERE soil_adc_raw IS NOT NULL
          AND ABS(soil_moisture - ROUND(MIN(100.0, 
              (:val_air - soil_adc_raw) / (:val_air - :new_vw) * 100.0), 1)) > 0.2
    """, {"val_air": val_air, "new_vw": new_vw}).fetchone()[0]
    if mismatch > 0:
        print(f"\n  ⚠️  {mismatch} 行的 soil_moisture 与 soil_adc_raw 不一致（可能因四舍五入）")
    else:
        print(f"\n  ✅ 一致性检查通过")


def main():
    args = parse_args()

    if not os.path.exists(args.db_path):
        print(f"错误：数据库文件 '{args.db_path}' 不存在", file=sys.stderr)
        sys.exit(1)

    print(f"数据库: {args.db_path}")
    if not args.apply:
        print("⚠️  预览模式（加 --apply 实际执行）")

    conn = sqlite3.connect(args.db_path)
    try:
        show_stats(conn, args.val_air, args.old_val_water, args.new_val_water)

        if not args.apply:
            print(f"{'='*60}")
            print("  预览完成。加 --apply 执行写入。")
            print(f"{'='*60}")
        else:
            print(f"{'='*60}")
            print("  执行重校准...")
            print(f"{'='*60}\n")
            run_migration(conn, args.val_air, args.old_val_water, args.new_val_water, apply_changes=True)
            conn.commit()
            print(f"\n  ✅ 重校准完成，已提交事务\n")
            verify(conn, args.val_air, args.new_val_water)
    except Exception as e:
        conn.rollback()
        print(f"\n❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

# 校准闸门（CI 自动生效）

把**真实校准件**放进来，CI 就会自动把 `calibrate` 当闸门跑：

```
calibration/
  judge_scores.json     # rag-eval judge 的输出
  human_labels.jsonl    # 人工标注（100~300 条为宜）
```

两个文件同时存在时，CI 的 `calibrate` job 激活，κ < 0.6 会让构建失败——
这正是「rubric 改坏了就拦住」的机制（《检测RAG质量.md》§50）。

只有样例、没有真实校准件时该 job 自动跳过，不拖累构建。

**放进来之前**：这两个文件含标注数据，公开仓库请评估是否入库；
私有仓库无此顾虑。本目录下的样例请勿直接当真实校准件使用。

用法（本地先验一遍）：

```bash
python -m rag_eval.cli calibrate \
    --judge-scores calibration/judge_scores.json \
    --human-labels calibration/human_labels.jsonl
# κ 均值 >= 0.6 才放量；否则改 rubric 重测
```

## 标注工作流（从零开始）

1. `labeling_worksheet.md` —— 人读的标注工作表（每题附真值与证据要点）
2. `labeling_template.jsonl` —— 可直接填的骨架（50 行，过 schema 校验）
3. 开标：按工作表把 `correct` / `faithful` / `complete` 填成 0/1
   （无答案题另填 `abstain_ok`；`labeler` 改成标注员名）
4. 填完的文件重命名为 `human_labels.jsonl` 放进本目录；
   同时把对应作答的 `judge` 输出命名为 `judge_scores.json` 放进来
5. 推送 → CI 的 `calibrate` job 自动开闸

**注意**：`human_labels.jsonl` 的 (question_id, system_name) 必须与
`judge_scores.json` 有交集，否则配对数为 0，闸门按「样本不足」拦下。

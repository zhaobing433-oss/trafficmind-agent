# 钱塘 Pilot 隔离演示运行时

`demo_manifest.json` 只引用已经审核的 G1/G2/G3 数据包。数据库、RAG SQLite、FTS 与
Chroma 文件由 `python -m backend.tools.materialize_qiantang_demo` 生成到本目录的
`runtime/` 下，并受 `.gitignore` 排除。

当前事件是钱塘真实地理上的合成验证数据；公开历史事件有独立来源；系统回放 Case
只证明 TrafficMind 闭环可以执行，不代表真实交通部门采用过系统方案，也不声称实际
交通处置效果。

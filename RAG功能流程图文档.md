# RAG 功能流程图

## 基础 RAG 流程图

```mermaid
flowchart TD
    ST([开始]) --> A[用户提交问题<br/>POST /api/ai/chat]
    A --> B[进入检索入口<br/>rag_service.search(query, top_k)]
    B --> C[向量化并相似度检索<br/>get_embedding + dense_search]
    C --> D[关键词检索<br/>bm25_search]
    D --> E[两路排序融合<br/>rrf(k=RRF_K)]
    E --> F{是否召回候选？}
    F -- 无候选 --> G[关键词打分兜底<br/>_keyword_fallback]
    G --> H[精排重排序<br/>rerank(query, hits)]
    F -- 有候选 --> H
    H --> I[子块回填父块<br/>_expand_to_parents]
    I --> J{上下文是否为空？}
    J -- 为空 --> K[返回拒答话术<br/>OFF_TOPIC_ANSWER]
    K --> Z([结束])
    J -- 非空 --> L[拼接上下文并组装提示词<br/>generate_answer(query, context)]
    L --> M[调用大模型生成<br/>ai_service.ask(temperature=0.1, top_p=0.3)]
    M --> N[返回答案与来源<br/>answer + sources]
    N --> Z
```

## 进阶 RAG 流程图

```mermaid
flowchart TD
    ST([开始]) --> A[用户提交问题<br/>POST /api/ai/chat]
    A --> B[按问题特征选择策略<br/>answer_with_strategy + route_strategy]
    B --> C{问题属于哪一类？}
    C -- 判断确认类 --> D[Self-RAG：检索后自评<br/>SelfRAG(_retrieve, _generate).run()]
    C -- 复合多实体类 --> E[Corrective：相关性过滤<br/>CorrectiveRAG(_retrieve, _generate).run()]
    C -- 其余常规类 --> F[标准链路：直接生成<br/>_retrieve + _generate]
    D -->|自评不合格，反思后重试| D
    E -->|全部不相关，重写后重试| E
    D -->|高级链路异常，回落标准| F
    E -->|高级链路异常，回落标准| F
    D --> G[共用检索入口<br/>rag_service.search(query, top_k)]
    E --> G
    F --> G
    G --> H[检索前预处理<br/>QueryPreprocessor.process()]
    H --> I[多路召回融合<br/>MultiRecall.rrf_fusion()]
    I --> J[精排与父块回填<br/>rerank + _expand_to_parents]
    J --> K{上下文是否为空？}
    K -- 为空 --> L[返回拒答话术<br/>OFF_TOPIC_ANSWER]
    L --> Z([结束])
    K -- 非空 --> M[防幻觉生成<br/>generate_answer(temperature=0.1, top_p=0.3)]
    M --> N[返回答案与策略步骤<br/>answer + strategy + steps]
    N --> Z
```

## 知识图谱 RAG 流程图

```mermaid
flowchart TD
    ST([开始]) --> A[用户提交问题<br/>POST /api/ai/chat use_graph=true]
    A --> B[双通道问答主流程<br/>answer_with_graph + search_with_graph]
    B --> C[图谱通道<br/>GraphQueryEngine.query(question)]
    B --> D[向量通道<br/>search + QueryPreprocessor + MultiRecall + rerank]
    C --> E[实体识别与消歧<br/>EntityExtractor.extract + canonicalize]
    E --> F[生成查询语句<br/>get_schema + CypherGenerator.generate]
    F --> G[执行查询并绑定参数<br/>execute_cypher + build_params]
    G --> H[格式化结构化记录<br/>_format_records]
    D --> I[按优先级与配额融合<br/>_truncate_by_tokens + _build_priority_hint]
    H --> I
    I --> J{两路是否都未命中？}
    J -- 都未命中 --> K[直接返回拒答话术<br/>不调用大模型]
    K --> Z([结束])
    J -- 至少一路命中 --> L[组装融合提示词<br/>GRAPH_FUSION_PROMPT.format]
    L --> M[调用大模型生成<br/>ai_service.ask(temperature=0.1, top_p=0.3)]
    M --> N[返回答案与图谱调试信息<br/>graph_hit + graph_cypher]
    N --> Z
```

## 知识库上传流程图

```mermaid
flowchart TD
    ST([开始]) --> A[管理员上传文件<br/>UploadModal el-upload + upload_knowledge]
    A --> B{文件类型是否允许？}
    B -- 类型不支持 --> C[返回 400 参数错误<br/>is_allowed 校验失败]
    C --> Z([结束])
    B -- 类型允许 --> D{文件大小是否超限？}
    D -- 超过上限 --> C
    D -- 大小合规 --> E[保存文件并写入台账<br/>save_upload_file + KnowledgeFile + db.commit]
    E --> F[提取文件文本<br/>utils/file_utils.extract_text]
    F --> G{是否提取到文本？}
    G -- 无文本 --> H[台账置为失败<br/>status = 失败]
    H --> Z
    G -- 提取成功 --> I[父块与子块切分<br/>split_text + split_child_text]
    I --> J{是否切出有效块？}
    J -- 无有效块 --> H
    J -- 有有效块 --> K[子块向量化并写入向量库<br/>get_embedding + Chroma col.add]
    K --> L{向量化是否成功？}
    L -- 失败 --> H
    L -- 成功 --> M[父块入库并回写状态<br/>put_parents + chunk_count + status = 已向量化]
    M --> N[返回上传成功<br/>code 200 + file_id]
    N --> Z
```

## 项目志愿填报流程图

```mermaid
flowchart TD
    ST([开始]) --> A[考生进入页面并选择科目成绩类型<br/>Volunteer.vue + onDimensionChange + loadLines]
    A --> B[输入预估分数并调用体检接口<br/>form.score + GET /api/meta/score-check]
    B --> C{分数是否在有效区间？}
    C -- 超出区间 --> D[页面提示修正分数<br/>scoreError 置错]
    D --> B
    C -- 区间合法 --> E[换算位次并推荐批次<br/>rank_service.score_check]
    E --> F{分数是否达到最低批次线？}
    F -- 未达到，清空位次 --> B
    F -- 达到 --> G[填入位次与批次并点击生成<br/>form.rank + form.batch + onRecommend]
    G --> H{必填信息是否完整？}
    H -- 信息缺失 --> I[提示补充必填项<br/>ElMessage.warning]
    I --> G
    H -- 信息完整 --> J[提交请求并查询数据表<br/>POST /api/recommend + _fetch_candidates + _plan_index]
    J --> K[去重匹配分档并填充概率<br/>_dedupe + _lookup_plan + subject_match + split_tiers + _to_item + _probability]
    K --> L{三档结果是否为空？}
    L -- 结果为空 --> M[提示放宽筛选条件<br/>ElMessage.info]
    M --> Z([结束])
    L -- 有推荐结果 --> N[前端展示冲稳保三档<br/>result.chong + wen + bao]
    N --> Z
```

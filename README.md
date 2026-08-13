# 语音对话生成器

上传多角色对话文本（chatlog）或给定场景，按角色分配音色，生成多人语音对话音频。

## 功能（M1）

- 上传 CSV/文本 chatlog，自动识别角色和对话轮次
- 输入单个场景，调用 DeepSeek 生成多角色对话脚本
- 一次输入最多 10 个场景，并发生成多份脚本，支持部分成功、结果预览与 JSON 下载
- 为每个角色分配固定 MiniMax 音色，保证多轮声音一致
- 逐轮调用 MiniMax TTS，并按可调句间停顿拼接完整 MP3
- 试听和下载最终音频

## 环境要求

- Python 3.9+
- Node.js 18+
- ffmpeg（pydub 依赖，`brew install ffmpeg`）

## 启动方式

后端：

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # 填入 MINIMAX_API_KEY 和 DEEPSEEK_API_KEY
python app.py
```

前端：

```bash
cd frontend
npm install
npm run dev
```

前端默认 http://localhost:5173 ，通过 Vite 代理转发 `/api` 到后端 http://localhost:5001 。

## DeepSeek 脚本生成

单场景和批量脚本生成均使用 DeepSeek 官方 OpenAI 兼容接口：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BATCH_CONCURRENCY=3
```

如需优先速度和成本，可将模型改为 `deepseek-v4-flash`。批量模式默认最多提交 10 个场景、并发 3 个请求；每项独立返回成功或失败，不会因单项错误丢失整批结果。

## MiniMax 国际版与多角色音色

TTS 默认使用国际版 `https://api.minimax.io` 和 `speech-2.8-turbo`，不读取 GroupId。多个音色通过一个 JSON 数组配置：

```env
MINIMAX_VOICES_JSON='[{"voice_id":"voice_for_agent","name":"客服","language":"Yue"},{"voice_id":"voice_for_customer","name":"客户","language":"Yue"}]'
```

每个对象必须包含唯一的 `voice_id` 和显示用 `name`，可选 `language`。前端把每个角色映射到一个 `voice_id`，后端在该角色的每一轮复用同一 ID。需要更多角色时继续向数组追加对象即可。

## 待办

- 声音克隆支持
- 历史记录/项目管理
- 后台任务与进度恢复

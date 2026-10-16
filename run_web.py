"""PyCharm可直接运行的网页入口，凭证从.env或运行配置读取。"""
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=False)

if __name__ == "__main__":
    import uvicorn
    from init_web_db import initialize
    from web_config import WebConfig
    try:
        cfg = WebConfig.from_env()
        initialize(cfg, create_database=True)
    except Exception as exc:
        print("启动配置或数据库初始化失败：", type(exc).__name__)
        print("请检查MYSQL_PASSWORD及MySQL服务；详细步骤见README.md。")
        raise SystemExit(1)
    print("打开 http://127.0.0.1:8000 ，模式：", cfg.mode)
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, workers=1,
                log_level="info", access_log=False)
